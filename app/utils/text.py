"""Текстовые утилиты."""

from __future__ import annotations

import re


def pluralize(n: int, one: str, few: str, many: str) -> str:
    """Склонение существительных.

    Args:
        n: Число.
        one: Форма для 1 (очко, матч).
        few: Форма для 2-4 (очка, матча).
        many: Форма для 5-10 (очков, матчей).

    Returns:
        Правильная форма слова.
    """
    abs_n = abs(n) % 100
    last_digit = abs_n % 10

    if abs_n > 10 and abs_n < 20:
        return many
    if last_digit == 1:
        return one
    if 2 <= last_digit <= 4:
        return few
    return many


def pluralize_points(n: int) -> str:
    """Склонение слова 'очко'."""
    return pluralize(n, "очко", "очка", "очков")


def pluralize_matches(n: int) -> str:
    """Склонение слова 'матч'."""
    return pluralize(n, "матч", "матча", "матчей")


def pluralize_games(n: int) -> str:
    """Склонение слова 'игра'."""
    return pluralize(n, "игра", "игры", "игр")


def truncate(text: str, max_length: int = 60) -> str:
    """Обрезать текст до максимальной длины.

    Args:
        text: Исходный текст.
        max_length: Максимальная длина.

    Returns:
        Обрезанный текст с многоточием если нужно.
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def escape_html(text: str) -> str:
    """Экранировать HTML-символы для безопасного вывода в Telegram.

    Telegram поддерживает HTML-режим: <, >, & нужно экранировать.

    Args:
        text: Исходный текст.

    Returns:
        Безопасный для HTML текст.
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def clean_text(text: str) -> str:
    """Очистить текст от лишних пробелов и символов.

    Args:
        text: Исходный текст.

    Returns:
        Очищенный текст.
    """
    if not text:
        return ""
    # Заменяем несколько пробелов на один
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_team_name(name: str) -> str:
    """Нормализовать имя команды для поиска и сопоставления.

    Убирает лишние пробелы/кавычки, приводит ё->е и нижнему регистру.
    """
    if not name:
        return ""
    name = clean_text(name).lower().replace("ё", "е")
    name = name.replace('"', "").replace("«", "").replace("»", "").replace("'", "")
    name = re.sub(r"[^\w\s\-]", " ", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name).strip()
    return name
