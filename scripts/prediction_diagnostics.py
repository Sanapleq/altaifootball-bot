"""CLI-утилита диагностики источников прогноза.

Пример:
    python -m scripts.prediction_diagnostics --team "СКА Сибирский ЗАТО" --league-id 3607
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Optional

from app.models.football import League, Team
from app.services.football_service import FootballService


async def _resolve_league(service: FootballService, league_id: Optional[str]) -> Optional[League]:
    if not league_id:
        return None
    return await service.get_league_by_id(league_id)


async def _resolve_team(
    service: FootballService,
    team_query: str,
    league: Optional[League],
) -> Optional[Team]:
    query_norm = team_query.strip().lower()

    if league is not None:
        teams = await service.get_league_teams(league)
        exact = next((t for t in teams if t.name.lower() == query_norm), None)
        if exact:
            return exact
        partial = [t for t in teams if query_norm in t.name.lower()]
        if len(partial) == 1:
            return partial[0]

    found = await service.search_teams(team_query)
    if not found:
        return None
    exact = next((t for t in found if t.name.lower() == query_norm), None)
    if exact:
        return exact
    return found[0]


async def run(team_query: str, league_id: Optional[str]) -> int:
    service = FootballService()
    try:
        league = await _resolve_league(service, league_id)
        team = await _resolve_team(service, team_query, league)
        if team is None:
            print(json.dumps({"error": "team_not_found", "team_query": team_query}, ensure_ascii=False, indent=2))
            return 1

        diagnostics = await service.get_prediction_diagnostics(team)
        if diagnostics is None:
            print(
                json.dumps(
                    {
                        "team": team.name,
                        "status": "no_upcoming_matches",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        print(json.dumps(diagnostics, ensure_ascii=False, indent=2))
        return 0
    finally:
        await service.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Диагностика источников прогноза по команде")
    parser.add_argument("--team", required=True, help="Название команды (например: СКА Сибирский ЗАТО)")
    parser.add_argument("--league-id", help="ID лиги для ускоренного поиска команды (например: 3607)")
    args = parser.parse_args()
    return asyncio.run(run(args.team, args.league_id))


if __name__ == "__main__":
    sys.exit(main())
