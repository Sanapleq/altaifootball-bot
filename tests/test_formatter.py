"""Тесты formatter-сервиса."""

import pytest

from app.models.football import League, Match, StandingRow, Team
from app.services.formatter import FootballFormatter


class TestFootballFormatter:
    """Тесты форматтера футбольных данных."""

    def test_format_leagues_list_empty(self) -> None:
        """Пустой список лиг."""
        result = FootballFormatter.format_leagues_list([])
        assert "не удалось" in result.lower() or "😔" in result

    def test_format_leagues_list(self) -> None:
        """Форматирование списка лиг."""
        leagues = [
            League(id="1", name="Премьер-Лига", url="http://example.com/league/1"),
            League(id="2", name="Кубок", url="http://example.com/league/2"),
        ]
        result = FootballFormatter.format_leagues_list(leagues)
        assert "Премьер-Лига" in result
        assert "Кубок" in result
        assert "2" in result

    def test_format_teams_list_empty(self) -> None:
        """Пустой список команд."""
        result = FootballFormatter.format_teams_list([], "Тестовая лига")
        assert "не удалось" in result.lower() or "😔" in result

    def test_format_teams_list(self) -> None:
        """Форматирование списка команд."""
        teams = [
            Team(id="1", name="Команда А", url="http://example.com/team/1"),
            Team(id="2", name="Команда Б", url="http://example.com/team/2"),
        ]
        result = FootballFormatter.format_teams_list(teams, "Тестовая лига")
        assert "Команда А" in result
        assert "Команда Б" in result

    def test_format_team_card(self) -> None:
        """Форматирование карточки команды."""
        team = Team(id="1", name="Тестовая команда", url="http://example.com/team/1")
        standing = StandingRow(
            position=3,
            team_name="Тестовая команда",
            played=10,
            wins=7,
            draws=1,
            losses=2,
            goals_for=20,
            goals_against=8,
            points=22,
        )
        result = FootballFormatter.format_team_card(team, standing)
        assert "Тестовая команда" in result
        assert "3" in result
        assert "22" in result

    def test_format_matches_list_empty(self) -> None:
        """Пустой список матчей."""
        result = FootballFormatter.format_matches_list([], "Тестовые матчи")
        assert "нет" in result.lower() or "😔" in result or "Матчей" in result

    def test_format_matches_list_finished(self) -> None:
        """Форматирование завершённого матча."""
        from datetime import datetime
        matches = [
            Match(
                id="1",
                home_team="Команда А",
                away_team="Команда Б",
                home_score=2,
                away_score=1,
                status="finished",
                match_date=datetime(2026, 4, 5, 18, 0),
            )
        ]
        result = FootballFormatter.format_matches_list(matches, "Результаты")
        assert "Команда А" in result
        assert "Команда Б" in result
        assert "2:1" in result

    def test_format_matches_list_scheduled(self) -> None:
        """Форматирование предстоящего матча."""
        from datetime import datetime, timedelta
        future_date = datetime.now() + timedelta(days=7)
        matches = [
            Match(
                id="1",
                home_team="Команда В",
                away_team="Команда Г",
                status="scheduled",
                match_date=future_date,
            )
        ]
        result = FootballFormatter.format_matches_list(matches, "Расписание")
        assert "Команда В" in result
        assert "Команда Г" in result

    def test_format_standings_empty(self) -> None:
        """Пустая турнирная таблица."""
        result = FootballFormatter.format_standings([], "Тестовая лига")
        assert "не удалось" in result.lower() or "😔" in result

    def test_format_standings(self) -> None:
        """Форматирование турнирной таблицы."""
        standings = [
            StandingRow(
                position=1,
                team_name="Лидер",
                played=10,
                wins=9,
                draws=1,
                losses=0,
                goals_for=25,
                goals_against=5,
                points=28,
            ),
            StandingRow(
                position=2,
                team_name="Преследователь",
                played=10,
                wins=7,
                draws=2,
                losses=1,
                goals_for=18,
                goals_against=8,
                points=23,
            ),
        ]
        result = FootballFormatter.format_standings(standings, "Тестовая лига")
        assert "Тестовая лига" in result
        assert "Лидер" in result
        assert "Преследователь" in result
        assert "28" in result

    def test_format_search_results_empty(self) -> None:
        """Пустые результаты поиска."""
        result = FootballFormatter.format_search_results([], "Запрос")
        assert "не найдены" in result.lower() or "😔" in result

    def test_format_search_results(self) -> None:
        """Результаты поиска."""
        teams = [
            Team(id="1", name="Алтай", url="http://example.com/team/1"),
            Team(id="2", name="Альтаир", url="http://example.com/team/2"),
        ]
        result = FootballFormatter.format_search_results(teams, "Алт")
        assert "Алтай" in result
        assert "Альтаир" in result

    def test_format_subscriptions_empty(self) -> None:
        """Пустые подписки."""
        result = FootballFormatter.format_subscriptions([])
        assert "нет подписок" in result.lower() or "📬" in result

    def test_format_subscriptions(self) -> None:
        """Форматирование подписок."""
        subs = [
            {"team_name": "Команда А", "league_name": "Лига 1"},
            {"team_name": "Команда Б", "league_name": "Лига 2"},
        ]
        result = FootballFormatter.format_subscriptions(subs)
        assert "Команда А" in result
        assert "Команда Б" in result
