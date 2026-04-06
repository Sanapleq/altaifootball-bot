"""Тесты моделей данных."""

import pytest
from datetime import datetime

from app.models.football import League, Match, StandingRow, Team


class TestLeague:
    """Тесты модели League."""

    def test_create_league(self) -> None:
        """Создание лиги."""
        league = League(id="1", name="Премьер-Лига", url="http://example.com/1")
        assert league.id == "1"
        assert league.name == "Премьер-Лига"
        assert league.season is None

    def test_league_with_season(self) -> None:
        """Лига с сезоном."""
        league = League(id="1", name="Премьер-Лига", url="http://example.com/1", season="2025/2026")
        assert league.season == "2025/2026"

    def test_league_equality(self) -> None:
        """Сравнение лиг по ID."""
        l1 = League(id="1", name="Лига А", url="http://a.com")
        l2 = League(id="1", name="Лига Б", url="http://b.com")
        assert l1 == l2  # Same ID

    def test_league_hash(self) -> None:
        """Хеширование по ID."""
        l1 = League(id="1", name="Лига А", url="http://a.com")
        l2 = League(id="1", name="Лига Б", url="http://b.com")
        assert hash(l1) == hash(l2)


class TestTeam:
    """Тесты модели Team."""

    def test_create_team(self) -> None:
        """Создание команды."""
        team = Team(id="1", name="Алтай", url="http://example.com/team/1")
        assert team.id == "1"
        assert team.name == "Алтай"
        assert team.league_id is None

    def test_team_with_league(self) -> None:
        """Команда с лигой."""
        team = Team(id="1", name="Алтай", url="http://example.com/team/1", league_id="10")
        assert team.league_id == "10"


class TestMatch:
    """Тесты модели Match."""

    def test_create_match_finished(self) -> None:
        """Завершённый матч."""
        match = Match(
            id="1",
            home_team="Команда А",
            away_team="Команда Б",
            home_score=2,
            away_score=1,
            status="finished",
        )
        assert match.is_finished
        assert not match.is_live
        assert match.score_display == "2:1"

    def test_create_match_scheduled(self) -> None:
        """Предстоящий матч."""
        match = Match(
            id="1",
            home_team="Команда А",
            away_team="Команда Б",
            status="scheduled",
        )
        assert not match.is_finished
        assert not match.is_live
        assert match.score_display == "vs"

    def test_create_match_live(self) -> None:
        """Матч в прямом эфире."""
        match = Match(
            id="1",
            home_team="Команда А",
            away_team="Команда Б",
            home_score=1,
            away_score=0,
            status="LIVE",
        )
        assert match.is_live
        assert match.score_display == "1:0"

    def test_match_with_date(self) -> None:
        """Матч с датой."""
        dt = datetime(2026, 4, 12, 18, 0)
        match = Match(
            id="1",
            home_team="Команда А",
            away_team="Команда Б",
            match_date=dt,
            status="scheduled",
        )
        assert match.match_date == dt


class TestStandingRow:
    """Тесты модели StandingRow."""

    def test_create_standing_row(self) -> None:
        """Создание строки таблицы."""
        row = StandingRow(
            position=1,
            team_name="Лидер",
            played=10,
            wins=8,
            draws=1,
            losses=1,
            goals_for=20,
            goals_against=5,
            points=25,
        )
        assert row.position == 1
        assert row.goal_difference == 15

    def test_goal_difference_negative(self) -> None:
        """Отрицательная разница голов."""
        row = StandingRow(
            position=10,
            team_name="Аутсайдер",
            goals_for=5,
            goals_against=15,
        )
        assert row.goal_difference == -10

    def test_default_values(self) -> None:
        """Значения по умолчанию."""
        row = StandingRow(position=1, team_name="Тест")
        assert row.played == 0
        assert row.wins == 0
        assert row.points == 0
        assert row.goal_difference == 0
