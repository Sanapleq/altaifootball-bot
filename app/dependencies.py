"""Модуль глобальных зависимостей (DI).

Использует явные синглтоны, которые инициализируются один раз
при запуске бота (в on_startup) и импортируются напрямую в handlers.

Это надёжный подход для aiogram 3.x без middleware.
"""

from __future__ import annotations

from app.repositories.subscription_repo import SubscriptionRepository
from app.repositories.user_repo import UserRepository
from app.services.football_service import FootballService

# ── Глобальные синглтоны ──────────────────────────────────────────
# Инициализируются ОДНОЖДЫ в init_dependencies().
# До вызова init_dependencies() равны None.
# После — гарантированно не None.
#
# Безопасность: handlers импортируют эти переменные и используют их
# только после запуска бота (on_startup уже отработал).
# При тестировании — вызывайте init_dependencies() вручную.
# ───────────────────────────────────────────────────────────────────

football_service: FootballService | None = None
user_repo: UserRepository | None = None
sub_repo: SubscriptionRepository | None = None


def init_dependencies() -> tuple[FootballService, UserRepository, SubscriptionRepository]:
    """Создать и сохранить все зависимости.

    Вызывается ОДНОЖДЫ при запуске бота (в on_startup).
    При повторном вызове — пересоздаёт всё заново.

    Returns:
        Кортеж (football_service, user_repo, sub_repo).
    """
    global football_service, user_repo, sub_repo

    user_repo = UserRepository()
    sub_repo = SubscriptionRepository()
    football_service = FootballService()

    return football_service, user_repo, sub_repo


async def close_dependencies() -> None:
    """Закрыть ресурсы (HTTP-клиенты, соединения).

    Вызывается при остановке бота (в on_shutdown).
    """
    global football_service, user_repo, sub_repo

    if football_service is not None:
        await football_service.close()
        football_service = None

    user_repo = None
    sub_repo = None
