"""Конфигурация pytest и фикстуры."""

import pytest

from app.repositories.subscription_repo import SubscriptionRepository
from app.repositories.user_repo import UserRepository


@pytest.fixture
def user_repo(tmp_path) -> UserRepository:
    """Репозиторий пользователей во временной БД."""
    db_path = str(tmp_path / "test_users.db")
    return UserRepository(db_path=db_path)


@pytest.fixture
def sub_repo(tmp_path) -> SubscriptionRepository:
    """Репозиторий подписок во временной БД."""
    db_path = str(tmp_path / "test_subs.db")
    return SubscriptionRepository(db_path=db_path)
