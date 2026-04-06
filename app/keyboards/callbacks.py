"""Вспомогательные функции для работы с callback-данными."""

from __future__ import annotations

from typing import Optional


def parse_callback(callback_data: str) -> tuple[str, Optional[str]]:
    """Распарсить callback data.

    Формат: action:param или action

    Args:
        callback_data: Строка callback.

    Returns:
        Кортеж (action, param).
    """
    if ":" in callback_data:
        parts = callback_data.split(":", 1)
        return parts[0], parts[1]
    return callback_data, None


def parse_callback_multi(callback_data: str) -> list[str]:
    """Распарсить callback с несколькими параметрами.

    Формат: action:param1:param2:...

    Args:
        callback_data: Строка callback.

    Returns:
        Список частей.
    """
    return callback_data.split(":")
