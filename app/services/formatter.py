"""Форматтер-сервис для красивого вывода данных.

Все методы принимают модели данных и возвращают строки,
готовые для отправки в Telegram.
"""

from __future__ import annotations

from typing import Optional

from app.models.football import League, Match, StandingRow, Team
from app.utils.dates import format_date_short, format_date_time, format_relative_date
from app.utils.text import (
    escape_html,
    pluralize_matches,
    pluralize_points,
    truncate,
)


class FootballFormatter:
    """Форматтер футбольных данных."""

    # ========================================================================
    # ЛИГИ
    # ========================================================================

    @staticmethod
    def format_leagues_list(leagues: list[League], title: str = "Доступные лиги и турниры") -> str:
        """Форматировать список лиг.

        Args:
            leagues: Список лиг.
            title: Заголовок сообщения.

        Returns:
            Текст для Telegram.
        """
        if not leagues:
            return "😔 К сожалению, не удалось загрузить список лиг.\n\nПопробуйте позже или проверьте доступность сайта."

        lines = [f"🏆 <b>{escape_html(title)}</b>\n"]

        for i, league in enumerate(leagues, 1):
            name = truncate(escape_html(league.name), 50)
            season = f" ({escape_html(league.season)})" if league.season else ""
            lines.append(f"{i}. {name}{season}")

        lines.append(f"\n📊 Всего: {len(leagues)} {pluralize_matches(len(leagues))}")
        return "\n".join(lines)

    @staticmethod
    def format_league_menu(league: League) -> str:
        """Форматировать меню лиги.

        Args:
            league: Объект лиги.

        Returns:
            Текст для Telegram.
        """
        name = escape_html(league.name)
        season_part = f"\n{escape_html(league.season)}" if league.season else ""
        return f"🏟 <b>{name}</b>{season_part}\n\nВыберите раздел:"

    # ========================================================================
    # КОМАНДЫ
    # ========================================================================

    @staticmethod
    def format_teams_list(teams: list[Team], league_name: str) -> str:
        """Форматировать список команд.

        Args:
            teams: Список команд.
            league_name: Название лиги.

        Returns:
            Текст для Telegram.
        """
        if not teams:
            return f"😔 Не удалось загрузить команды лиги <b>{escape_html(league_name)}</b>.\n\nВозможно, на сайте ещё нет данных для этого турнира."

        lines = [f"👥 <b>Команды: {escape_html(league_name)}</b>\n"]

        # Если команд много — показываем компактно
        if len(teams) > 20:
            for i, team in enumerate(teams, 1):
                name = truncate(escape_html(team.name), 40)
                lines.append(f"{i}. {name}")
        else:
            for i, team in enumerate(teams, 1):
                name = truncate(escape_html(team.name), 40)
                lines.append(f"{i}. {name}")

        lines.append(f"\n⚽ Всего: {len(teams)} {pluralize_matches(len(teams))}")
        return "\n".join(lines)

    @staticmethod
    def format_team_card(team: Team, standing: Optional[StandingRow] = None) -> str:
        """Форматировать карточку команды.

        Args:
            team: Объект команды.
            standing: Позиция в таблице (опционально).

        Returns:
            Текст для Telegram.
        """
        name = escape_html(team.name)
        lines = [f"⚽ <b>{name}</b>\n"]

        if standing:
            lines.append(
                f"📊 Позиция в таблице: <b>{standing.position}</b> место\n"
                f"   Игр: {standing.played} | В: {standing.wins} | Н: {standing.draws} | П: {standing.losses}\n"
                f"   Голы: {standing.goals_for}-{standing.goals_against} "
                f"({'+' if standing.goal_difference >= 0 else ''}{standing.goal_difference})\n"
                f"   Очки: <b>{standing.points}</b> {pluralize_points(standing.points)}"
            )

        return "\n".join(lines)

    # ========================================================================
    # МАТЧИ
    # ========================================================================

    @staticmethod
    def format_matches_list(
        matches: list[Match],
        title: str = "Матчи",
        max_count: int = 10,
    ) -> str:
        """Форматировать список матчей.

        Args:
            matches: Список матчей.
            title: Заголовок.
            max_count: Максимум матчей в списке.

        Returns:
            Текст для Telegram.
        """
        if not matches:
            return (
                f"📭 <b>{escape_html(title)}</b>\n\n"
                "Матчей пока нет или они ещё не опубликованы на сайте.\n"
                "Попробуйте проверить позже или выберите другую команду."
            )

        lines = [f"📅 <b>{escape_html(title)}</b>\n"]

        for i, match in enumerate(matches[:max_count], 1):
            home = escape_html(match.home_team)
            away = escape_html(match.away_team)
            league_tag = f" [{escape_html(match.league_name)}]" if match.league_name else ""

            if match.is_finished and match.home_score is not None:
                # 05.04 — Команда A — Команда B  2:1
                date_part = format_date_short(match.match_date)
                lines.append(
                    f"{i}. {date_part} — {home} — {away}{league_tag}  <b>{match.home_score}:{match.away_score}</b>"
                )
            elif match.is_live:
                # 🔴 LIVE — Команда A — Команда B  1:0
                score = f"{match.home_score}:{match.away_score}" if match.home_score is not None else "?:?"
                lines.append(
                    f"{i}. 🔴 LIVE — {home} — {away}{league_tag}  <b>{score}</b>"
                )
            elif match.status == "unknown":
                # Дата в прошлом, но нет счёта
                date_part = format_date_short(match.match_date)
                lines.append(f"{i}. {date_part} — {home} — {away}{league_tag}")
            else:
                # Будущий матч: 12.04 18:00 — Команда A — Команда B
                if match.match_date:
                    date_part = format_date_short(match.match_date)
                    time_part = match.match_date.strftime(" %H:%M")
                    lines.append(f"{i}. {date_part}{time_part} — {home} — {away}{league_tag}")
                else:
                    lines.append(f"{i}. {home} — {away}{league_tag}")

        if len(matches) > max_count:
            lines.append(f"\n... и ещё {len(matches) - max_count} {pluralize_matches(len(matches) - max_count)}")

        return "\n".join(lines)

    @staticmethod
    def format_match_detail(match: Match) -> str:
        """Форматировать детали одного матча.

        Args:
            match: Объект матча.

        Returns:
            Текст для Telegram.
        """
        lines = [f"🏟 <b>Матч</b>\n"]

        if match.league_name:
            lines.append(f"🏆 {escape_html(match.league_name)}")
            if match.round:
                lines.append(f"   Тур: {escape_html(match.round)}")

        date_str = format_date_time(match.match_date)
        lines.append(f"📅 {date_str}")

        if match.venue:
            lines.append(f"📍 {escape_html(match.venue)}")

        lines.append("")

        home = escape_html(match.home_team)
        away = escape_html(match.away_team)

        if match.is_finished and match.home_score is not None:
            lines.append(f"   <b>{home} {match.home_score}:{match.away_score} {away}</b>")
        elif match.is_live:
            score = f"{match.home_score}:{match.away_score}" if match.home_score is not None else "?:?"
            lines.append(f"   🔴 <b>{home} {score} {away}</b>")
        else:
            lines.append(f"   {home}  —  {away}")

        return "\n".join(lines)

    # ========================================================================
    # ТУРНИРНАЯ ТАБЛИЦА
    # ========================================================================

    @staticmethod
    def format_standings(standings: list[StandingRow], league_name: str) -> str:
        """Форматировать турнирную таблицу в читаемом виде для Telegram.

        Формат вывода (по две строки на команду):
            1. Динамо Барнаул — 9 очков
               И: 3  В: 3  Н: 0  П: 0  Голы: 21-6 (+15)

        Args:
            standings: Список строк таблицы.
            league_name: Название лиги.

        Returns:
            Текст для Telegram.
        """
        if not standings:
            return (
                f"📊 <b>{escape_html(league_name)}</b>\n\n"
                "😔 Не удалось загрузить турнирную таблицу."
            )

        name_escaped = escape_html(league_name)
        lines = [f"🏆 <b>Турнирная таблица: {name_escaped}</b>\n"]

        for row in standings:
            # Аккуратная обрезка длинных названий — 40 символов достаточно
            team = truncate(escape_html(row.team_name), 40)
            pts = row.points
            pt_word = pluralize_points(pts)

            # Первая строка: место, название, очки
            lines.append(f"{row.position}. {team} — <b>{pts}</b> {pt_word}")

            # Вторая строка: статистика (с отступом)
            gd = row.goal_difference
            gd_str = f" +{gd}" if gd > 0 else (f" {gd}" if gd < 0 else "")
            goals = f"{row.goals_for}-{row.goals_against}{gd_str}"

            stats = f"   И: {row.played}  В: {row.wins}  Н: {row.draws}  П: {row.losses}  Голы: {goals}"
            lines.append(stats)

            # Разделитель между командами (кроме последней)
            if row.position < len(standings):
                lines.append("")

        return "\n".join(lines)

    # ========================================================================
    # ПОИСК
    # ========================================================================

    @staticmethod
    def format_search_results(teams: list[Team], query: str) -> str:
        """Форматировать результаты поиска.

        Args:
            teams: Найденные команды.
            query: Поисковый запрос.

        Returns:
            Текст для Telegram.
        """
        if not teams:
            return f"🔍 Поиск: <b>{escape_html(query)}</b>\n\n😔 Команды не найдены. Попробуйте другой запрос."

        lines = [f"🔍 <b>Результаты поиска: {escape_html(query)}</b>\n"]

        for i, team in enumerate(teams, 1):
            name = truncate(escape_html(team.name), 40)
            league = f" ({escape_html(team.league_id)})" if team.league_id else ""
            lines.append(f"{i}. {name}{league}")

        if len(teams) == 1:
            lines.append("\nНайдена одна команда — открываю карточку...")

        lines.append(f"\n📊 Найдено: {len(teams)} {pluralize_matches(len(teams))}")
        return "\n".join(lines)

    # ========================================================================
    # ПОДПИСКИ
    # ========================================================================

    @staticmethod
    def format_subscriptions(subscriptions: list[dict]) -> str:
        """Форматировать список подписок.

        Args:
            subscriptions: Список подписок (словари с team_name, league_name).

        Returns:
            Текст для Telegram.
        """
        if not subscriptions:
            return (
                "📬 <b>Мои подписки</b>\n\n"
                "У вас пока нет подписок.\n"
                "Выберите команду и нажмите «Подписаться» чтобы получать уведомления."
            )

        lines = ["📬 <b>Мои подписки</b>\n"]

        for i, sub in enumerate(subscriptions, 1):
            team = escape_html(sub.get("team_name", "Неизвестно"))
            league = escape_html(sub.get("league_name", ""))
            league_str = f" — {league}" if league else ""
            lines.append(f"{i}. ⚽ {team}{league_str}")

        return "\n".join(lines)
