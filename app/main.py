"""Точка входа в приложение — инициализация и запуск бота."""

from __future__ import annotations

import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings, ensure_dirs
from app.dependencies import close_dependencies, init_dependencies
from app.handlers import leagues, start
from app.logger import logger
from app.states import MainStates


async def on_startup() -> None:
    """Действия при запуске бота.

    Инициализирует базу данных и глобальные сервисы.
    Сервисы доступны через app.dependencies.*.
    """
    ensure_dirs()

    f_service, u_repo, s_repo = init_dependencies()

    # Инициализируем таблицы БД
    await u_repo._ensure_db()
    await s_repo._ensure_db()

    logger.info("=" * 50)
    logger.info("Altaifootball Bot запущен!")
    logger.info("   База данных: %s", settings.db_path)
    logger.info("   Сайт: %s", settings.base_url)
    logger.info("   Лог: уровень %s", settings.log_level)
    logger.info("=" * 50)


async def on_shutdown() -> None:
    """Действия при остановке бота."""
    await close_dependencies()
    logger.info("Бот остановлен")


def create_bot() -> Bot:
    """Создать экземпляр бота с настройками по умолчанию."""
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    """Создать диспетчер и зарегистрировать все обработчики.

    Роутеры подключаются в порядке приоритета:
    1. start.py — команды /start, /menu, /help
    2. leagues.py — inline-навигация, кнопки меню
    """
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(start.router)
    dp.include_router(leagues.router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    return dp


async def main() -> None:
    """Основная функция запуска бота."""
    if not settings.bot_token or settings.bot_token == "your_bot_token_here":
        logger.error(
            "BOT_TOKEN не установлен!\n"
            "   Скопируйте .env.example в .env и укажите токен от @BotFather."
        )
        sys.exit(1)

    bot = create_bot()
    dp = create_dispatcher()

    try:
        logger.info("Запуск polling...")
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("Polling отменён")
    except Exception as e:
        logger.error("Критическая ошибка polling: %s", e, exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлено пользователем (Ctrl+C)")
    except Exception as e:
        logger.error("Необработанная ошибка: %s", e, exc_info=True)
        sys.exit(1)
