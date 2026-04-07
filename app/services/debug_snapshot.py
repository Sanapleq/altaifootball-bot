"""Debug-снапшоты HTML страниц.

Сохраняет HTML проблемных страниц в локальную директорию
для последующего анализа при отладке парсера.

Использование:
    from app.services.debug_snapshot import save_debug_html

    # В парсере, если не нашлись данные:
    save_debug_html(html, "team_6662_matches")
    save_debug_html(html, "tournament_3607", league_id="3607")
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

DEBUG_DIR = Path("debug_html")


def _ensure_debug_dir() -> None:
    """Создать директорию для debug-снапшотов если её нет."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)


def save_debug_html(
    html: str,
    name: str,
    league_id: Optional[str] = None,
    team_id: Optional[str] = None,
    extra: Optional[str] = None,
) -> Path:
    """Сохранить HTML страницы в debug-папку.

    Args:
        html: HTML-содержимое страницы.
        name: Базовое имя файла (например "team_matches", "tournament").
        league_id: ID лиги для имени файла (опционально).
        team_id: ID команды для имени файла (опционально).
        extra: Дополнительная метка (опционально).

    Returns:
        Путь к сохранённому файлу.
    """
    if not html or len(html) < 100:
        return Path()

    _ensure_debug_dir()

    # Формируем имя файла
    parts = [name]
    if league_id:
        parts.append(f"league_{league_id}")
    if team_id:
        parts.append(f"team_{team_id}")
    if extra:
        parts.append(extra)

    date_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts.append(date_stamp)

    filename = "_".join(parts) + ".html"
    filepath = DEBUG_DIR / filename

    try:
        filepath.write_text(html, encoding="utf-8")
    except Exception:
        pass

    return filepath


def get_debug_snapshots(name: Optional[str] = None) -> list[Path]:
    """Получить список сохранённых снапшотов.

    Args:
        name: Фильтр по базовому имени (опционально).

    Returns:
        Список путей к файлам.
    """
    if not DEBUG_DIR.exists():
        return []

    files = sorted(DEBUG_DIR.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    if name:
        files = [f for f in files if name in f.name]
    return files


def cleanup_old_snapshots(older_than_hours: int = 24) -> int:
    """Удалить снапшоты старше указанного времени.

    Args:
        older_than_hours: Удалять файлы старше N часов.

    Returns:
        Количество удалённых файлов.
    """
    if not DEBUG_DIR.exists():
        return 0

    import time
    cutoff = time.time() - (older_than_hours * 3600)
    deleted = 0

    for f in DEBUG_DIR.glob("*.html"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            deleted += 1

    return deleted
