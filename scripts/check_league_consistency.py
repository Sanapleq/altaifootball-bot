"""Sanity-check: сверка W/D/L команды с таблицей лиги по fixtures.

Пример:
    python -m scripts.check_league_consistency --league-id 3607
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from app.services.parser import SiteParser
from app.utils.text import clean_text


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "site_html"


def _load_html(filename: str) -> str:
    path = FIXTURES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    return path.read_text(encoding="utf-8")


def _parse_team_finished_record(parser: SiteParser, html: str, team_url: str) -> tuple[str, int, int, int]:
    soup = BeautifulSoup(html, "lxml")
    team_name = parser._extract_current_team_name(soup) or "unknown"

    matches = []
    for table in soup.find_all("table", class_="table_box_row"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header = " ".join(clean_text(c.get_text()).lower() for c in rows[0].find_all(["th", "td"]))
        if "дата" not in header or "соперник" not in header:
            continue
        for row in rows[1:]:
            match = parser._parse_team_match_row(row, team_name, team_url)
            if match and match.is_finished and match.home_score is not None and match.away_score is not None:
                matches.append(match)
        break

    wins = sum(1 for m in matches if m.home_score > m.away_score)
    draws = sum(1 for m in matches if m.home_score == m.away_score)
    losses = sum(1 for m in matches if m.home_score < m.away_score)
    return team_name, wins, draws, losses


def run_check(league_id: str) -> dict:
    parser = SiteParser()
    league_filename = f"league_{league_id}.html"
    league_html = _load_html(league_filename)
    league_soup = BeautifulSoup(league_html, "lxml")

    table = league_soup.find("table", class_="table_box_row")
    if table is None:
        raise RuntimeError(f"Standings table not found in {league_filename}")

    standings_rows = parser._parse_standings_table_box(table)
    by_name = {row.team_name: row for row in standings_rows}

    report = {
        "league_id": league_id,
        "checked": [],
        "mismatches": [],
        "missing_fixtures": [],
    }

    for row in standings_rows:
        team_url = row.team_url or ""
        team_id_match = re.search(r"/teams/(\d+)/", team_url)
        if not team_id_match:
            continue
        team_id = team_id_match.group(1)
        fixture_name = f"team_{team_id}.html"
        fixture_path = FIXTURES_DIR / fixture_name
        if not fixture_path.exists():
            report["missing_fixtures"].append(fixture_name)
            continue

        html = fixture_path.read_text(encoding="utf-8")
        team_name, wins, draws, losses = _parse_team_finished_record(parser, html, team_url)
        entry = {
            "fixture": fixture_name,
            "team_name": team_name,
            "standings_name": row.team_name,
            "fixture_wdl": [wins, draws, losses],
            "standings_wdl": [row.wins, row.draws, row.losses],
        }
        report["checked"].append(entry)
        if (wins, draws, losses) != (row.wins, row.draws, row.losses):
            report["mismatches"].append(entry)

    report["ok"] = not report["mismatches"] and not report["missing_fixtures"]
    return report


def main() -> int:
    argp = argparse.ArgumentParser(description="Сверка W/D/L по fixtures и таблице лиги")
    argp.add_argument("--league-id", required=True, help="ID лиги (например 3607)")
    args = argp.parse_args()

    report = run_check(args.league_id)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
