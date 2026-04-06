"""Конфигурация CSS-селекторов для парсинга сайта altaifootball.ru.

Все селекторы вынесены сюда для удобства адаптации при изменении структуры сайта.
Если сайт меняет HTML — достаточно поправить значения в этом файле.
"""

from __future__ import annotations
from typing import Optional


class SelectorsConfig:
    """CSS-селекторы и XPath для парсинга сайта."""

    # ===== Лиги =====
    # Контейнер списка лиг на главной / странице турниров
    leagues_container: str = "div.content"
    # Ссылка на лигу (элемент списка)
    league_link: str = "a"
    # Контейнер с лигами (может быть список/таблица)
    leagues_list: str = "ul.leagues-list, div.tournaments-list, table.tournament-table"
    # Название лиги
    league_name: str = "a, span.name, td.name"

    # ===== Команды =====
    # Контейнер списка команд
    teams_container: str = "div.teams-list, table.teams-table, div.club-list"
    # Строка команды
    team_row: str = "tr, div.team-item, a.team-link"
    # Ссылка на команду
    team_link: str = "a"
    # Название команды
    team_name: str = "a, td.name, span.team-name"

    # ===== Турнирная таблица =====
    # Контейнер таблицы
    standings_container: str = "table.standings, table.table, div.standings"
    # Строка таблицы
    standings_row: str = "tbody tr, tr"
    # Ячейки: позиция, команда, игры, победы, ничьи, поражения, голы, очки
    standings_position: str = "td:nth-child(1)"
    standings_team: str = "td:nth-child(2) a, td:nth-child(2)"
    standings_played: str = "td:nth-child(3)"
    standings_wins: str = "td:nth-child(4)"
    standings_draws: str = "td:nth-child(5)"
    standings_losses: str = "td:nth-child(6)"
    standings_goals_for: str = "td:nth-child(7)"
    standings_goals_against: str = "td:nth-child(8)"
    standings_points: str = "td:nth-child(9), td:last-child"

    # ===== Матчи =====
    # Контейнер матчей
    matches_container: str = "div.matches-list, table.matches-table, div.fixtures"
    # Строка матча
    match_row: str = "tr, div.match-item, div.match-card"
    # Дата матча
    match_date: str = "td.date, td.match-date, span.date, time"
    # Домашняя команда
    match_home: str = "td.home-team a, td:nth-child(2) a, span.home-team"
    # Гостевая команда
    match_away: str = "td.away-team a, td:nth-child(4) a, span.away-team"
    # Счёт
    match_score: str = "td.score, td.match-score, span.score"
    # Ссылка на матч
    match_link: str = "a"

    # ===== Поиск =====
    # Результат поиска
    search_results: str = "div.search-results, div.results, table.search-table"
    search_result_item: str = "a, div.result-item"

    # ===== Общие =====
    # Заголовок страницы
    page_title: str = "h1, h1.title, div.page-title"
    # Пагинация
    pagination: str = "div.pagination, ul.pagination, nav.pagination"
    pagination_next: str = "a.next, a:contains('Следующая')"


# Альтернативные селекторы (fallback)
# Если основные не сработали — пробуем эти
FALLBACK_SELECTORS: dict[str, dict[str, str]] = {
    "leagues": {
        "container": "div.content, div.main, #content",
        "link": "a[href*='league'], a[href*='tournament'], a[href*='season']",
    },
    "teams": {
        "container": "div.content, #content, div.main",
        "link": "a[href*='team'], a[href*='club']",
    },
    "matches": {
        "container": "div.content, #content, table",
        "row": "tr, div.match",
        "date": "td:first-child, time",
        "home": "td a, a.team",
        "away": "td a, a.team",
        "score": "td.score, td:nth-child(3)",
    },
    "standings": {
        "container": "table.standings, table.table",
        "row": "tr",
    },
}
