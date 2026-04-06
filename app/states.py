"""FSM состояния для бота."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class MainStates(StatesGroup):
    """Состояния главного меню."""
    idle = State()           # Бездействие
    viewing_leagues = State()  # Просмотр лиг
    viewing_league = State()   # Просмотр конкретной лиги
    viewing_teams = State()    # Просмотр команд
    viewing_team = State()     # Просмотр команды
    searching = State()        # Поиск команды
    viewing_standings = State()  # Просмотр таблицы
    viewing_matches = State()    # Просмотр матчей
    viewing_subscriptions = State()  # Просмотр подписок


class SearchStates(StatesGroup):
    """Состояния поиска."""
    waiting_for_query = State()
