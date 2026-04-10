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

    def test_libertas_match_record(self) -> None:
        """Libertas NEO STAR's: 2 победы, 0 ничьих, 1 поражение."""
        parser = SiteParser()
        html = load_fixture("team_6734.html")
        soup = BeautifulSoup(html, "lxml")
        team_name = "Libertas NEO STAR's Барнаул"

        matches = self._parse_team_matches(parser, soup, team_name, "/tournaments/2026/3607/teams/6734/")
        wins = sum(1 for m in matches if m.home_score > m.away_score)
        draws = sum(1 for m in matches if m.home_score == m.away_score)
        losses = sum(1 for m in matches if m.home_score < m.away_score)

        assert wins == 2
        assert draws == 0
        assert losses == 1

    def test_att_farmer_match_record(self) -> None:
        """АТТ фермер: 2 победы, 0 ничьих, 1 поражение."""
        parser = SiteParser()
        html = load_fixture("team_5628.html")
        soup = BeautifulSoup(html, "lxml")
        team_name = "АТТ фермер Алейск"

        matches = self._parse_team_matches(parser, soup, team_name, "/tournaments/2026/3607/teams/5628/")
        wins = sum(1 for m in matches if m.home_score > m.away_score)
        draws = sum(1 for m in matches if m.home_score == m.away_score)
        losses = sum(1 for m in matches if m.home_score < m.away_score)

        assert wins == 2
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


class TestBoxscoreParsing:
    """Тесты парсинга boxscore — источник истины для сыгранного матча."""

    def test_boxscore_teams_and_score(self) -> None:
        """Boxscore: GM SPORT 22 vs АТТ фермер (2:1)."""
        parser = SiteParser()
        html = load_fixture("boxscore_140352.html")
        soup = BeautifulSoup(html, "lxml")
        match = parser._parse_boxscore(soup, "/tournaments/boxscore/140352/")

        assert match is not None
        assert "GM SPORT 22" in match.home_team
        assert "АТТ фермер" in match.away_team
        assert match.home_score == 2
        assert match.away_score == 1
        assert match.is_finished
        assert match.status == "finished"

    def test_boxscore_second_match(self) -> None:
        """Boxscore: Товарка 22 vs GM SPORT 22 (7:3)."""
        parser = SiteParser()
        html = load_fixture("boxscore_140597.html")
        soup = BeautifulSoup(html, "lxml")
        match = parser._parse_boxscore(soup, "/tournaments/boxscore/140597/")

        assert match is not None
        # Товарка 22 — home, GM SPORT 22 — away (по boxscore)
        assert "Товарка 22" in match.home_team
        assert "GM SPORT 22" in match.away_team
        assert match.home_score == 7
        assert match.away_score == 3


class TestPreviewParsing:
    """Тесты парсинга preview — источник истины для будущего матча."""

    def test_preview_teams(self) -> None:
        """Preview: СКА vs GM SPORT 22."""
        parser = SiteParser()
        html = load_fixture("preview_140750.html")
        soup = BeautifulSoup(html, "lxml")
        match = parser._parse_preview(soup, "/tournaments/boxscore/140750/preview/")

        assert match is not None
        assert "СКА" in match.home_team
        assert "GM SPORT 22" in match.away_team
        assert match.status == "scheduled"
        assert match.match_date is not None


class TestMatchCandidates:
    """Тесты кандидатов матчей со страницы команды."""

    def test_gm_sport_candidates(self) -> None:
        """GM SPORT 22: минимум 4 сыгранных + 2 будущих."""
        parser = SiteParser()
        html = load_fixture("team_6662.html")
        soup = BeautifulSoup(html, "lxml")

        candidates = []
        for table in soup.find_all("table", class_="table_box_row"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            header = " ".join(clean_text(c.get_text()).lower() for c in rows[0].find_all(["th", "td"]))
            if "дата" not in header:
                continue
            team_name = parser._extract_current_team_name(soup)
            for row in rows[1:]:
                c = parser._parse_candidate_row(row, team_name)
                if c:
                    candidates.append(c)
            break

        assert len(candidates) >= 5
        # Есть boxscore ссылки
        boxscore = [c for c in candidates if "/boxscore/" in c.match_url and "/preview/" not in c.match_url]
        assert len(boxscore) >= 4


class TestLeagueStandingsConsistency:
    """Сверка формы команд с таблицей лиги 3607."""

    def test_team_records_match_league_standings(self) -> None:
        parser = SiteParser()
        league_html = load_fixture("league_3607.html")
        league_soup = BeautifulSoup(league_html, "lxml")

        # Парсим standings через существующую таблицу-парсер
        table = league_soup.find("table", class_="table_box_row")
        assert table is not None
        rows = parser._parse_standings_table_box(table)
        by_team = {r.team_name: r for r in rows}

        expectations = {
            "team_6662.html": ("GM SPORT 22 Барнаул", 3, 0, 1),
            "team_5790.html": ("СКА Сибирский ЗАТО", 1, 0, 3),
            "team_6659.html": ("Товарка 22 Барнаул", 3, 0, 0),
            "team_6734.html": ("Libertas NEO STAR's Барнаул", 2, 0, 1),
            "team_5628.html": ("АТТ фермер Алейск", 2, 0, 1),
            "team_6377.html": ("ASM Group Барнаул", 1, 0, 2),
            "team_6281.html": ("Барнаульский завод АТИ Барнаул", 0, 0, 4),
        }

        for fixture_name, (team_name, exp_w, exp_d, exp_l) in expectations.items():
            team_html = load_fixture(fixture_name)
            soup = BeautifulSoup(team_html, "lxml")
            matches = TestTeamMatchParsing()._parse_team_matches(parser, soup, team_name, "/tournaments/2026/3607/teams/0/")
            wins = sum(1 for m in matches if m.home_score > m.away_score)
            draws = sum(1 for m in matches if m.home_score == m.away_score)
            losses = sum(1 for m in matches if m.home_score < m.away_score)

            assert (wins, draws, losses) == (exp_w, exp_d, exp_l)
            assert team_name in by_team
            row = by_team[team_name]
            assert (row.wins, row.draws, row.losses) == (exp_w, exp_d, exp_l)


class TestScheduleCandidates:
    """Проверка кандидатов расписания на реальных страницах команды."""

    def test_gm_sport_candidates_have_finished_and_upcoming(self) -> None:
        parser = SiteParser()
        html = load_fixture("team_6662.html")
        soup = BeautifulSoup(html, "lxml")
        team_name = parser._extract_current_team_name(soup)

        candidates = []
        for table in soup.find_all("table", class_="table_box_row"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            header = " ".join(clean_text(c.get_text()).lower() for c in rows[0].find_all(["th", "td"]))
            if "дата" not in header or "соперник" not in header:
                continue
            for row in rows[1:]:
                c = parser._parse_candidate_row(row, team_name)
                if c:
                    candidates.append(c)
            break

        assert candidates
        finished = [c for c in candidates if c.match_url and "/boxscore/" in c.match_url and "/preview/" not in c.match_url]
        upcoming = [c for c in candidates if c.match_url and "/preview/" in c.match_url]
        assert len(finished) >= 4
        assert len(upcoming) >= 1

    def test_ska_candidates_have_finished_and_upcoming(self) -> None:
        parser = SiteParser()
        html = load_fixture("team_5790.html")
        soup = BeautifulSoup(html, "lxml")
        team_name = parser._extract_current_team_name(soup)

        candidates = []
        for table in soup.find_all("table", class_="table_box_row"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            header = " ".join(clean_text(c.get_text()).lower() for c in rows[0].find_all(["th", "td"]))
            if "дата" not in header or "соперник" not in header:
                continue
            for row in rows[1:]:
                c = parser._parse_candidate_row(row, team_name)
                if c:
                    candidates.append(c)
            break

        assert candidates
        finished = [c for c in candidates if c.match_url and "/boxscore/" in c.match_url and "/preview/" not in c.match_url]
        upcoming = [c for c in candidates if c.match_url and "/preview/" in c.match_url]
        assert len(finished) >= 4
        assert len(upcoming) >= 1
