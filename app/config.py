"""Конфигурация приложения."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Загружаем .env файл
load_dotenv()


class Settings(BaseSettings):
    """Настройки приложения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram
    bot_token: str = Field(default="", alias="BOT_TOKEN")

    # Сайт
    base_url: str = Field(default="https://altaifootball.ru", alias="BASE_URL")

    # HTTP
    request_timeout: int = Field(default=30, alias="REQUEST_TIMEOUT")

    # Логирование
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # База данных
    db_path: str = Field(default="data/bot.db", alias="DB_PATH")


# Глобальный экземпляр настроек
settings = Settings()


def ensure_dirs() -> None:
    """Создать необходимые директории если их нет."""
    db_dir = Path(settings.db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)
