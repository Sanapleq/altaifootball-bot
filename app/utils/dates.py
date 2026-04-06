"""Утилиты для работы с датами."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def parse_russian_date(date_str: str) -> Optional[datetime]:
    """Распарсить дату из русского формата.

    Поддерживаемые форматы:
        - DD.MM.YYYY
        - DD.MM.YYYY HH:MM
        - DD/MM/YYYY
        - YYYY-MM-DD
        - DD Month YYYY (русские названия месяцев)

    Args:
        date_str: Строка с датой.

    Returns:
        datetime или None если не удалось распарсить.
    """
    if not date_str or not date_str.strip():
        return None

    date_str = date_str.strip()

    # Русские названия месяцев
    month_map = {
        "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
        "мая": "05", "июня": "06", "июля": "07", "августа": "08",
        "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12",
    }

    # Пробуем DD.MM.YYYY HH:MM
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    # Пробуем формат с русским месяцем: "12 апреля 2026"
    parts = date_str.split()
    if len(parts) >= 3:
        day = parts[0]
        month_str = parts[1].lower()
        year = parts[2]

        month = month_map.get(month_str)
        if month:
            # Дополняем день до 2 знаков
            day = day.zfill(2)
            try:
                return datetime.strptime(f"{day}.{month}.{year}", "%d.%m.%Y")
            except ValueError:
                pass

    return None


def format_date_short(dt: Optional[datetime]) -> str:
    """Форматировать дату в короткий вид DD.MM.YYYY.

    Args:
        dt: datetime объект.

    Returns:
        Строка с датой или прочерк.
    """
    if dt is None:
        return "—"
    return dt.strftime("%d.%m.%Y")


def format_date_time(dt: Optional[datetime]) -> str:
    """Форматировать дату с временем DD.MM.YYYY HH:MM.

    Args:
        dt: datetime объект.

    Returns:
        Строка с датой и временем или прочерк.
    """
    if dt is None:
        return "—"
    return dt.strftime("%d.%m.%Y %H:%M")


def format_relative_date(dt: Optional[datetime]) -> str:
    """Форматировать дату относительно сегодня.

    Args:
        dt: datetime объект.

    Returns:
        Строка типа "Сегодня", "Завтра" или DD.MM.YYYY.
    """
    if dt is None:
        return "—"

    now = datetime.now()
    today = now.date()

    if dt.date() == today:
        return "Сегодня"
    elif (dt.date() - today).days == 1:
        return "Завтра"
    elif (dt.date() - today).days == -1:
        return "Вчера"
    else:
        return format_date_short(dt)
