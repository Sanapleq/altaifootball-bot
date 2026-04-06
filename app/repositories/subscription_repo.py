"""Репозиторий подписок в SQLite.

Хранит подписки пользователей на команды.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from app.config import settings
from app.logger import logger


class SubscriptionRepository:
    """Репозиторий подписок."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or settings.db_path
        self._initialized = False

    async def _ensure_db(self) -> None:
        """Создать таблицы если их нет."""
        if self._initialized:
            return

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_telegram_id INTEGER NOT NULL,
                    team_id TEXT NOT NULL,
                    team_name TEXT NOT NULL,
                    league_id TEXT,
                    league_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_telegram_id, team_id)
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_subscriptions_user
                ON subscriptions(user_telegram_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_subscriptions_team
                ON subscriptions(team_id)
            """)
            await db.commit()

        self._initialized = True

    async def subscribe(
        self,
        user_telegram_id: int,
        team_id: str,
        team_name: str,
        league_id: Optional[str] = None,
        league_name: Optional[str] = None,
    ) -> bool:
        """Подписать пользователя на команду.

        Returns:
            True если подписка создана, False если уже существует.
        """
        await self._ensure_db()
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """
                    INSERT INTO subscriptions (user_telegram_id, team_id, team_name, league_id, league_name)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_telegram_id, team_id, team_name, league_id, league_name),
                )
                await db.commit()
                logger.info(
                    f"Подписка создана: user={user_telegram_id}, team={team_name} ({team_id})"
                )
                return True
        except aiosqlite.IntegrityError:
            # Уже подписан
            return False

    async def unsubscribe(self, user_telegram_id: int, team_id: str) -> bool:
        """Отписать пользователя от команды.

        Returns:
            True если подписка удалена, False если не найдена.
        """
        await self._ensure_db()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM subscriptions WHERE user_telegram_id = ? AND team_id = ?",
                (user_telegram_id, team_id),
            )
            await db.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Подписка удалена: user={user_telegram_id}, team={team_id}")
            return deleted

    async def get_user_subscriptions(self, user_telegram_id: int) -> list[dict]:
        """Получить все подписки пользователя.

        Returns:
            Список словарей с данными подписок.
        """
        await self._ensure_db()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM subscriptions WHERE user_telegram_id = ? ORDER BY created_at DESC",
                (user_telegram_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def is_subscribed(self, user_telegram_id: int, team_id: str) -> bool:
        """Проверить, подписан ли пользователь на команду."""
        await self._ensure_db()
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT 1 FROM subscriptions WHERE user_telegram_id = ? AND team_id = ? LIMIT 1",
                (user_telegram_id, team_id),
            ) as cursor:
                row = await cursor.fetchone()
                return row is not None

    async def get_subscribers_for_team(self, team_id: str) -> list[int]:
        """Получить всех подписчиков команды (для рассылки уведомлений)."""
        await self._ensure_db()
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT user_telegram_id FROM subscriptions WHERE team_id = ?",
                (team_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

    async def get_user_subscription_count(self, user_telegram_id: int) -> int:
        """Получить количество подписок пользователя."""
        await self._ensure_db()
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM subscriptions WHERE user_telegram_id = ?",
                (user_telegram_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def clear_user_subscriptions(self, user_telegram_id: int) -> int:
        """Удалить все подписки пользователя.

        Returns:
            Количество удалённых подписок.
        """
        await self._ensure_db()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM subscriptions WHERE user_telegram_id = ?",
                (user_telegram_id,),
            )
            await db.commit()
            count = cursor.rowcount
            if count > 0:
                logger.info(f"Удалено {count} подписок пользователя {user_telegram_id}")
            return count
