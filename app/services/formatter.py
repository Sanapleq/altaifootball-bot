"""Форматтер-сервис для красивого вывода данных.

Все методы принимают модели данных и возвращают строки,
готовые для отправки в Telegram.

Единый стиль сообщений:
  📅 Заголовок
  Название команды/лиги

  1. Дата время
     Команда — Счёт — Соперник
"""

from __future__ import annotations

from datetime import datetime
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
    def format_leagues_list(
        leagues: list[League],
        title: str = "Доступные лиги и турниры",
    ) -> str:
        """Форматировать список лиг."""
        if not leagues:
            return (
                "😔 К сожалению, не удалось загрузить список лиг.\n\n"
                "Попробуйте позже или проверьте доступность сайта."
            )

        lines = [f"🏆 <b>{escape_html(title)}</b>\n"]

        for i, league in enumerate(leagues, 1):
            name = truncate(escape_html(league.name), 50)
            season = f" ({escape_html(league.season)})" if league.season else ""
            lines.append(f"{i}. {name}{season}")

        lines.append(f"\n📊 Всего: {len(leagues)} {pluralize_matches(len(leagues))}")
        return "\n".join(lines)

    @staticmethod
    def format_league_menu(league: League) -> str:
        """Форматировать меню лиги."""
        name = escape_html(league.name)
        season_part = f"\n{escape_html(league.season)}" if league.season else ""
        return f"🏟 <b>{name}</b>{season_part}\n\nВыберите раздел:"

    # ========================================================================
    # КОМАНДЫ
    # ========================================================================

    @staticmethod
    def format_teams_list(teams: list[Team], league_name: str) -> str:
        """Форматировать список команд."""
        if not teams:
            return (
                f"😔 Не удалось загрузить команды лиги "
                f"<b>{escape_html(league_name)}</b>.\n\n"
                "Возможно, на сайте ещё нет данных для этого турнира."
            )

        lines = [f"👥 <b>Команды: {escape_html(league_name)}</b>\n"]

        for i, team in enumerate(teams, 1):
            name = truncate(escape_html(team.name), 45)
            lines.append(f"{i}. {name}")

        lines.append(f"\n⚽ Всего: {len(teams)} {pluralize_matches(len(teams))}")
        return "\n".join(lines)

    @staticmethod
    def format_team_card(
        team: Team,
        standing: Optional[StandingRow] = None,
        league_name: Optional[str] = None,
    ) -> str:
        """Форматировать карточку команды.

        Пример:
          ⚽ GM SPORT 22 Барнаул

          🏆 Лига: Десятая лига
          📍 Позиция: 2 место
          🎯 Очки: 10
          🥅 Мячи: 8-3
        """
        name = escape_html(team.name)
        lines = [f"⚽ <b>{name}</b>"]

        parts: list[str] = []

        if league_name:
            parts.append(f"🏆 <b>Лига:</b> {escape_html(league_name)}")

        if standing:
            pos = standing.position
            parts.append(f"📍 <b>Позиция:</b> {pos} {FootballFormatter._position_word(pos)}")
            parts.append(f"🎯 <b>Очки:</b> {standing.points}")
            parts.append(f"🥅 <b>Мячи:</b> {standing.goals_for}-{standing.goals_against}")

        if parts:
            lines.append("")
            lines.extend(parts)

        lines.append("\n📋 Выберите действие:")
        return "\n".join(lines)

    @staticmethod
    def _position_word(pos: int) -> str:
        """Склонение слова «место»."""
        abs_pos = pos % 100
        last = abs_pos % 10
        if 11 <= abs_pos <= 14:
            return "мест"
        if last == 1:
            return "место"
        if 2 <= last <= 4:
            return "места"
        return "мест"

    # ========================================================================
    # МАТЧИ
    # ========================================================================

    @staticmethod
    def format_matches_list(
        matches: list[Match],
        title: str = "Матчи",
        team_name: Optional[str] = None,
        max_count: int = 15,
        show_sections: bool = True,
    ) -> str:
        """Форматировать список матчей.

        Для ближайших матчей (show_sections=False):
          📅 Ближайшие матчи
          GM SPORT 22 Барнаул

          1. 11.04.2026 16:00
             GM SPORT 22 Барнаул — СКА Сибирский ЗАТО

        Для результатов (show_sections=False):
          🔥 Последние результаты
          GM SPORT 22 Барнаул

          1. 15.03.2026 16:00
             ✅ GM SPORT 22 Барнаул 2:1 АТТ фермер Алейск

        Для расписания (show_sections=True):
          🗓 Расписание
          GM SPORT 22 Барнаул

          🔴 Прошедшие
          1. 15.03.2026 16:00
             GM SPORT 22 Барнаул 2:1 АТТ фермер Алейск

          🟢 Предстоящие
          2. 11.04.2026 16:00
             GM SPORT 22 Барнаул — СКА Сибирский ЗАТО
        """
        if not matches:
            label = escape_html(title)
            return (
                f"📭 <b>{label}</b>\n\n"
                "Матчей пока нет или они ещё не опубликованы на сайте.\n"
                "Попробуйте проверить позже или выберите другую команду."
            )

        lines: list[str] = [f"📅 <b>{escape_html(title)}</b>"]

        if team_name:
            lines.append(escape_html(team_name))

        lines.append("")

        if not show_sections:
            # Плоский список — для ближайших и результатов
            for i, match in enumerate(matches[:max_count], 1):
                lines.append(FootballFormatter._format_match_card(match, index=i))
            if len(matches) > max_count:
                lines.append(f"\n… и ещё {len(matches) - max_count} {pluralize_matches(len(matches) - max_count)}")
            return "\n".join(lines)

        # С секциями: для расписания
        finished = [m for m in matches if m.is_finished and m.home_score is not None]
        upcoming = [
            m for m in matches
            if not m.is_finished and (m.match_date is None or m.match_date >= datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
        ]

        total_shown = 0
        idx = 1

        if finished:
            lines.append("🔴 <b>Прошедшие</b>")
            lines.append("")
            for match in finished[:max_count]:
                lines.append(FootballFormatter._format_match_card(match, index=idx))
                idx += 1
                total_shown += 1
            lines.append("")

        if upcoming and total_shown < max_count:
            remaining = max_count - total_shown
            lines.append("🟢 <b>Предстоящие</b>")
            lines.append("")
            for match in upcoming[:remaining]:
                lines.append(FootballFormatter._format_match_card(match, index=idx))
                idx += 1
                total_shown += 1

        if total_shown == 0:
            for match in matches[:max_count]:
                lines.append(FootballFormatter._format_match_card(match, index=idx))
                idx += 1
                total_shown += 1

        if len(matches) > max_count:
            lines.append(f"\n… и ещё {len(matches) - max_count} {pluralize_matches(len(matches) - max_count)}")

        return "\n".join(lines)

    @staticmethod
    def _format_match_card(match: Match, index: Optional[int] = None) -> str:
        """Оформить один матч как мини-карточку.

        Формат:
          1. 11.04.2026 16:00
             GM SPORT 22 Барнаул — Соперник

        или для результатов:
          1. 15.03.2026 16:00
             ✅ GM SPORT 22 Барнаул 2:1 АТТ фермер Алейск
        """
        # Номер
        num = f"{index}. " if index else ""

        # Дата и время
        if match.match_date:
            date_part = format_date_short(match.match_date)
            time_part = match.match_date.strftime(" %H:%M") if match.match_date.hour or match.match_date.minute else ""
            datetime_line = f"{num}{date_part}{time_part}"
        else:
            datetime_line = f"{num}— —"

        home = escape_html(match.home_team)
        away = escape_html(match.away_team)

        if match.is_finished and match.home_score is not None:
            # Результат: с маркером результата
            marker = FootballFormatter._result_marker(match)
            score = f"<b>{match.home_score}:{match.away_score}</b>"
            match_line = f"   {marker} {home} {score} {away}"
        elif match.is_live:
            score = f"<b>{match.home_score}:{match.away_score}</b>" if match.home_score is not None else "<b>?:?</b>"
            match_line = f"   🔴 <b>LIVE</b> — {home} {score} {away}"
        elif match.status == "unknown":
            match_line = f"   {home} — {away}"
        else:
            # Предстоящий
            match_line = f"   {home} — {away}"

        return f"{datetime_line}\n{match_line}"

    @staticmethod
    def _result_marker(match: Match) -> str:
        """Вернуть эмодзи-маркер результата для текущей команды.

        Определяем по первой команде в home_team.
        """
        if match.home_score is None or match.away_score is None:
            return ""

        if match.home_score > match.away_score:
            return "✅"
        elif match.home_score < match.away_score:
            return "❌"
        else:
            return "🤝"

    # ========================================================================
    # ТУРНИРНАЯ ТАБЛИЦА
    # ========================================================================

    @staticmethod
    def format_standings(
        standings: list[StandingRow],
        league_name: str,
        highlight_team: Optional[str] = None,
    ) -> str:
        """Форматировать турнирную таблицу.

        Пример:
          📊 Турнирная таблица
          Десятая лига

          1. Команда А — 12 очков
          2. GM SPORT 22 Барнаул — 10 очков
          3. Команда В — 9 очков

          🏷 GM SPORT 22 Барнаул: 2 место
          ⚽ Игры: 4 | Победы: 3 | Ничьи: 1 | Поражения: 0
          🥅 Мячи: 8-3
        """
        if not standings:
            return (
                f"📊 <b>{escape_html(league_name)}</b>\n\n"
                "😔 Не удалось загрузить турнирную таблицу."
            )

        lines = [f"📊 <b>Турнирная таблица</b>", escape_html(league_name), ""]

        highlight_row: Optional[StandingRow] = None

        for row in standings:
            team = truncate(escape_html(row.team_name), 40)
            pts = row.points
            pt_word = pluralize_points(pts)

            # Выделяем подсвеченную команду
            if highlight_team and row.team_name.lower() == highlight_team.lower():
                lines.append(f"<b>{row.position}. {team} — {pts} {pt_word}</b>")
                highlight_row = row
            else:
                lines.append(f"{row.position}. {team} — <b>{pts}</b> {pt_word}")

        # Детали подсвеченной команды
        if highlight_row:
            pos = highlight_row.position
            pos_word = FootballFormatter._position_word(pos)
            lines.append("")
            lines.append(f"🏷 <b>{escape_html(highlight_row.team_name)}</b>: {pos} {pos_word}")
            lines.append(
                f"⚽ Игры: {highlight_row.played} | Победы: {highlight_row.wins} | "
                f"Ничьи: {highlight_row.draws} | Поражения: {highlight_row.losses}"
            )
            gd = highlight_row.goal_difference
            gd_str = f"+{gd}" if gd > 0 else str(gd) if gd < 0 else "0"
            lines.append(f"🥅 Мячи: {highlight_row.goals_for}-{highlight_row.goals_against} ({gd_str})")

        return "\n".join(lines)

    # ========================================================================
    # ПОИСК
    # ========================================================================

    @staticmethod
    def format_search_results(teams: list[Team], query: str) -> str:
        """Форматировать результаты поиска."""
        if not teams:
            return (
                f"🔍 Поиск: <b>{escape_html(query)}</b>\n\n"
                "😔 Команды не найдены. Попробуйте другой запрос."
            )

        lines = [f"🔍 <b>Результаты поиска: {escape_html(query)}</b>\n"]

        for i, team in enumerate(teams, 1):
            name = truncate(escape_html(team.name), 45)
            lines.append(f"{i}. {name}")

        if len(teams) == 1:
            lines.append("\nНайдена одна команда — открываю карточку...")

        lines.append(f"\n📊 Найдено: {len(teams)} {pluralize_matches(len(teams))}")
        return "\n".join(lines)

    # ========================================================================
    # ПОДПИСКИ
    # ========================================================================

    @staticmethod
    def format_subscriptions(subscriptions: list[dict]) -> str:
        """Форматировать список подписок."""
        if not subscriptions:
            return (
                "📬 <b>Мои подписки</b>\n\n"
                "У вас пока нет подписок.\n"
                "Выберите команду через «Лиги» и нажмите «Подписаться»."
            )

        lines = ["📬 <b>Мои подписки</b>\n"]

        for i, sub in enumerate(subscriptions, 1):
            team = escape_html(sub.get("team_name", "Неизвестно"))
            league = escape_html(sub.get("league_name", ""))
            league_str = f" — {league}" if league else ""
            lines.append(f"{i}. ⚽ {team}{league_str}")

        return "\n".join(lines)
