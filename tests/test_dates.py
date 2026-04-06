"""Тесты утилит для работы с датами."""

import pytest
from datetime import datetime

from app.utils.dates import (
    format_date_short,
    format_date_time,
    format_relative_date,
    parse_russian_date,
)


class TestParseRussianDate:
    """Тесты парсинга русских дат."""

    def test_dd_mm_yyyy(self) -> None:
        """Формат DD.MM.YYYY."""
        result = parse_russian_date("05.04.2026")
        assert result is not None
        assert result.day == 5
        assert result.month == 4
        assert result.year == 2026

    def test_dd_mm_yyyy_hh_mm(self) -> None:
        """Формат DD.MM.YYYY HH:MM."""
        result = parse_russian_date("12.04.2026 18:30")
        assert result is not None
        assert result.hour == 18
        assert result.minute == 30

    def test_iso_format(self) -> None:
        """ISO формат YYYY-MM-DD."""
        result = parse_russian_date("2026-04-12")
        assert result is not None
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 12

    def test_slash_format(self) -> None:
        """Формат DD/MM/YYYY."""
        result = parse_russian_date("12/04/2026")
        assert result is not None
        assert result.day == 12
        assert result.month == 4

    def test_russian_month(self) -> None:
        """Русский месяц."""
        result = parse_russian_date("12 апреля 2026")
        assert result is not None
        assert result.month == 4

    def test_empty_string(self) -> None:
        """Пустая строка."""
        assert parse_russian_date("") is None
        assert parse_russian_date("   ") is None

    def test_invalid(self) -> None:
        """Невалидная дата."""
        assert parse_russian_date("invalid") is None
        assert parse_russian_date("32.13.2026") is None


class TestDateFormatting:
    """Тесты форматирования дат."""

    def test_format_date_short(self) -> None:
        """Короткий формат."""
        dt = datetime(2026, 4, 12)
        assert format_date_short(dt) == "12.04.2026"
        assert format_date_short(None) == "—"

    def test_format_date_time(self) -> None:
        """Формат с временем."""
        dt = datetime(2026, 4, 12, 18, 30)
        assert format_date_time(dt) == "12.04.2026 18:30"
        assert format_date_time(None) == "—"

    def test_format_relative_date_today(self) -> None:
        """Сегодня."""
        now = datetime.now()
        result = format_relative_date(now)
        assert result == "Сегодня"

    def test_format_relative_date_yesterday(self) -> None:
        """Вчера."""
        from datetime import timedelta
        yesterday = datetime.now() - timedelta(days=1)
        assert format_relative_date(yesterday) == "Вчера"

    def test_format_relative_date_tomorrow(self) -> None:
        """Завтра."""
        from datetime import timedelta
        tomorrow = datetime.now() + timedelta(days=1)
        assert format_relative_date(tomorrow) == "Завтра"

    def test_format_relative_date_none(self) -> None:
        """None."""
        assert format_relative_date(None) == "—"
