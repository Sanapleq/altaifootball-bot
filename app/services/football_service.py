"""Футбольный сервис — слой бизнес-логики.

Оборачивает парсер, добавляет кэширование, обработку ошибок
и предоставляет удобный API для handlers.
"""

from __future__ import annotations

from typing import Optional

from app.logger import logger
from app.models.football import League, Match, StandingRow, Team
from app.services.cache import cache
from app.services.parser import SiteParser, SiteParserError


class FootballService:
    """Сервис для работы с футбольными данными.

    Координирует парсер и кеш, обрабатывает ошибки.
    """

    def __init__(self) -> None:
        self._parser = SiteParser()

    async def close(self) -> None:
        """Закрыть ресурсы."""
        await self._parser.close()

    # ========================================================================
    # ЛИГИ
    # ========================================================================

    async def get_leagues(self) -> list[League]:
        """Получить список лиг (из кеша или с парсинга)."""
        cached = await cache.get_leagues()
        if cached is not None:
            logger.debug("Лиги загружены из кеша")
            return cached

        try:
            leagues = await self._parser.get_leagues()
            await cache.set_leagues(leagues)
            return leagues
        except Exception as e:
            logger.error(f"Ошибка получения лиг: {e}")
            return []

    async def get_league_by_id(self, league_id: str) -> Optional[League]:
        """Найти лигу по ID."""
        leagues = await self.get_leagues()
        for league in leagues:
            if league.id == league_id:
                return league
        return None

    # ========================================================================
    # КОМАНДЫ
    # ========================================================================

    async def get_league_teams(self, league: League) -> list[Team]:
        """Получить команды лиги."""
        cached = await cache.get_teams(league.id)
        if cached is not None:
            logger.debug(f"Команды лиги {league.name} загружены из кеша")
            return cached

        try:
            teams = await self._parser.get_league_teams(league)
            # Проставляем league_id (на случай если парсер не проставил)
            for team in teams:
                team.league_id = league.id
            await cache.set_teams(league.id, teams)
            return teams
        except Exception as e:
            logger.error(f"Ошибка получения команд лиги {league.name}: {e}")
            return []

    # ========================================================================
    # ТУРНИРНАЯ ТАБЛИЦА
    # ========================================================================

    async def get_league_standings(self, league: League) -> list[StandingRow]:
        """Получить турнирную таблицу."""
        cached = await cache.get_standings(league.id)
        if cached is not None:
            logger.debug(f"Таблица лиги {league.name} загружена из кеша")
            return cached

        try:
            standings = await self._parser.get_league_standings(league.url)
            await cache.set_standings(league.id, standings)
            return standings
        except Exception as e:
            logger.error(f"Ошибка получения таблицы лиги {league.name}: {e}")
            return []

    # ========================================================================
    # МАТЧИ КОМАНДЫ
    # ========================================================================

    async def get_team_matches(self, team: Team) -> list[Match]:
        """Получить все матчи команды."""
        cache_key = f"team_matches:{team.id}"
        cached = await cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Матчи команды {team.name} загружены из кеша")
            return cached

        try:
            matches = await self._parser.get_team_matches(team.url)
            await cache.set_matches(cache_key, matches)
            return matches
        except Exception as e:
            logger.error(f"Ошибка получения матчей команды {team.name}: {e}")
            return []

    async def get_team_upcoming_matches(self, team: Team) -> list[Match]:
        """Получить предстоящие матчи команды.

        Делегирует парсеру — тот сам фильтрует по дате.
        """
        return await self._parser.get_team_upcoming_matches(team.url)

    async def get_team_recent_results(self, team: Team) -> list[Match]:
        """Получить последние результаты команды.

        Делегирует парсеру — тот сам фильтрует по дате.
        """
        return await self._parser.get_team_recent_results(team.url)

    async def get_team_position_in_table(self, team: Team, league: Optional[League] = None) -> Optional[StandingRow]:
        """Получить позицию команды в таблице.

        Если лига не указана, пытаемся определить из team.league_id.
        """
        target_league = league
        if target_league is None and team.league_id:
            target_league = await self.get_league_by_id(team.league_id)

        if target_league is None:
            logger.warning(f"Не удалось определить лигу для команды {team.name}")
            return None

        standings = await self.get_league_standings(target_league)
        for row in standings:
            if row.team_name.lower() == team.name.lower():
                return row

        return None

    # ========================================================================
    # МАТЧИ ЛИГИ
    # ========================================================================

    async def get_league_upcoming_matches(self, league: League) -> list[Match]:
        """Получить предстоящие матчи лиги."""
        cache_key = f"league_upcoming:{league.id}"
        cached = await cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            matches = await self._parser.get_league_upcoming_matches(league.url)
            await cache.set_matches(cache_key, matches)
            return matches
        except Exception as e:
            logger.error(f"Ошибка получения предстоящих матчей лиги {league.name}: {e}")
            return []

    async def get_league_recent_results(self, league: League) -> list[Match]:
        """Получить последние результаты лиги."""
        cache_key = f"league_recent:{league.id}"
        cached = await cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            matches = await self._parser.get_league_recent_results(league.url)
            await cache.set_matches(cache_key, matches)
            return matches
        except Exception as e:
            logger.error(f"Ошибка получения результатов лиги {league.name}: {e}")
            return []

    # ========================================================================
    # ПОИСК
    # ========================================================================

    async def search_teams(self, query: str) -> list[Team]:
        """Поиск команды по названию."""
        if len(query) < 2:
            return []

        cached = await cache.get_search(query)
        if cached is not None:
            return cached

        try:
            teams = await self._parser.search_teams(query)
            await cache.set_search(query, teams)
            return teams
        except Exception as e:
            logger.error(f"Ошибка поиска команд по запросу '{query}': {e}")
            return []

    # ========================================================================
    # УТИЛИТЫ
    # ========================================================================

    async def invalidate_cache(self) -> None:
        """Полностью очистить кеш."""
        await cache.clear()
        logger.info("Кеш очищен")

    async def cleanup_cache(self) -> int:
        """Очистить протухшие записи кеша."""
        return await cache.cleanup()
