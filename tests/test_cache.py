"""Тесты кеш-сервиса."""

import asyncio

import pytest

from app.services.cache import CacheService, InMemoryCache


@pytest.fixture
def cache() -> CacheService:
    """Создать кеш для тестов."""
    return CacheService(InMemoryCache())


@pytest.mark.asyncio
async def test_cache_set_get(cache: CacheService) -> None:
    """Базовое сохранение и получение."""
    await cache.set("key1", "value1", ttl=60)
    result = await cache.get("key1")
    assert result == "value1"


@pytest.mark.asyncio
async def test_cache_get_missing(cache: CacheService) -> None:
    """Получение отсутствующего ключа."""
    result = await cache.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_cache_delete(cache: CacheService) -> None:
    """Удаление ключа."""
    await cache.set("key1", "value1", ttl=60)
    await cache.delete("key1")
    result = await cache.get("key1")
    assert result is None


@pytest.mark.asyncio
async def test_cache_clear(cache: CacheService) -> None:
    """Очистка всего кеша."""
    await cache.set("key1", "value1", ttl=60)
    await cache.set("key2", "value2", ttl=60)
    await cache.clear()
    assert await cache.get("key1") is None
    assert await cache.get("key2") is None


@pytest.mark.asyncio
async def test_cache_ttl_expiration(cache: CacheService) -> None:
    """Истечение TTL."""
    await cache.set("key1", "value1", ttl=1)
    # Сразу доступно
    assert await cache.get("key1") == "value1"
    # Ждём истечения
    await asyncio.sleep(1.1)
    assert await cache.get("key1") is None


@pytest.mark.asyncio
async def test_cache_typed_methods(cache: CacheService) -> None:
    """Типизированные методы кеша."""
    data = [{"id": "1", "name": "Лига 1"}]
    await cache.set_leagues(data)
    result = await cache.get_leagues()
    assert result == data

    await cache.set_teams("league1", [{"id": "1", "name": "Команда"}])
    result = await cache.get_teams("league1")
    assert len(result) == 1

    await cache.set_standings("league1", [{"position": 1}])
    result = await cache.get_standings("league1")
    assert result[0]["position"] == 1


@pytest.mark.asyncio
async def test_cache_cleanup(cache: CacheService) -> None:
    """Очистка протухших записей."""
    await cache.set("expired", "value", ttl=1)
    await cache.set("fresh", "value", ttl=3600)

    await asyncio.sleep(1.1)
    cleaned = await cache.cleanup()
    assert cleaned == 1
    assert await cache.get("fresh") == "value"
    assert await cache.get("expired") is None
