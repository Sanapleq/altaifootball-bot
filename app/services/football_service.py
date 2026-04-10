"""Футбольный сервис — слой бизнес-логики.

Оборачивает парсер, добавляет кэширование, обработку ошибок
и предоставляет удобный API для handlers.
"""

from __future__ import annotations

from datetime import datetime
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

    def get_cache_stats(self) -> dict:
        """Получить статистику кеша для диагностики."""
        return cache.get_stats()

    # ========================================================================
    # ЛИГИ
    # ========================================================================

    async def get_leagues(self) -> list[League]:
        """Получить список лиг (из кеша или с парсинга)."""
        cached = await cache.get_leagues()
        if cached is not None:
            logger.debug("[service] Лиги загружены из кеша (%d шт)", len(cached))
            return cached

        try:
            leagues = await self._parser.get_leagues()
            await cache.set_leagues(leagues)
            logger.debug("[service] Лиги загружены с сайта, закэшировано: %d", len(leagues))
            return leagues
        except Exception as e:
            logger.error("[service] Ошибка получения лиг: %s", e)
            return []

    async def get_leagues_by_season(self, season: str) -> list[League]:
        """Получить лиги конкретного сезона."""
        all_leagues = await self.get_leagues()
        filtered = [lg for lg in all_leagues if lg.season == season]
        logger.debug("[service] Лиги сезона '%s': %d из %d", season, len(filtered), len(all_leagues))
        return filtered

    async def get_available_seasons(self) -> list[str]:
        """Получить список доступных сезонов (отсортированных по убыванию)."""
        all_leagues = await self.get_leagues()
        seasons = set()
        for lg in all_leagues:
            if lg.season:
                seasons.add(lg.season)
        return sorted(seasons, reverse=True)

    async def _get_current_season(self) -> str:
        """Определить текущий сезон из данных.

        Стратегия: берём самый последний сезон из доступных.
        Если год текущего сезона совпадает с реальным годом —
        считаем его текущим. Иначе — последний доступный.
        """
        from datetime import datetime
        seasons = await self.get_available_seasons()
        if not seasons:
            return str(datetime.now().year)

        current_year = str(datetime.now().year)
        # Если самый свежий сезон — это текущий или следующий год, считаем его текущим
        latest = seasons[0]
        if latest == current_year or latest == str(int(current_year) + 1):
            return latest
        # Иначе всё равно берём последний доступный как «текущий»
        return latest

    async def get_current_season_leagues(self) -> list[League]:
        """Получить лиги текущего сезона."""
        season = await self._get_current_season()
        return await self.get_leagues_by_season(season)

    async def get_archive_seasons(self) -> list[str]:
        """Получить архивные сезоны (все кроме текущего)."""
        current = await self._get_current_season()
        all_seasons = await self.get_available_seasons()
        return [s for s in all_seasons if s != current]

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
            logger.debug("[service] Команды лиги '%s' из кеша (%d шт)", league.name, len(cached))
            return cached

        try:
            teams = await self._parser.get_league_teams(league)
            for team in teams:
                team.league_id = league.id
            await cache.set_teams(league.id, teams)
            logger.debug("[service] Команды лиги '%s' загружены с сайта: %d", league.name, len(teams))
            return teams
        except Exception as e:
            logger.error("[service] Ошибка получения команд лиги '%s': %s", league.name, e)
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
        """Получить все матчи команды.

        Стратегия:
        1. Получить кандидатов со страницы команды (ссылки + даты).
        2. Для сыгранных матчей — парсить boxscore (источник истины).
        3. Для будущих матчей — парсить preview.
        4. Если boxscore/preview недоступен — использовать кандидата как fallback.

        Args:
            team: Объект команды.

        Returns:
            Список подтверждённых Match.
        """
        cache_key = f"team_matches_confirmed:{team.id}"
        cached = await cache.get(cache_key)
        if cached is not None:
            logger.debug("[service] Матчи команды '%s' из кеша", team.name)
            return cached

        # 1. Кандидаты со страницы команды
        candidates = await self._parser.get_team_match_candidates(team.url)
        if not candidates:
            return []

        confirmed: list[Match] = []
        fallback: list[Match] = []

        for c in candidates:
            if c.match_url and "/preview/" in c.match_url:
                # Будущий матч → preview
                preview = await self._parser.get_match_preview(c.match_url)
                if preview:
                    confirmed.append(preview)
                else:
                    fallback.append(c.as_match())
            elif c.match_url and "/boxscore/" in c.match_url:
                # Сыгранный матч → boxscore
                boxscore = await self._parser.get_match_boxscore(c.match_url)
                if boxscore:
                    confirmed.append(boxscore)
                else:
                    fallback.append(c.as_match())
            else:
                # Нет ссылки — fallback
                fallback.append(c.as_match())

        # Приоритет источников:
        # 1) подтверждённые матчи (boxscore/preview)
        # 2) fallback только для неподтверждённых строк
        # Это предотвращает потерю валидных boxscore/preview из-за
        # "переключения" всего списка на fallback.
        seen_keys: set[tuple[str, str, object]] = set()
        result: list[Match] = []

        def _match_key(m: Match) -> tuple[str, str, object]:
            date_key = m.match_date.date().isoformat() if m.match_date else None
            return (m.home_team.strip().lower(), m.away_team.strip().lower(), date_key)

        for m in confirmed:
            key = _match_key(m)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            result.append(m)

        for m in fallback:
            key = _match_key(m)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            result.append(m)

        await cache.set_matches(cache_key, result)
        logger.info(
            "[service] Матчи '%s': подтверждено=%d, fallback=%d, использовано=%d",
            team.name, len(confirmed), len(fallback), len(result)
        )
        return result

    async def get_team_upcoming_matches(self, team: Team) -> list[Match]:
        """Получить предстоящие матчи команды.

        Только матчи без счёта, у которых дата в будущем
        или статус scheduled.
        """
        all_matches = await self.get_team_matches(team)
        now = datetime.now()
        upcoming = [
            m for m in all_matches
            if m.home_score is None  # Нет счёта — значит не завершён
            and (m.match_date is None or m.match_date >= now)
            and m.status != "finished"
        ]
        return sorted(upcoming, key=lambda m: m.match_date or datetime.max)

    async def get_team_recent_results(self, team: Team) -> list[Match]:
        """Получить последние результаты команды.

        Только завершённые матчи — со счётом или статусом finished.
        """
        all_matches = await self.get_team_matches(team)
        results = [
            m for m in all_matches
            if m.is_finished or (m.home_score is not None and m.away_score is not None)
        ]
        return sorted(results, key=lambda m: m.match_date or datetime.min, reverse=True)

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
    # ЗАЯВКА И СТАТИСТИКА КОМАНДЫ
    # ========================================================================

    async def get_team_roster(self, team: Team) -> list["Player"]:
        """Получить заявку (состав) команды."""
        from app.models.football import Player

        cache_key = f"team_roster:{team.id}"
        cached = await cache.get(cache_key)
        if cached is not None:
            logger.debug("[service] Заявка команды '%s' из кеша", team.name)
            return cached

        try:
            roster = await self._parser.get_team_roster(team.url)
            await cache.set(cache_key, roster, ttl=6 * 3600)  # 6 часов
            logger.debug("[service] Заявка команды '%s' загружена: %d", team.name, len(roster))
            return roster
        except Exception as e:
            logger.error("[service] Ошибка получения заявки команды '%s': %s", team.name, e)
            return []

    async def get_team_player_stats(self, team: Team) -> list["PlayerStat"]:
        """Получить статистику игроков команды."""
        from app.models.football import PlayerStat

        cache_key = f"team_player_stats:{team.id}"
        cached = await cache.get(cache_key)
        if cached is not None:
            logger.debug("[service] Статистика игроков '%s' из кеша", team.name)
            return cached

        try:
            stats = await self._parser.get_team_player_stats(team.url)
            await cache.set(cache_key, stats, ttl=3 * 3600)  # 3 часа
            logger.debug("[service] Статистика игроков '%s' загружена: %d", team.name, len(stats))
            return stats
        except Exception as e:
            logger.error("[service] Ошибка получения статистики '%s': %s", team.name, e)
            return []

    # ========================================================================
    # ПРОГНОЗ НА МАТЧ
    # ========================================================================

    async def get_team_match_prediction(self, team: Team) -> Optional["MatchPrediction"]:
        """Получить прогноз на ближайший матч команды.

        Логика:
        1. Найти первый будущий матч команды.
        2. Определить соперника.
        3. Найти соперника: сначала в том же турнире, потом fallback.
        4. Получить последние результаты обеих команд.
        5. Посчитать метрики за последние 5 матчей.
        6. Найти личные встречи (head-to-head).
        7. Получить позиции в таблице.
        8. Сформировать текстовый прогноз.
        """
        from app.models.football import MatchPrediction

        # 1. Ближайший матч
        upcoming = await self.get_team_upcoming_matches(team)
        if not upcoming:
            logger.debug("[prediction] У команды '%s' нет предстоящих матчей", team.name)
            return None

        preview_upcoming = [m for m in upcoming if m.id.startswith("preview_")]
        next_match = preview_upcoming[0] if preview_upcoming else upcoming[0]
        opponent_name = (
            next_match.away_team
            if next_match.home_team.lower() == team.name.lower()
            else next_match.home_team
        )
        if not opponent_name or opponent_name == "—":
            logger.debug("[prediction] Соперник не определён")
            return None

        # 2. Найти соперника: сначала в том же турнире
        opponent: Optional[Team] = None
        if team.league_id:
            opponent = await self._find_team_in_league(opponent_name, team.league_id)
        if opponent is None:
            opponent = await self._find_team_by_name(opponent_name)

        # 3. Последние результаты
        team_results_raw = await self.get_team_recent_results(team)
        opponent_results_raw = await self.get_team_recent_results(opponent) if opponent else []
        team_results = self._select_reliable_results_for_prediction(team_results_raw)
        opponent_results = self._select_reliable_results_for_prediction(opponent_results_raw)

        # 4. Метрики формы (последние 5)
        team_metrics = self._calc_form_metrics(team_results[:5], team.name)
        opponent_metrics = self._calc_form_metrics(opponent_results[:5], opponent_name) if opponent_results else {
            "wins": 0, "draws": 0, "losses": 0,
            "avg_scored": 0.0, "avg_conceded": 0.0,
            "total_scored": 0, "total_conceded": 0,
            "matches": 0,
        }

        # 5. Личные встречи:
        # Сначала считаем по подтверждённым boxscore-матчам,
        # fallback на общий набор только если подтверждённых H2H нет.
        team_results_box = [m for m in team_results if m.id.startswith("boxscore_")]
        opponent_results_box = [m for m in opponent_results if m.id.startswith("boxscore_")]
        h2h = await self._get_head_to_head(team_results_box, opponent_results_box, team.name, opponent_name)
        if h2h["total"] == 0:
            h2h = await self._get_head_to_head(team_results, opponent_results, team.name, opponent_name)

        # 6. Позиции в таблице
        team_standing = await self.get_team_position_in_table(team)
        opponent_standing = None
        if opponent:
            opponent_standing = await self.get_team_position_in_table(opponent)

        # 7. Прогнозируемый счёт
        pred_home = round(max(0, team_metrics["avg_scored"] + opponent_metrics["avg_conceded"]) / 2)
        pred_away = round(max(0, opponent_metrics["avg_scored"] + team_metrics["avg_conceded"]) / 2)

        # 8. Оценка фаворита (форма + таблица + личные встречи + home advantage)
        team_power = (
            team_metrics["wins"] * 3
            + team_metrics["draws"]
            + team_metrics["avg_scored"]
        )
        opponent_power = (
            opponent_metrics["wins"] * 3
            + opponent_metrics["draws"]
            + opponent_metrics["avg_scored"]
        )

        # Home advantage
        is_home = next_match.home_team.lower() == team.name.lower()
        if is_home:
            team_power += 0.5  # домашнее преимущество
        else:
            opponent_power += 0.5

        # Корректировка по таблице
        if team_standing and opponent_standing:
            pos_diff = opponent_standing.position - team_standing.position
            if pos_diff > 3:
                team_power += 1.5
            elif pos_diff < -3:
                opponent_power += 1.5

        # Корректировка по личным встречам
        if h2h["total"] >= 2:
            if h2h["team_wins"] > h2h["opponent_wins"]:
                team_power += 0.5
            elif h2h["opponent_wins"] > h2h["team_wins"]:
                opponent_power += 0.5

        # Текст прогноза
        reasons: list[str] = []
        if team_metrics["wins"] >= 3:
            reasons.append(f"отличная форма {team.name} ({team_metrics['wins']} побед)")
        if opponent_metrics["losses"] >= 3:
            reasons.append(f"слабая форма {opponent_name} ({opponent_metrics['losses']} поражений)")
        if team_standing and opponent_standing:
            if team_standing.position < opponent_standing.position:
                reasons.append(
                    f"{team.name} выше в таблице ({team_standing.position} vs {opponent_standing.position})"
                )
        if h2h["total"] >= 2 and h2h["team_wins"] > h2h["opponent_wins"]:
            reasons.append(
                f"{team.name} доминирует в личных встречах ({h2h['team_wins']} из {h2h['total']})"
            )

        if team_power > opponent_power + 2:
            prediction_text = f"{team.name} — явный фаворит"
        elif team_power > opponent_power + 0.5:
            prediction_text = f"{team.name} выглядит фаворитом"
        elif opponent_power > team_power + 2:
            prediction_text = f"{opponent_name} — явный фаворит"
        elif opponent_power > team_power + 0.5:
            prediction_text = f"{opponent_name} выглядит фаворитом"
        else:
            prediction_text = "Команды примерно равны, вероятна ничья"

        if reasons:
            prediction_text += ". " + ", ".join(reasons[:2]).capitalize()

        # Home/away для прогноза
        home_team_name = next_match.home_team
        away_team_name = next_match.away_team

        if is_home:
            # team играет дома: team → home_*, opponent → away_*
            predicted_home = max(0, pred_home)
            predicted_away = max(0, pred_away)
            home_w = team_metrics["wins"]
            home_d = team_metrics["draws"]
            home_l = team_metrics["losses"]
            home_gs = round(team_metrics["avg_scored"], 1)
            home_gc = round(team_metrics["avg_conceded"], 1)
            away_w = opponent_metrics["wins"]
            away_d = opponent_metrics["draws"]
            away_l = opponent_metrics["losses"]
            away_gs = round(opponent_metrics["avg_scored"], 1)
            away_gc = round(opponent_metrics["avg_conceded"], 1)
            h2h_home_w = h2h["team_wins"]
            h2h_away_w = h2h["opponent_wins"]
            h2h_home_g = h2h["team_goals"]
            h2h_away_g = h2h["opponent_goals"]
            home_pos = team_standing.position if team_standing else 0
            away_pos = opponent_standing.position if opponent_standing else 0
        else:
            # team играет в гостях: opponent → home_*, team → away_*
            predicted_home = max(0, pred_away)
            predicted_away = max(0, pred_home)
            home_w = opponent_metrics["wins"]
            home_d = opponent_metrics["draws"]
            home_l = opponent_metrics["losses"]
            home_gs = round(opponent_metrics["avg_scored"], 1)
            home_gc = round(opponent_metrics["avg_conceded"], 1)
            away_w = team_metrics["wins"]
            away_d = team_metrics["draws"]
            away_l = team_metrics["losses"]
            away_gs = round(team_metrics["avg_scored"], 1)
            away_gc = round(team_metrics["avg_conceded"], 1)
            h2h_home_w = h2h["opponent_wins"]
            h2h_away_w = h2h["team_wins"]
            h2h_home_g = h2h["opponent_goals"]
            h2h_away_g = h2h["team_goals"]
            home_pos = opponent_standing.position if opponent_standing else 0
            away_pos = team_standing.position if team_standing else 0

        return MatchPrediction(
            home_team=home_team_name,
            away_team=away_team_name,
            match_date=next_match.match_date,
            home_wins=home_w,
            home_draws=home_d,
            home_losses=home_l,
            home_goals_scored=home_gs,
            home_goals_conceded=home_gc,
            away_wins=away_w,
            away_draws=away_d,
            away_losses=away_l,
            away_goals_scored=away_gs,
            away_goals_conceded=away_gc,
            h2h_total=h2h["total"],
            h2h_home_wins=h2h_home_w,
            h2h_draws=h2h["draws"],
            h2h_away_wins=h2h_away_w,
            h2h_home_goals=h2h_home_g,
            h2h_away_goals=h2h_away_g,
            home_position=home_pos,
            away_position=away_pos,
            predicted_home_score=predicted_home,
            predicted_away_score=predicted_away,
            prediction_text=prediction_text,
        )

    def _select_reliable_results_for_prediction(self, results: list[Match]) -> list[Match]:
        """Отобрать матчи для прогноза.

        Приоритет: подтверждённые boxscore-матчи.
        Если их мало, используем все завершённые результаты как fallback.
        """
        reliable = [m for m in results if m.id.startswith("boxscore_")]
        if len(reliable) >= 3:
            return reliable
        return results

    async def _find_team_in_league(self, name: str, league_id: str) -> Optional[Team]:
        """Найти команду внутри конкретной лиги (быстрый путь)."""
        if not name or name == "—":
            return None
        league = await self.get_league_by_id(league_id)
        if not league:
            return None
        try:
            teams = await self.get_league_teams(league)
            for t in teams:
                if t.name.lower() == name.lower():
                    return t
        except Exception:
            pass
        return None

    async def _find_team_by_name(self, name: str) -> Optional[Team]:
        """Найти команду по имени через все лиги (fallback)."""
        if not name or name == "—":
            return None

        leagues = await self.get_leagues()
        for league in leagues:
            try:
                teams = await self.get_league_teams(league)
                for t in teams:
                    if t.name.lower() == name.lower():
                        return t
            except Exception:
                continue
        return None

    async def _get_head_to_head(
        self,
        team_results: list,
        opponent_results: list,
        team_name: str,
        opponent_name: str,
    ) -> dict:
        """Найти личные встречи между командой и соперником.

        Собирает матчи из результатов ОБЕИХ команд, чтобы найти
        все очные встречи, даже если одна команда играла дома
        а другая — в гостях.

        Args:
            team_results: Результаты матчей команды A.
            opponent_results: Результаты матчей команды B.
            team_name: Имя команды A.
            opponent_name: Имя команды B.

        Returns:
            Словарь с статистикой личных встреч.
        """
        team_wins = 0
        draws = 0
        opponent_wins = 0
        team_goals_total = 0
        opponent_goals_total = 0
        total = 0
        seen_matches: set[str] = set()

        def _norm_name(name: str) -> str:
            return " ".join(name.strip().lower().split())

        for match in team_results + opponent_results:
            if match.home_score is None or match.away_score is None:
                continue

            # Проверяем что обе команды участвуют
            home_name = _norm_name(match.home_team)
            away_name = _norm_name(match.away_team)
            home_is_team = home_name == _norm_name(team_name)
            home_is_opp = home_name == _norm_name(opponent_name)
            away_is_team = away_name == _norm_name(team_name)
            away_is_opp = away_name == _norm_name(opponent_name)

            if not ((home_is_team or home_is_opp) and (away_is_team or away_is_opp)):
                continue

            # Уникальный ключ матча (чтобы не дублировать одну и ту же игру
            # из разных списков и с возможным переворотом home/away):
            # 1) стабильный id, если есть
            # 2) иначе неориентированная пара команд + дата
            date_key = match.match_date.isoformat() if match.match_date else "nodate"
            pair_key = "|".join(sorted([home_name, away_name]))
            match_key = match.id if getattr(match, "id", "") else f"{pair_key}_{date_key}"
            if match_key in seen_matches:
                continue
            seen_matches.add(match_key)

            total += 1

            # Определяем голы для каждой команды
            if home_is_team:
                team_goals = match.home_score
                opp_goals = match.away_score
            else:
                team_goals = match.away_score
                opp_goals = match.home_score

            team_goals_total += team_goals
            opponent_goals_total += opp_goals

            if team_goals > opp_goals:
                team_wins += 1
            elif team_goals == opp_goals:
                draws += 1
            else:
                opponent_wins += 1

        return {
            "total": total,
            "team_wins": team_wins,
            "draws": draws,
            "opponent_wins": opponent_wins,
            "team_goals": team_goals_total,
            "opponent_goals": opponent_goals_total,
        }

    def _calc_form_metrics(self, results: list, team_name: str) -> dict:
        """Посчитать метрики формы по последним матчам.

        Для каждого матча определяет, играла ли команда дома или в гостях,
        и считает забитые/пропущенные/результат относительно этой команды.

        Args:
            results: Список последних Match.
            team_name: Имя анализируемой команды.

        Returns:
            Словарь с метриками.
        """
        wins = 0
        draws = 0
        losses = 0
        total_scored = 0
        total_conceded = 0

        team_norm = " ".join(team_name.strip().lower().split())

        for m in results:
            if m.home_score is not None and m.away_score is not None:
                home_norm = " ".join(m.home_team.strip().lower().split())
                away_norm = " ".join(m.away_team.strip().lower().split())

                if home_norm != team_norm and away_norm != team_norm:
                    # Пропускаем матч, если команда в нём явно не участвует.
                    continue

                is_home = home_norm == team_norm

                if is_home:
                    scored = m.home_score
                    conceded = m.away_score
                else:
                    scored = m.away_score
                    conceded = m.home_score

                total_scored += scored
                total_conceded += conceded

                if scored > conceded:
                    wins += 1
                elif scored == conceded:
                    draws += 1
                else:
                    losses += 1

        matches = wins + draws + losses
        return {
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "avg_scored": round(total_scored / matches, 1) if matches > 0 else 0.0,
            "avg_conceded": round(total_conceded / matches, 1) if matches > 0 else 0.0,
            "total_scored": total_scored,
            "total_conceded": total_conceded,
            "matches": matches,
        }

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
