"""Настройка логирования."""

import logging
import sys

from app.config import settings


def setup_logger(name: str = "altaifootball_bot") -> logging.Logger:
    """Настроить и вернуть логгер.

    Args:
        name: Имя логгера.

    Returns:
        Настроенный экземпляр logging.Logger.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    # Уровень логирования из настроек
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger.setLevel(level)

    # Формат сообщений
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Вывод в stdout
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


# Глобальный логгер по умолчанию
logger = setup_logger()
