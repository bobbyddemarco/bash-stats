#!/usr/bin/env python3
"""
generate_bash_stats_site.py

Regenerates the entire "Bobby's Summer Bash" stats website from a raw
games CSV. Run this once a year after adding the new games to the CSV,
upload the contents of the output folder to your S3 bucket, and you're
done.

USAGE:
    python3 generate_bash_stats_site.py rawGames.csv --outdir site

WHAT IT PRODUCES (all in --outdir):
    - one <person>StatsAllTime.html per person
    - one <game>.html per game/sport
    - bashStatsNames.html   (overall rankings, all people, all games)
    - bashGamesSportsList.html (index of every game/sport)
    - allGames.html         (raw, unfiltered table of every game ever played)
    - style.css             (shared stylesheet used by every page)

HOW TO EXTEND FOR NEXT YEAR:
    1. Add new rows to the CSV as usual.
    2. If a NEW person or NEW game/sport shows up that has never been
       played before, this script will auto-generate a reasonable slug
       for them (see slugify()) and print a warning. Check the warning,
       and if you want a different display name or filename than the
       auto-generated one, add an entry to PERSON_OVERRIDES or
       GAME_OVERRIDES below.
    3. Re-run the script. It regenerates every page from scratch, so it's
       always safe to re-run.

CONFIG YOU MAY WANT TO TOUCH EACH YEAR:
    - EXCLUDE_GAMES: games that happened but shouldn't count (like the
      Thumb Wrestle one-off).
    - EXCLUDE_PEOPLE: people who only played to fill out teams and don't
      want individual stats tracked (like Julie). NOTE: excluding a
      person only hides THEIR stats -- their teammates still get full
      credit for the win/loss, since the game still happened.
"""

import argparse
import csv
import os
import re
from collections import defaultdict

# ---------------------------------------------------------------------------
# CONFIG -- edit this section as your group's games/roster change over time
# ---------------------------------------------------------------------------

# Games that were played but shouldn't count toward anyone's record.
EXCLUDE_GAMES = {"Thumb Wrestle"}

# People who should never appear in the stats output. Their teammates
# still get credit for games they played together.
EXCLUDE_PEOPLE = {"Julie"}

# S3 bucket (or wherever you host) base URL. All internal links point here.
BASE_URL = "https://bobbyddemarco.github.io/bash-stats"

# Manual overrides for game display name / filename slug, keyed by the
# exact "Game" value as it appears in the CSV. Use this when the
# auto-generated slug (see slugify()) isn't what you want -- e.g. the
# CSV says "Magic Cards" but you want the page to say "Magic" and live
# at magic.html, or a name needs a hyphenated slug like "Billiards - 9 Ball".
GAME_OVERRIDES = {
    "Magic Cards": ("Magic", "magic.html"),
    "Billiards - 9 Ball": ("Billiards - 9 Ball", "billiards-9-ball.html"),
    "Liars Dice": ("Liar's Dice", "liarsDice.html"),
}

# Manual overrides for person display name / filename slug, keyed by the
# exact name as it appears in the CSV (winning/losing team columns).
PERSON_OVERRIDES = {
    "Kevin B": ("Kevin", "kevinStatsAllTime.html"),
}

# Games/people already in the CSV as of this script's last update, using
# the plain auto-generated slug (no override needed). Anyone/anything in
# here is treated as "already known" so the pipeline won't warn about
# them every year -- only genuinely NEW names trigger a warning. When you
# see a "[new game]" or "[new person]" warning and you're happy with the
# auto-generated slug, add that name to the matching set below so it
# stops warning on future runs.
KNOWN_GAMES = {
    "Cornhole", "Wiffleball", "Spikeball", "Billiards", "Table Hockey",
    "Volleyball", "Polish Horseshoes", "Kan Jam", "Triathalon",
    "Beer Ball", "Badminton", "Chameleon", "Wingspan", "Flip Cup",
}
KNOWN_PEOPLE = {
    "Bobby", "Jorge", "John", "Ari", "Scott", "Steve", "Impalli", "Mike G",
    "Nick", "Tommy", "Ralph", "Mike A", "Mike K", "Joe", "Erik",
}

# ---------------------------------------------------------------------------
# SLUG GENERATION -- shouldn't need to touch this
# ---------------------------------------------------------------------------

def slugify_camel(name: str) -> str:
    """Turn 'Table Hockey' into 'tableHockey'. Used as the default slug
    for any game/person not listed in the OVERRIDES dicts above."""
    words = re.findall(r"[A-Za-z0-9]+", name)
    if not words:
        return "unknown"
    first = words[0].lower()
    rest = "".join(w.capitalize() for w in words[1:])
    return first + rest


def get_game_display_and_slug(game, seen_warnings):
    if game in GAME_OVERRIDES:
        return GAME_OVERRIDES[game]
    slug = slugify_camel(game) + ".html"
    if game not in KNOWN_GAMES and game not in seen_warnings:
        print("  [NEW GAME] " + repr(game) + " hasn't been seen before -- "
              "auto-generated slug " + repr(slug) + ". If that looks "
              "right, add it to KNOWN_GAMES. Otherwise add an entry to "
              "GAME_OVERRIDES.")
        seen_warnings.add(game)
    return (game, slug)


def get_person_display_and_slug(person, seen_warnings):
    if person in PERSON_OVERRIDES:
        return PERSON_OVERRIDES[person]
    slug = slugify_camel(person) + "StatsAllTime.html"
    if person not in KNOWN_PEOPLE and person not in seen_warnings:
        print("  [NEW PERSON] " + repr(person) + " hasn't been seen before "
              "-- auto-generated slug " + repr(slug) + ". If that looks "
              "right, add it to KNOWN_PEOPLE. Otherwise add an entry to "
              "PERSON_OVERRIDES.")
        seen_warnings.add(person)
    return (person, slug)


# ---------------------------------------------------------------------------
# DATA LOADING + STATS
# ---------------------------------------------------------------------------

def load_rows(csv_path):
    with open(csv_path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def compute_stats(rows):
    """Returns (pg, person_total, game_person, person_years, game_years)."""
    pg = defaultdict(lambda: [0, 0])                      # (person, game) -> [W, L]
    person_total = defaultdict(lambda: [0, 0])             # person -> [W, L]
    game_person = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # game -> person -> [W, L]
    person_years = defaultdict(set)
    game_years = defaultdict(set)

    for r in rows:
        game = r["Game"].strip()
        if game in EXCLUDE_GAMES:
            continue
        year = int(r["Year"])
        winners = [x.strip() for x in r["Winning Team"].split(",") if x.strip()]
        losers = [x.strip() for x in r["Losing Team"].split(",") if x.strip()]
        game_years[game].add(year)
        for w in winners:
            if w in EXCLUDE_PEOPLE:
                continue
            pg[(w, game)][0] += 1
            person_total[w][0] += 1
            game_person[game][w][0] += 1
            person_years[w].add(year)
        for l in losers:
            if l in EXCLUDE_PEOPLE:
                continue
            pg[(l, game)][1] += 1
            person_total[l][1] += 1
            game_person[game][l][1] += 1
            person_years[l].add(year)

    return pg, person_total, game_person, person_years, game_years


def pct(w, l):
    total = w + l
    return (w / total) if total > 0 else 0.0


def sort_key(name, w, l):
    """Sort by win% desc. Ties broken by games played: more games is
    'better' at/above 50%, fewer games is 'better' below 50%. Final tie
    broken alphabetically."""
    p = pct(w, l)
    games = w + l
    secondary = -games if p >= 0.5 else games
    return (-p, secondary, name)


# ---------------------------------------------------------------------------
# HTML TEMPLATES
# ---------------------------------------------------------------------------

NAV_HTML = f"""  <nav class="bash-nav">
    <ul>
      <li><strong>Bobby's Summer Bash</strong></li>
    </ul>
    <ul>
      <li><a href="{BASE_URL}bashStatsNames.html">Overall Stats</a></li>
      <li><a href="{BASE_URL}bashGamesSportsList.html">Games / Sports</a></li>
      <li><a href="{BASE_URL}bashPictures.html">Pictures</a></li>
      <li><a href="{BASE_URL}allGames.html">All Games</a></li>
    </ul>
  </nav>
"""

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
  <link rel="stylesheet" href="{base}style.css">
</head>
<body>
{nav}
{body}
  <footer>
    <small>Bobby's Summer Bash &middot; Est. 2022</small>
  </footer>
</body>
</html>
"""


def render_page(title, body_html):
    return PAGE_TEMPLATE.format(title=title, base=BASE_URL, nav=NAV_HTML, body=body_html)


def render_person_page(display, slug_for_game, entries, tot_w, tot_l, yr_min, yr_max):
    rows_html = ""
    for g, w, l, p in entries:
        gdisplay, gslug = slug_for_game(g)
        rows_html += (
            f"      <tr><td><a href=\"{BASE_URL}{gslug}\">{gdisplay}</a></td>"
            f"<td>{w}</td><td>{l}</td><td>{round(p*100)}%</td></tr>\n"
        )
    tot_pct = pct(tot_w, tot_l)
    body = f"""  <hgroup>
    <h1>{display}</h1>
    <p>{yr_min} - {yr_max}</p>
  </hgroup>

  <table>
    <thead>
      <tr><th>Game</th><th>Wins</th><th>Losses</th><th>Win %</th></tr>
    </thead>
    <tbody>
{rows_html}    </tbody>
    <tfoot>
      <tr><td><strong>Total</strong></td><td><strong>{tot_w}</strong></td>
      <td><strong>{tot_l}</strong></td><td><strong>{round(tot_pct*100)}%</strong></td></tr>
    </tfoot>
  </table>
"""
    return render_page(f"Bash Stats — {display}", body)


def render_game_page(display, slug_for_person, entries, yr_min, yr_max):
    rows_html = ""
    for p2, w, l, pc in entries:
        pdisplay, pslug = slug_for_person(p2)
        rows_html += (
            f"      <tr><td><a href=\"{BASE_URL}{pslug}\">{pdisplay}</a></td>"
            f"<td>{w}-{l}</td><td>{round(pc*100)}%</td></tr>\n"
        )
    body = f"""  <hgroup>
    <h1>{display}</h1>
    <p>{yr_min} - {yr_max}</p>
  </hgroup>

  <table>
    <thead>
      <tr><th>Name</th><th>Record</th><th>Win %</th></tr>
    </thead>
    <tbody>
{rows_html}    </tbody>
  </table>
"""
    return render_page(f"Bash Stats — {display}", body)


MEDALS = {0: "\U0001F947", 1: "\U0001F948", 2: "\U0001F949"}


def render_overall_page(slug_for_person, overall):
    rows_html = ""
    for i, (p, w, l, pc) in enumerate(overall):
        pdisplay, pslug = slug_for_person(p)
        rank_cell = MEDALS.get(i, str(i + 1))
        row_class = ' class="top3"' if i < 3 else ""
        rows_html += (
            f"      <tr{row_class}><td>{rank_cell}</td>"
            f"<td><a href=\"{BASE_URL}{pslug}\">{pdisplay}</a></td>"
            f"<td>{w}-{l}</td><td>{round(pc*100)}%</td></tr>\n"
        )
    body = f"""  <hgroup>
    <h1>Overall rankings</h1>
    <p>All games and sports combined</p>
  </hgroup>

  <table>
    <thead>
      <tr><th>#</th><th>Name</th><th>Record</th><th>Win %</th></tr>
    </thead>
    <tbody>
{rows_html}    </tbody>
  </table>
"""
    return render_page("Bash Stats — Overall Rankings", body)


def render_sports_list_page(games_sorted, slug_for_game):
    rows_html = ""
    for g in games_sorted:
        gdisplay, gslug = slug_for_game(g)
        rows_html += f"      <tr><td><a href=\"{BASE_URL}{gslug}\">{gdisplay}</a></td></tr>\n"
    body = f"""  <hgroup>
    <h1>Games / Sports</h1>
  </hgroup>

  <table>
    <tbody>
{rows_html}    </tbody>
  </table>
"""
    return render_page("Bash Stats — Games / Sports", body)


def render_all_games_page(rows):
    thead = (
        "      <tr><th>#</th><th>Year</th><th>Time</th><th>Game</th>"
        "<th>Winning Team</th><th>Losing Team</th><th>Score</th><th>Notes</th></tr>\n"
    )
    body_rows = ""
    for i, r in enumerate(rows):
        body_rows += (
            f"      <tr><td>{i}</td><td>{r['Year']}</td><td>{r['Time']}</td>"
            f"<td>{r['Game']}</td><td>{r['Winning Team']}</td>"
            f"<td>{r['Losing Team']}</td><td>{r.get('Score','')}</td>"
            f"<td>{r.get('Notes','')}</td></tr>\n"
        )
    body = f"""  <hgroup>
    <h1>All games</h1>
    <p>Complete unfiltered history, every game ever played</p>
  </hgroup>

  <table>
    <thead>
{thead}    </thead>
    <tbody>
{body_rows}    </tbody>
  </table>
"""
    return render_page("Bash Stats — All Games", body)


STYLE_CSS = """body { max-width: 900px; margin: 0 auto; padding: 1rem; }
nav.bash-nav ul { gap: 1.5rem; }
tr.top3 td { background: var(--pico-mark-background-color); }
table td, table th { text-align: center; }
table td:first-child, table th:first-child { text-align: left; }
"""


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Regenerate the Bash Stats site from a CSV.")
    parser.add_argument("csv_path", help="Path to the raw games CSV")
    parser.add_argument("--outdir", default="site", help="Output directory (default: site)")
    args = parser.parse_args()

    rows = load_rows(args.csv_path)
    pg, person_total, game_person, person_years, game_years = compute_stats(rows)

    os.makedirs(args.outdir, exist_ok=True)

    game_warned, person_warned = set(), set()
    slug_for_game = lambda g: get_game_display_and_slug(g, game_warned)
    slug_for_person = lambda p: get_person_display_and_slug(p, person_warned)

    print("Generating person pages...")
    for person in sorted(set(p for (p, g) in pg)):
        display, slug = slug_for_person(person)
        entries = [(g, w, l, pct(w, l)) for (p, g), (w, l) in pg.items() if p == person]
        entries.sort(key=lambda x: sort_key(x[0], x[1], x[2]))
        tot_w, tot_l = person_total[person]
        yr_min, yr_max = min(person_years[person]), max(person_years[person])
        html = render_person_page(display, slug_for_game, entries, tot_w, tot_l, yr_min, yr_max)
        with open(os.path.join(args.outdir, slug), "w") as f:
            f.write(html)

    print("Generating game pages...")
    for game in sorted(game_person.keys()):
        display, slug = slug_for_game(game)
        entries = [(p2, w, l, pct(w, l)) for p2, (w, l) in game_person[game].items()]
        entries.sort(key=lambda x: sort_key(x[0], x[1], x[2]))
        yr_min, yr_max = min(game_years[game]), max(game_years[game])
        html = render_game_page(display, slug_for_person, entries, yr_min, yr_max)
        with open(os.path.join(args.outdir, slug), "w") as f:
            f.write(html)

    print("Generating overall rankings page...")
    overall = [(p, w, l, pct(w, l)) for p, (w, l) in person_total.items()]
    overall.sort(key=lambda x: sort_key(x[0], x[1], x[2]))
    html = render_overall_page(slug_for_person, overall)
    with open(os.path.join(args.outdir, "bashStatsNames.html"), "w") as f:
        f.write(html)

    print("Generating games/sports index page...")
    games_sorted = sorted(game_person.keys(), key=lambda g: slug_for_game(g)[0])
    html = render_sports_list_page(games_sorted, slug_for_game)
    with open(os.path.join(args.outdir, "bashGamesSportsList.html"), "w") as f:
        f.write(html)

    print("Generating raw all-games page...")
    html = render_all_games_page(rows)
    with open(os.path.join(args.outdir, "allGames.html"), "w") as f:
        f.write(html)

    with open(os.path.join(args.outdir, "style.css"), "w") as f:
        f.write(STYLE_CSS)

    print(f"\nDone. {len(os.listdir(args.outdir))} files written to '{args.outdir}/'.")
    print("Upload the contents of that folder to your S3 bucket and you're set.")


if __name__ == "__main__":
    main()
