"""Репозиторий для работы с пользователями в SQLite.

Хранит состояние пользователей: выбранная лига, команда и т.д.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from app.config import settings
from app.logger import logger


class UserRepository:
    """Репозиторий пользовательского состояния."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or settings.db_path
        self._initialized = False

    async def _connect(self) -> aiosqlite.Connection:
        """Создать соединение SQLite с безопасными pragma."""
        db = await aiosqlite.connect(self._db_path)
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        return db

    async def _ensure_db(self) -> None:
        """Создать таблицы если их нет."""
        if self._initialized:
            return

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        async with await self._connect() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_states (
                    telegram_id INTEGER PRIMARY KEY,
                    selected_league_id TEXT,
                    selected_league_name TEXT,
                    selected_team_id TEXT,
                    selected_team_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

        self._initialized = True

    async def get_selected_league(self, telegram_id: int) -> Optional[tuple[str, str]]:
        """Получить выбранную лигу пользователя.

        Returns:
            Кортеж (league_id, league_name) или None.
        """
        await self._ensure_db()
        async with await self._connect() as db:
            async with db.execute(
                "SELECT selected_league_id, selected_league_name FROM user_states WHERE telegram_id = ?",
                (telegram_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return row if row else None

    async def set_selected_league(self, telegram_id: int, league_id: str, league_name: str) -> None:
        """Сохранить выбранную лигу."""
        await self._ensure_db()
        async with await self._connect() as db:
            await db.execute(
                """
                INSERT INTO user_states (telegram_id, selected_league_id, selected_league_name, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    selected_league_id = excluded.selected_league_id,
                    selected_league_name = excluded.selected_league_name,
                    updated_at = excluded.updated_at
                """,
                (telegram_id, league_id, league_name, datetime.now().isoformat()),
            )
            await db.commit()

    async def get_selected_team(self, telegram_id: int) -> Optional[tuple[str, str]]:
        """Получить выбранную команду пользователя.

        Returns:
            Кортеж (team_id, team_name) или None.
        """
        await self._ensure_db()
        async with await self._connect() as db:
            async with db.execute(
                "SELECT selected_team_id, selected_team_name FROM user_states WHERE telegram_id = ?",
                (telegram_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return row if row else None

    async def set_selected_team(self, telegram_id: int, team_id: str, team_name: str) -> None:
        """Сохранить выбранную команду."""
        await self._ensure_db()
        async with await self._connect() as db:
            await db.execute(
                """
                INSERT INTO user_states (telegram_id, selected_team_id, selected_team_name, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    selected_team_id = excluded.selected_team_id,
                    selected_team_name = excluded.selected_team_name,
                    updated_at = excluded.updated_at
                """,
                (telegram_id, team_id, team_name, datetime.now().isoformat()),
            )
            await db.commit()

    async def clear_selection(self, telegram_id: int) -> None:
        """Очистить выбор пользователя."""
        await self._ensure_db()
        async with await self._connect() as db:
            await db.execute(
                """
                UPDATE user_states SET
                    selected_league_id = NULL,
                    selected_league_name = NULL,
                    selected_team_id = NULL,
                    selected_team_name = NULL,
                    updated_at = ?
                WHERE telegram_id = ?
                """,
                (datetime.now().isoformat(), telegram_id),
            )
            await db.commit()

    async def clear_all(self) -> None:
        """Очистить все состояния (для отладки)."""
        await self._ensure_db()
        async with await self._connect() as db:
            await db.execute("DELETE FROM user_states")
            await db.commit()
        logger.info("Все пользовательские состояния очищены")
