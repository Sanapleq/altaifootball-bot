"""Кеш-сервис с TTL для кэширования данных сайта.

Интерфейсный дизайн — легко заменить на Redis или другой бэкенд.
Усилен статистикой хитов/промахов для диагностики.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Optional


class CacheBackend(ABC):
    """Абстрактный интерфейс кеша."""

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Получить значение из кеша."""
        ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int) -> None:
        """Сохранить значение в кеш с TTL (секунды)."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Удалить значение из кеша."""
        ...

    @abstractmethod
    async def clear(self) -> None:
        """Очистить весь кеш."""
        ...

    @abstractmethod
    def size(self) -> int:
        """Текущее количество записей."""
        ...


class InMemoryCache(CacheBackend):
    """In-memory кеш с TTL.

    Хранит данные в словаре. Периодически очищает протухшие записи.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}  # key -> (value, expire_at)
        self._hits = 0
        self._misses = 0

    async def get(self, key: str) -> Optional[Any]:
        """Получить значение. Возвращает None если ключа нет или запись протухла."""
        if key not in self._store:
            self._misses += 1
            return None

        value, expire_at = self._store[key]
        if time.time() > expire_at:
            # Запись протухла — удаляем
            del self._store[key]
            self._misses += 1
            return None

        self._hits += 1
        return value

    async def set(self, key: str, value: Any, ttl: int) -> None:
        """Сохранить значение с TTL в секундах."""
        self._store[key] = (value, time.time() + ttl)

    async def delete(self, key: str) -> None:
        """Удалить запись."""
        self._store.pop(key, None)

    async def clear(self) -> None:
        """Очистить весь кеш."""
        self._store.clear()
        self._hits = 0
        self._misses = 0

    def size(self) -> int:
        """Текущее количество записей (включая протухшие)."""
        return len(self._store)

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    async def cleanup_expired(self) -> int:
        """Очистить протухшие записи. Возвращает количество удалённых."""
        now = time.time()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        return len(expired)


# TTL константы (в секундах)
TTL_LEAGUES = 6 * 3600        # 6 часов
TTL_TEAMS = 6 * 3600          # 6 часов
TTL_STANDINGS = 3600           # 1 час
TTL_MATCHES = 30 * 60          # 30 минут
TTL_SEARCH = 3 * 3600         # 3 часа


class CacheService:
    """Сервис кэширования.

    Оборачивает CacheBackend и предоставляет удобные методы
    с предопределёнными TTL для разных типов данных.
    """

    def __init__(self, backend: Optional[CacheBackend] = None) -> None:
        self._backend = backend or InMemoryCache()

    # --- Обёртки с TTL ---

    async def get_leagues(self) -> Optional[Any]:
        return await self._backend.get("leagues")

    async def set_leagues(self, data: Any) -> None:
        await self._backend.set("leagues", data, TTL_LEAGUES)

    async def get_teams(self, league_id: str) -> Optional[Any]:
        return await self._backend.get(f"teams:{league_id}")

    async def set_teams(self, league_id: str, data: Any) -> None:
        await self._backend.set(f"teams:{league_id}", data, TTL_TEAMS)

    async def get_standings(self, league_id: str) -> Optional[Any]:
        return await self._backend.get(f"standings:{league_id}")

    async def set_standings(self, league_id: str, data: Any) -> None:
        await self._backend.set(f"standings:{league_id}", data, TTL_STANDINGS)

    async def get_matches(self, team_or_league_id: str) -> Optional[Any]:
        return await self._backend.get(f"matches:{team_or_league_id}")

    async def set_matches(self, team_or_league_id: str, data: Any) -> None:
        await self._backend.set(f"matches:{team_or_league_id}", data, TTL_MATCHES)

    async def get_search(self, query: str) -> Optional[Any]:
        return await self._backend.get(f"search:{query}")

    async def set_search(self, query: str, data: Any) -> None:
        await self._backend.set(f"search:{query}", data, TTL_SEARCH)

    # --- Общие методы ---

    async def get(self, key: str) -> Optional[Any]:
        return await self._backend.get(key)

    async def set(self, key: str, value: Any, ttl: int) -> None:
        await self._backend.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        await self._backend.delete(key)

    async def clear(self) -> None:
        await self._backend.clear()

    async def cleanup(self) -> int:
        """Очистить протухшие записи (если бэкенд поддерживает)."""
        if isinstance(self._backend, InMemoryCache):
            return await self._backend.cleanup_expired()
        return 0

    # --- Статистика ---

    @property
    def hits(self) -> int:
        """Количество cache hits."""
        if isinstance(self._backend, InMemoryCache):
            return self._backend.hits
        return 0

    @property
    def misses(self) -> int:
        """Количество cache misses."""
        if isinstance(self._backend, InMemoryCache):
            return self._backend.misses
        return 0

    @property
    def hit_rate(self) -> float:
        """Процент попаданий в кеш."""
        if isinstance(self._backend, InMemoryCache):
            return self._backend.hit_rate
        return 0.0

    @property
    def size(self) -> int:
        """Текущее количество записей в кеше."""
        if isinstance(self._backend, InMemoryCache):
            return self._backend.size()
        return 0

    def get_stats(self) -> dict[str, int | float]:
        """Получить статистику кеша для диагностики."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hit_rate, 3),
            "size": self.size,
        }


# Глобальный экземпляр кеша
cache = CacheService()
