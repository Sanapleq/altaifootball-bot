"""Обработчик команд /start, /menu, /help и главного меню.

Обрабатывает:
- /start — приветствие + главное меню
- /menu — возврат в главное меню
- /help — справка
- /leagues — быстрый переход к лигам
- /search — поиск команды
- /subscriptions — список подписок
- Текстовые кнопки главного меню
"""

from __future__ import annotations

import app.dependencies as deps
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.keyboards.main import (
    get_leagues_inline_keyboard,
    get_main_keyboard,
    get_subscriptions_keyboard,
)
from app.logger import logger
from app.services.formatter import FootballFormatter
from app.states import MainStates, SearchStates

router = Router()


# ── Команды ────────────────────────────────────────────────────────


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Обработка команды /start."""
    await state.set_state(MainStates.idle)
    await message.answer(
        "⚽ <b>Добро пожаловать в Football Bot!</b>\n\n"
        "Я помогу вам следить за футбольными лигами и командами "
        "с сайта <b>altaifootball.ru</b>.\n\n"
        "Используйте кнопки ниже для навигации или отправьте /help для справки.",
        reply_markup=get_main_keyboard(),
    )
    logger.info("Пользователь %s запустил бота", message.from_user.id)


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    """Обработка команды /menu."""
    await state.set_state(MainStates.idle)
    await state.clear()
    await message.answer(
        "🏠 <b>Главное меню</b>",
        reply_markup=get_main_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Обработка команды /help."""
    await message.answer(
        "❓ <b>Справка</b>\n\n"
        "Этот бот показывает данные с сайта altaifootball.ru.\n\n"
        "📋 <b>Команды:</b>\n"
        "/start — Запустить бота\n"
        "/menu — Главное меню\n"
        "/help — Эта справка\n"
        "/leagues — Список лиг\n"
        "/search — Поиск команды\n"
        "/subscriptions — Мои подписки\n\n"
        "🖱 <b>Кнопки меню:</b>\n"
        "🏆 <b>Лиги</b> — выбрать лигу и смотреть её данные\n"
        "🔍 <b>Найти команду</b> — поиск по названию\n"
        "📊 <b>Турнирная таблица</b> — таблица выбранной лиги\n"
        "📅 <b>Ближайшие матчи</b> — расписание выбранной лиги\n"
        "🔥 <b>Последние результаты</b> — завершённые матчи\n"
        "📬 <b>Мои подписки</b> — отслеживаемые команды\n"
        "❓ <b>Помощь</b> — эта справка\n\n"
        "💡 <b>Совет:</b> начните с раздела «Лиги»."
    )


@router.message(Command("leagues"))
async def cmd_leagues(message: Message) -> None:
    """Обработка команды /leagues."""
    await message.answer("⏳ Загрузка списка лиг...")

    leagues_list = await deps.football_service.get_leagues()

    if not leagues_list:
        await message.answer(
            "😔 Не удалось загрузить список лиг.\n"
            "Проверьте доступность сайта и попробуйте позже.",
            reply_markup=get_main_keyboard(),
        )
        return

    await message.answer(
        FootballFormatter.format_leagues_list(leagues_list),
        reply_markup=get_leagues_inline_keyboard(leagues_list),
    )


@router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext) -> None:
    """Обработка команды /search."""
    await state.set_state(SearchStates.waiting_for_query)
    await message.answer(
        "🔍 <b>Поиск команды</b>\n\n"
        "Введите название команды (частичное совпадение работает):"
    )


@router.message(Command("subscriptions"))
async def cmd_subscriptions(message: Message) -> None:
    """Обработка команды /subscriptions."""
    subscriptions = await deps.sub_repo.get_user_subscriptions(message.from_user.id)

    if not subscriptions:
        await message.answer(
            "📬 <b>Мои подписки</b>\n\n"
            "У вас пока нет подписок.\n"
            "Выберите команду через «Лиги» и нажмите «Подписаться».",
            reply_markup=get_main_keyboard(),
        )
    else:
        await message.answer(
            FootballFormatter.format_subscriptions(subscriptions),
            reply_markup=get_subscriptions_keyboard(subscriptions),
        )


# ── Текстовые кнопки главного меню ─────────────────────────────────


@router.message(F.text == "🔍 Найти команду")
async def handle_search_button(message: Message, state: FSMContext) -> None:
    """Кнопка «Найти команду»."""
    await state.set_state(SearchStates.waiting_for_query)
    await message.answer(
        "🔍 <b>Поиск команды</b>\n\n"
        "Введите название команды (или часть названия):"
    )


# Тексты кнопок главного меню — fallback не должен их перехватывать,
# т.к. их обрабатывают хендлеры в leagues.py (и start.py).
_MENU_BUTTON_TEXTS = {
    "🏆 Лиги",
    "🔍 Найти команду",
    "📊 Турнирная таблица",
    "📅 Ближайшие матчи",
    "🔥 Последние результаты",
    "📬 Мои подписки",
    "❓ Помощь",
}


@router.message(F.text == "❓ Помощь")
async def handle_help_button(message: Message) -> None:
    """Кнопка «Помощь»."""
    await cmd_help(message)


@router.message(MainStates.idle, ~F.text.in_(_MENU_BUTTON_TEXTS))
async def handle_unknown_text(message: Message) -> None:
    """Fallback — неизвестная команда в idle-состоянии.

    Не срабатывает на тексты кнопок главного меню — их обрабатывают
    специализированные хендлеры (в start.py и leagues.py).
    """
    await message.answer(
        "Неизвестная команда. Используйте кнопки ниже:",
        reply_markup=get_main_keyboard(),
    )
