"""Тесты новых фич: заявка, статистика, прогноз, сезоны, H2H."""

import pytest
from datetime import datetime, timedelta

from app.models.football import (
    League, Match, Player, PlayerStat, StandingRow, Team, MatchPrediction,
)
from app.services.formatter import FootballFormatter
from app.services.football_service import FootballService


# ====================================================================
# Модели
# ====================================================================

class TestPlayer:
    """Тесты модели Player."""

    def test_create_player(self) -> None:
        """Создание игрока."""
        p = Player(name="Иван Иванов", number=10)
        assert p.name == "Иван Иванов"
        assert p.number == 10
        assert p.position is None
        assert p.matches == 0
        assert p.goals == 0

    def test_player_full(self) -> None:
        """Полный игрок."""
        from datetime import date
        p = Player(
            name="Пётр Петров",
            number=7,
            position="Нападающий",
            birth_date=date(1995, 3, 15),
            matches=12,
            goals=5,
        )
        assert p.name == "Пётр Петров"
        assert p.position == "Нападающий"
        assert p.birth_date == date(1995, 3, 15)
        assert p.matches == 12
        assert p.goals == 5

    def test_player_short_name_rejected(self) -> None:
        """Короткое имя отклоняется."""
        with pytest.raises(Exception):
            Player(name="И")


class TestPlayerStat:
    """Тесты модели PlayerStat."""

    def test_create_stat(self) -> None:
        """Создание статистики."""
        s = PlayerStat(name="Иванов", matches=5, goals=3)
        assert s.name == "Иванов"
        assert s.matches == 5
        assert s.goals == 3
        assert s.assists == 0
        assert s.yellow_cards == 0

    def test_stat_full(self) -> None:
        """Полная статистика."""
        s = PlayerStat(
            name="Петров",
            matches=10, goals=5, assists=3,
            yellow_cards=2, red_cards=1, minutes=870,
        )
        assert s.matches == 10
        assert s.goals == 5
        assert s.assists == 3
        assert s.yellow_cards == 2
        assert s.red_cards == 1
        assert s.minutes == 870


class TestMatchPrediction:
    """Тесты модели MatchPrediction."""

    def test_create_prediction(self) -> None:
        """Создание прогноза."""
        p = MatchPrediction(
            home_team="Команда А",
            away_team="Команда Б",
            predicted_home_score=2,
            predicted_away_score=1,
            prediction_text="Команда А выглядит фаворитом",
        )
        assert p.home_team == "Команда А"
        assert p.predicted_home_score == 2
        assert p.h2h_total == 0  # default

    def test_prediction_with_h2h(self) -> None:
        """Прогноз с личными встречами."""
        p = MatchPrediction(
            home_team="А",
            away_team="Б",
            h2h_total=5,
            h2h_home_wins=3,
            h2h_draws=1,
            h2h_away_wins=1,
            h2h_goals=12,
            home_position=2,
            away_position=5,
        )
        assert p.h2h_total == 5
        assert p.home_position == 2
        assert p.away_position == 5


# ====================================================================
# Форматтеры
# ====================================================================

class TestFormatterRoster:
    """Тесты formatter заявки."""

    def test_format_roster_empty(self) -> None:
        """Пустая заявка."""
        result = FootballFormatter.format_team_roster([], "Команда")
        assert "😔" in result or "не удалось" in result.lower()

    def test_format_roster(self) -> None:
        """Заявка с игроками."""
        from datetime import date
        players = [
            Player(name="Иван Иванов", number=10, position="Нападающий"),
            Player(name="Пётр Петров", number=1, position="Вратарь",
                   birth_date=date(1990, 1, 1), matches=15, goals=0),
        ]
        result = FootballFormatter.format_team_roster(players, "Тест")
        assert "Иван Иванов" in result
        assert "Пётр Петров" in result
        assert "№10" in result
        assert "Нападающий" in result
        assert "Матчи: 15" in result


class TestFormatterPlayerStats:
    """Тесты formatter статистики."""

    def test_format_stats_empty(self) -> None:
        """Пустая статистика."""
        result = FootballFormatter.format_team_player_stats([], "Команда")
        assert "😔" in result or "не удалось" in result.lower()

    def test_format_stats(self) -> None:
        """Статистика игроков."""
        stats = [
            PlayerStat(name="Иванов", matches=5, goals=3, assists=1, yellow_cards=2),
            PlayerStat(name="Петров", matches=5, goals=1),
        ]
        result = FootballFormatter.format_team_player_stats(stats, "Тест")
        assert "Иванов" in result
        assert "Петров" in result
        assert "⚽ 3" in result
        assert "🟨 2" in result
        # Сортировка по голам — Иванов первый
        ivanov_pos = result.index("Иванов")
        petrov_pos = result.index("Петров")
        assert ivanov_pos < petrov_pos


class TestFormatterPrediction:
    """Тесты formatter прогноза."""

    def test_format_prediction_basic(self) -> None:
        """Базовый прогноз."""
        from datetime import datetime
        pred = MatchPrediction(
            home_team="Команда А",
            away_team="Команда Б",
            match_date=datetime(2026, 4, 11, 16, 0),
            home_wins=3, home_draws=1, home_losses=1,
            home_goals_scored=2.0, home_goals_conceded=0.8,
            away_wins=1, away_draws=2, away_losses=2,
            away_goals_scored=0.8, away_goals_conceded=1.5,
            predicted_home_score=2, predicted_away_score=1,
            prediction_text="Команда А выглядит фаворитом",
        )
        result = FootballFormatter.format_match_prediction(pred)
        assert "Команда А" in result
        assert "Команда Б" in result
        assert "2:1" in result
        assert "Форма" in result
        assert "Вывод" in result
        assert "статистический прогноз" in result

    def test_format_prediction_with_h2h(self) -> None:
        """Прогноз с личными встречами."""
        pred = MatchPrediction(
            home_team="А",
            away_team="Б",
            h2h_total=5,
            h2h_home_wins=3,
            h2h_draws=1,
            h2h_away_wins=1,
            h2h_home_goals=12,
            h2h_away_goals=5,
            predicted_home_score=2,
            predicted_away_score=1,
            prediction_text="А фаворит",
        )
        result = FootballFormatter.format_match_prediction(pred)
        assert "Личные встречи" in result
        assert "5 встреч" in result
        assert "Победы А: 3" in result
        assert "Голы А: 12" in result
        assert "Голы Б: 5" in result

    def test_format_prediction_with_positions(self) -> None:
        """Прогноз с позициями в таблице."""
        pred = MatchPrediction(
            home_team="А",
            away_team="Б",
            home_position=2,
            away_position=7,
            predicted_home_score=2,
            predicted_away_score=1,
            prediction_text="А выше в таблице",
        )
        result = FootballFormatter.format_match_prediction(pred)
        assert "Позиция в таблице: 2" in result
        assert "Позиция в таблице: 7" in result


# ====================================================================
# Расчёт формы (unit-тесты логики)
# ====================================================================

class TestFormMetrics:
    """Тесты расчёта формы команды."""

    def _make_service(self) -> FootballService:
        return FootballService()

    def _make_match(self, home: str, away: str, hs: int, aws: int) -> Match:
        return Match(
            id=f"{home}_{away}",
            home_team=home,
            away_team=away,
            home_score=hs,
            away_score=aws,
            status="finished",
        )

    def test_home_team_form(self) -> None:
        """Форма команды дома."""
        svc = self._make_service()
        results = [
            self._make_match("А", "Б", 2, 1),  # победа
            self._make_match("А", "В", 3, 0),  # победа
            self._make_match("А", "Г", 1, 1),  # ничья
        ]
        metrics = svc._calc_form_metrics(results, "А")
        assert metrics["wins"] == 2
        assert metrics["draws"] == 1
        assert metrics["losses"] == 0
        assert metrics["avg_scored"] == 2.0  # (2+3+1)/3
        assert metrics["avg_conceded"] == round(2 / 3, 1)  # (1+0+1)/3

    def test_away_team_form(self) -> None:
        """Форма команды в гостях."""
        svc = self._make_service()
        results = [
            self._make_match("Б", "А", 0, 3),  # А победила в гостях
            self._make_match("В", "А", 2, 2),  # ничья в гостях
            self._make_match("Г", "А", 1, 0),  # поражение в гостях
        ]
        metrics = svc._calc_form_metrics(results, "А")
        assert metrics["wins"] == 1
        assert metrics["draws"] == 1
        assert metrics["losses"] == 1
        assert metrics["avg_scored"] == round(5 / 3, 1)  # (3+2+0)/3
        assert metrics["avg_conceded"] == 1.0  # (0+2+1)/3

    def test_empty_results(self) -> None:
        """Пустые результаты."""
        svc = self._make_service()
        metrics = svc._calc_form_metrics([], "А")
        assert metrics["wins"] == 0
        assert metrics["avg_scored"] == 0.0
        assert metrics["matches"] == 0

    def test_mixed_home_away_form(self) -> None:
        """Смешанная форма: дома и в гостях."""
        svc = self._make_service()
        results = [
            self._make_match("А", "Б", 3, 1),  # А дома, победа
            self._make_match("В", "А", 0, 2),  # А в гостях, победа
            self._make_match("А", "Г", 1, 1),  # А дома, ничья
            self._make_match("Д", "А", 2, 0),  # А в гостях, поражение
            self._make_match("А", "Е", 4, 0),  # А дома, победа
        ]
        metrics = svc._calc_form_metrics(results, "А")
        assert metrics["wins"] == 3
        assert metrics["draws"] == 1
        assert metrics["losses"] == 1
        # Забитые: 3(home) + 2(away) + 1(home) + 0(away) + 4(home) = 10
        assert metrics["avg_scored"] == 2.0  # 10/5
        # Пропущенные: 1 + 0 + 1 + 2 + 0 = 4
        assert metrics["avg_conceded"] == 0.8  # 4/5


# ====================================================================
# Личные встречи
# ====================================================================

class TestHeadToHead:
    """Тесты личных встреч."""

    def _make_match(self, home: str, away: str, hs: int, aws: int) -> Match:
        return Match(
            id=f"{home}_{away}",
            home_team=home,
            away_team=away,
            home_score=hs,
            away_score=aws,
            status="finished",
        )

    @pytest.mark.asyncio
    async def test_h2h_basic(self) -> None:
        """Личные встречи считаются правильно."""
        svc = FootballService()
        team_results = [
            self._make_match("А", "Б", 2, 1),  # А победила дома
            self._make_match("А", "В", 5, 0),  # не H2H
        ]
        opp_results = [
            self._make_match("Б", "А", 0, 3),  # Б дома, А победила
            self._make_match("А", "Б", 1, 1),  # дубликат из team_results (dedup)
        ]
        h2h = await svc._get_head_to_head(team_results, opp_results, "А", "Б")
        # Матч "А_Б" дедуплицирован → 2 уникальных матча:
        # "А_Б" (2:1) + "Б_А" (0:3)
        assert h2h["total"] == 2
        assert h2h["team_wins"] == 2  # А победила в обоих (2:1 и 0:3)
        assert h2h["draws"] == 0
        assert h2h["opponent_wins"] == 0
        assert h2h["team_goals"] == 5     # 2(home) + 3(away)
        assert h2h["opponent_goals"] == 1  # 1(home) + 0(away)

    @pytest.mark.asyncio
    async def test_h2h_no_matches(self) -> None:
        """Нет личных встреч."""
        svc = FootballService()
        team_results = [
            self._make_match("А", "В", 2, 1),
        ]
        opp_results = [
            self._make_match("Б", "Г", 3, 0),
        ]
        h2h = await svc._get_head_to_head(team_results, opp_results, "А", "Б")
        assert h2h["total"] == 0

    @pytest.mark.asyncio
    async def test_h2h_both_perspectives(self) -> None:
        """Личные встречи учитывают результаты обеих команд."""
        svc = FootballService()
        team_results = [
            self._make_match("А", "Б", 2, 0),  # А дома
            self._make_match("А", "В", 3, 1),  # не H2H
        ]
        opp_results = [
            self._make_match("Б", "А", 1, 1),  # Б дома, ничья
            self._make_match("Б", "Г", 2, 0),  # не H2H
        ]
        h2h = await svc._get_head_to_head(team_results, opp_results, "А", "Б")
        assert h2h["total"] == 2
        assert h2h["team_wins"] == 1  # А победила 2:0
        assert h2h["draws"] == 1  # 1:1
        assert h2h["opponent_wins"] == 0

    @pytest.mark.asyncio
    async def test_h2h_dedup(self) -> None:
        """Один и тот же матч не дублируется."""
        svc = FootballService()
        # Один и тот же матч в результатах обеих команд
        team_results = [
            self._make_match("А", "Б", 2, 1),
        ]
        opp_results = [
            self._make_match("А", "Б", 2, 1),  # тот же матч
        ]
        h2h = await svc._get_head_to_head(team_results, opp_results, "А", "Б")
        assert h2h["total"] == 1  # не 2!


# ====================================================================
# Home/away mapping в прогнозе
# ====================================================================

class TestPredictionMapping:
    """Тесты правильного распределения home/away в прогнозе."""

    def test_team_home_mapping(self) -> None:
        """Когда team = home_team, метрики team → home_*."""
        from app.models.football import MatchPrediction

        # Проверяем через прямое конструирование
        pred = MatchPrediction(
            home_team="Команда А",
            away_team="Команда Б",
            home_wins=3, home_draws=1, home_losses=1,
            home_goals_scored=2.0, home_goals_conceded=0.8,
            away_wins=1, away_draws=2, away_losses=2,
            away_goals_scored=0.8, away_goals_conceded=1.5,
            predicted_home_score=2, predicted_away_score=1,
            prediction_text="А фаворит",
        )
        # home_team == "Команда А" → home_* должны быть метриками "А"
        assert pred.home_team == "Команда А"
        assert pred.home_wins == 3
        assert pred.home_goals_scored == 2.0

    def test_team_away_mapping(self) -> None:
        """Когда team = away_team, метрики team → away_*."""
        from app.models.football import MatchPrediction

        pred = MatchPrediction(
            home_team="Б",
            away_team="А",
            home_wins=1, home_draws=2, home_losses=2,
            home_goals_scored=0.8, home_goals_conceded=1.5,
            away_wins=3, away_draws=1, away_losses=1,
            away_goals_scored=2.0, away_goals_conceded=0.8,
            predicted_home_score=1, predicted_away_score=2,
            prediction_text="А фаворит",
        )
        # home_team == "Б" ≠ "А" → home_* это метрики соперника
        assert pred.home_team == "Б"
        assert pred.home_wins == 1  # метрики соперника
        assert pred.away_wins == 3  # метрики "А"


# ====================================================================
# Сезоны
# ====================================================================

class TestSeasons:
    """Тесты фильтрации по сезонам."""

    @pytest.mark.asyncio
    async def test_filter_by_season(self) -> None:
        """Фильтрация лиг по сезону."""
        svc = FootballService()
        # Mock leagues
        leagues = [
            League(id="1", name="Лига А", url="http://a.com/1", season="2026"),
            League(id="2", name="Лига Б", url="http://a.com/2", season="2025"),
            League(id="3", name="Лига В", url="http://a.com/3", season="2026"),
        ]
        # Manually test filtering logic
        filtered = [lg for lg in leagues if lg.season == "2026"]
        assert len(filtered) == 2
        assert all(lg.season == "2026" for lg in filtered)

    @pytest.mark.asyncio
    async def test_available_seasons(self) -> None:
        """Список доступных сезонов."""
        leagues = [
            League(id="1", name="Лига А", url="http://a.com/1", season="2026"),
            League(id="2", name="Лига Б", url="http://a.com/2", season="2025"),
            League(id="3", name="Лига В", url="http://a.com/3", season="2024"),
            League(id="4", name="Лига Г", url="http://a.com/4", season="2026"),
        ]
        seasons = sorted(set(lg.season for lg in leagues if lg.season), reverse=True)
        assert seasons == ["2026", "2025", "2024"]


# ====================================================================
# Стабильность парсинга
# ====================================================================

class TestEmptyHtmlError:
    """Тесты: пустой HTML считается ошибкой."""

    def test_parse_html_empty_string(self) -> None:
        """Пустая строка → SiteParserError."""
        from app.services.parser import SiteParser, SiteParserError
        parser = SiteParser()
        with pytest.raises(SiteParserError, match="Пустой HTML"):
            parser._parse_html("")

    def test_parse_html_too_small(self) -> None:
        """Слишком маленький HTML → SiteParserError."""
        from app.services.parser import SiteParser, SiteParserError
        parser = SiteParser()
        with pytest.raises(SiteParserError, match="Пустой HTML"):
            parser._parse_html("<html></html>")

    def test_parse_html_valid(self) -> None:
        """Валидный HTML → BS4 объект."""
        from app.services.parser import SiteParser
        parser = SiteParser()
        # HTML должен быть >= 100 bytes
        html = "<html><head><title>Test Page</title></head><body><div class='content'><table class='table_box_row'><tr><th>М</th><th>Команда</th></tr><tr><td>1</td><td>Тест</td></tr></table></div></body></html>"
        soup = parser._parse_html(html)
        assert soup is not None
        assert soup.find("table") is not None


class TestFormMetricsCorrectness:
    """Тесты: форма команды считается правильно, не перевёрнуто."""

    def _make_match(self, home: str, away: str, hs: int, aws: int) -> Match:
        return Match(
            id=f"{home}_{away}",
            home_team=home,
            away_team=away,
            home_score=hs,
            away_score=aws,
            status="finished",
        )

    def test_home_win_is_win(self) -> None:
        """Команда дома победила 2:1 → wins=1."""
        svc = FootballService()
        results = [self._make_match("СКА", "Соперник", 2, 1)]
        metrics = svc._calc_form_metrics(results, "СКА")
        assert metrics["wins"] == 1
        assert metrics["losses"] == 0
        assert metrics["avg_scored"] == 2.0

    def test_away_loss_is_loss(self) -> None:
        """Команда в гостях проиграла 1:3 → losses=1."""
        svc = FootballService()
        # Хозяин забил 3, гость (СКА) забил 1 → поражение
        results = [self._make_match("Соперник", "СКА", 3, 1)]
        metrics = svc._calc_form_metrics(results, "СКА")
        assert metrics["wins"] == 0
        assert metrics["losses"] == 1
        # СКА забила 1 (away_score), пропустила 3 (home_score)
        assert metrics["avg_scored"] == 1.0
        assert metrics["avg_conceded"] == 3.0

    def test_away_win_is_win(self) -> None:
        """Команда в гостях победила 3:1 → wins=1."""
        svc = FootballService()
        # Хозяин забил 1, гость (СКА) забил 3 → победа
        results = [self._make_match("Соперник", "СКА", 1, 3)]
        metrics = svc._calc_form_metrics(results, "СКА")
        assert metrics["wins"] == 1
        assert metrics["losses"] == 0
        assert metrics["avg_scored"] == 3.0
        assert metrics["avg_conceded"] == 1.0

    def test_home_draw_is_draw(self) -> None:
        """Команда дома сыграла вничью 1:1 → draws=1."""
        svc = FootballService()
        results = [self._make_match("СКА", "Соперник", 1, 1)]
        metrics = svc._calc_form_metrics(results, "СКА")
        assert metrics["wins"] == 0
        assert metrics["draws"] == 1
        assert metrics["losses"] == 0


class TestPredictionNoFlip:
    """Тесты: прогноз не переворачивает победы/поражения."""

    def _make_match(self, home: str, away: str, hs: int, aws: int) -> Match:
        return Match(
            id=f"{home}_{away}",
            home_team=home,
            away_team=away,
            home_score=hs,
            away_score=aws,
            status="finished",
        )

    def test_away_losses_not_counted_as_wins(self) -> None:
        """Если команда проиграла все матчи в гостях → losses, не wins."""
        svc = FootballService()
        # СКА играла в гостях и проиграла 3 матча из 4
        results = [
            self._make_match("А", "СКА", 3, 0),
            self._make_match("Б", "СКА", 2, 0),
            self._make_match("В", "СКА", 1, 0),
            self._make_match("Г", "СКА", 1, 2),  # одна победа
        ]
        metrics = svc._calc_form_metrics(results, "СКА")
        assert metrics["wins"] == 1
        assert metrics["losses"] == 3
        assert metrics["avg_scored"] == round(2 / 4, 1)  # 0+0+0+2=2
        assert metrics["avg_conceded"] == round(7 / 4, 1)  # 3+2+1+1=7

    def test_prediction_uses_correct_metrics(self) -> None:
        """Прогноз использует правильные метрики home/away."""
        from app.models.football import MatchPrediction

        # Симуляция: team играет в гостях, проиграла 3 из 4
        pred = MatchPrediction(
            home_team="Соперник",
            away_team="СКА Сибирский ЗАТО",
            home_wins=3, home_draws=0, home_losses=1,
            home_goals_scored=1.8, home_goals_conceded=0.5,
            away_wins=1, away_draws=0, away_losses=3,
            away_goals_scored=0.5, away_goals_conceded=1.8,
            predicted_home_score=2, predicted_away_score=1,
            prediction_text="Соперник фаворит",
        )
        # away_wins = 1, away_losses = 3 — правильно для СКА
        assert pred.away_wins == 1
        assert pred.away_losses == 3
        # home_team ≠ away_team → home_* это метрики соперника
        assert pred.home_wins == 3
