"""Тесты на реальных HTML fixtures с altaifootball.ru.

Fixtures хранатся в tests/fixtures/site_html/.
Для обновления: python -m tests.fixtures.save_site_html --force
"""

import pytest
from pathlib import Path
from bs4 import BeautifulSoup

from app.services.parser import SiteParser
from app.utils.text import clean_text

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "site_html"


def load_fixture(name: str) -> str:
    """Загрузить HTML fixture из tests/fixtures/site_html/."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


class TestTeamMatchParsing:
    """Тесты парсинга матчей на реальных страницах команд."""

    def test_ska_match_record(self) -> None:
        """СКА Сибирский ЗАТО: 1 победа, 0 ничьих, 3 поражения."""
        parser = SiteParser()
        html = load_fixture("team_5790.html")
        soup = BeautifulSoup(html, "lxml")
        team_name = '"СКА" ЗАТО Сибирский'

        matches = self._parse_team_matches(parser, soup, team_name, "/tournaments/2026/3607/teams/5790/")
        wins = sum(1 for m in matches if m.home_score > m.away_score)
        draws = sum(1 for m in matches if m.home_score == m.away_score)
        losses = sum(1 for m in matches if m.home_score < m.away_score)

        assert wins == 1
        assert draws == 0
        assert losses == 3

    def test_gm_sport_match_record(self) -> None:
        """GM SPORT 22 Барнаул: 3 победы, 0 ничьих, 1 поражение."""
        parser = SiteParser()
        html = load_fixture("team_6662.html")
        soup = BeautifulSoup(html, "lxml")
        team_name = '"GM SPORT 22" Барнаул'

        matches = self._parse_team_matches(parser, soup, team_name, "/tournaments/2026/3607/teams/6662/")
        wins = sum(1 for m in matches if m.home_score > m.away_score)
        draws = sum(1 for m in matches if m.home_score == m.away_score)
        losses = sum(1 for m in matches if m.home_score < m.away_score)

        assert wins == 3
        assert draws == 0
        assert losses == 1

    def test_ska_match_scores(self) -> None:
        """СКА: конкретные счёты матчей."""
        parser = SiteParser()
        html = load_fixture("team_5790.html")
        soup = BeautifulSoup(html, "lxml")
        team_name = '"СКА" ЗАТО Сибирский'

        matches = self._parse_team_matches(parser, soup, team_name, "/tournaments/2026/3607/teams/5790/")
        scores = [(m.home_score, m.away_score) for m in matches]

        # Счёт всегда от лица СКА: 3:7 (забил 3, пропустил 7)
        assert (3, 7) in scores  # vs ASM Group
        assert (8, 6) in scores  # vs АТИ (победа)

    def _parse_team_matches(self, parser: SiteParser, soup: BeautifulSoup, team_name: str, team_url: str) -> list:
        """Распарсить все матчи команды."""
        for table in soup.find_all("table", class_="table_box_row"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            header = " ".join(clean_text(c.get_text()).lower() for c in rows[0].find_all(["th", "td"]))
            if "дата" not in header or "соперник" not in header:
                continue
            matches = []
            for row in rows[1:]:
                m = parser._parse_team_match_row(row, team_name, team_url)
                if m and m.is_finished:
                    matches.append(m)
            return matches
        return []


class TestRosterParsing:
    """Тесты парсинга заявки на реальном HTML."""

    def test_roster_count(self) -> None:
        """GM SPORT 22: минимум 15 игроков."""
        parser = SiteParser()
        html = load_fixture("team_6662_roster.html")
        soup = BeautifulSoup(html, "lxml")
        players = parser._parse_roster_table(soup)
        assert len(players) >= 15

    def test_roster_positions(self) -> None:
        """Позиции игроков определяются."""
        parser = SiteParser()
        html = load_fixture("team_6662_roster.html")
        soup = BeautifulSoup(html, "lxml")
        players = parser._parse_roster_table(soup)

        positions = {p.position for p in players if p.position}
        assert "Вратари" in positions
        assert "Защитники" in positions

    def test_roster_first_player(self) -> None:
        """Первый игрок — вратарь с номером."""
        parser = SiteParser()
        html = load_fixture("team_6662_roster.html")
        soup = BeautifulSoup(html, "lxml")
        players = parser._parse_roster_table(soup)

        assert len(players) >= 1
        p = players[0]
        assert p.position == "Вратари"
        assert p.number == 22
        assert p.birth_date is not None

    def test_roster_ska(self) -> None:
        """СКА roster тоже парсится."""
        parser = SiteParser()
        html = load_fixture("team_5790_roster.html")
        soup = BeautifulSoup(html, "lxml")
        players = parser._parse_roster_table(soup)
        assert len(players) >= 10


class TestPlayerStatsParsing:
    """Тесты парсинга статистики на реальном HTML."""

    def test_stats_count(self) -> None:
        """GM SPORT 22: минимум 5 игроков со статистикой."""
        parser = SiteParser()
        html = load_fixture("team_6662_stats.html")
        soup = BeautifulSoup(html, "lxml")
        stats = parser._parse_player_stats_table(soup)
        assert len(stats) >= 5

    def test_stats_goals(self) -> None:
        """Голы игроков парсятся."""
        parser = SiteParser()
        html = load_fixture("team_6662_stats.html")
        soup = BeautifulSoup(html, "lxml")
        stats = parser._parse_player_stats_table(soup)

        total_goals = sum(s.goals for s in stats)
        assert total_goals > 0

    def test_stats_cards(self) -> None:
        """Карточки парсятся."""
        parser = SiteParser()
        html = load_fixture("team_6662_stats.html")
        soup = BeautifulSoup(html, "lxml")
        stats = parser._parse_player_stats_table(soup)

        # Хотя бы у одного игрока есть карточки
        total_yellow = sum(s.yellow_cards for s in stats)
        total_red = sum(s.red_cards for s in stats)
        assert total_yellow + total_red > 0
