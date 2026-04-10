"""Обработчики для лиг, команд и действий с ними.

Основной модуль — вся логика inline-навигации:
  лиги → команды → матчи → подписки → таблицы.
"""

from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

import app.dependencies as deps
from app.keyboards.callbacks import parse_callback, parse_callback_multi
from app.keyboards.main import (
    get_league_menu_keyboard,
    get_leagues_inline_keyboard,
    get_main_back_keyboard,
    get_main_keyboard,
    get_search_results_keyboard,
    get_seasons_keyboard,
    get_seasons_list_keyboard,
    get_subscriptions_keyboard,
    get_team_back_keyboard,
    get_team_menu_keyboard,
    get_teams_keyboard,
)
from app.logger import logger
from app.models.football import League, Team
from app.services.formatter import FootballFormatter
from app.states import MainStates, SearchStates
from app.utils.text import escape_html

router = Router()


# ── Хелперы ────────────────────────────────────────────────────────


async def _safe_edit_text(callback: CallbackQuery, text: str, **kwargs) -> None:
    """Безопасно отредактировать сообщение callback.

    Если сообщение нельзя отредактировать (слишком длинное, не наше
    и т.д.) — отправляем новое сообщение.
    """
    try:
        await callback.message.edit_text(text, **kwargs)
    except Exception as e:
        logger.debug("[_safe_edit_text] fallback to answer: %s", e)
        # Не удалось отредактировать — шлём новое
        await callback.message.answer(text, **kwargs)


async def _find_team_by_id(team_id: str) -> Team | None:
    """Найти команду по ID через все доступные лиги.

    ⚠️  Делает N HTTP-запросов (по одному на лигу).
        Вызывается ТОЛЬКО как последний fallback.
    """
    leagues_list = await deps.football_service.get_leagues()
    logger.debug(
        "[_find_team_by_id] Старт: %d лиг, ищем team_id=%s",
        len(leagues_list), team_id,
    )
    found_count = 0
    for league in leagues_list:
        try:
            teams = await deps.football_service.get_league_teams(league)
            for t in teams:
                if t.id == team_id:
                    logger.info(
                        "[_find_team_by_id] Команда '%s' найдена в лиге '%s'",
                        t.name, league.name,
                    )
                    return t
            found_count += len(teams)
        except Exception as e:
            logger.debug(
                "[_find_team_by_id] Ошибка загрузки команд лиги '%s': %s",
                league.name, e,
            )
    logger.debug(
        "[_find_team_by_id] Итог: team_id=%s не найдена "
        "(проверено %d лиг, %d команд)",
        team_id, len(leagues_list), found_count,
    )
    return None


async def _find_league_for_team(team_id: str) -> League | None:
    """Найти лигу, в которой играет команда с данным ID."""
    leagues_list = await deps.football_service.get_leagues()
    logger.debug(
        "[_find_league_for_team] Старт: %d лиг, ищем team_id=%s",
        len(leagues_list), team_id,
    )
    found_count = 0
    for league in leagues_list:
        try:
            teams = await deps.football_service.get_league_teams(league)
            for t in teams:
                if t.id == team_id:
                    logger.info(
                        "[_find_league_for_team] Лига '%s' найдена для команды '%s'",
                        league.name, t.name,
                    )
                    return league
            found_count += len(teams)
        except Exception as e:
            logger.debug(
                "[_find_league_for_team] Ошибка загрузки команд лиги '%s': %s",
                league.name, e,
            )
    logger.debug(
        "[_find_league_for_team] Итог: лига для team_id=%s не найдена "
        "(проверено %d лиг, %d команд)",
        team_id, len(leagues_list), found_count,
    )
    return None


async def _get_team_from_state_or_search(
    team_id: str, state: FSMContext
) -> Team | None:
    """Получить команду по ID.

    Логика (по приоритету):
    1. Если selected_team в state и ID совпадает — берём из кэша.
    2. Если teams_list в state — ищем там (один запрос не нужен).
    3. Если selected_league_id есть — ищем только в этой лиге.
    4. Fallback: ищем через все лиги (тяжёлый).
    """
    state_data = await state.get_data()
    team: Team | None = state_data.get("selected_team")

    # 1. Кэшированная команда совпадает — возвращаем сразу
    if team is not None and team.id == team_id:
        return team

    # 2. Ищем в кэшированном списке команд (быстро, без запросов)
    teams_list: list[Team] = state_data.get("teams_list", [])
    for t in teams_list:
        if t.id == team_id:
            return t

    # 3. Пробуем найти в сохранённой лиге (один запрос вместо N)
    league_id = state_data.get("selected_league_id")
    if league_id:
        league = await deps.football_service.get_league_by_id(league_id)
        if league:
            try:
                teams = await deps.football_service.get_league_teams(league)
                for t in teams:
                    if t.id == team_id:
                        return t
            except Exception as e:
                logger.debug(
                    "[_get_team_from_state_or_search] Ошибка загрузки команд лиги '%s': %s",
                    league.name, e,
                )

    # 4. Fallback: сканируем все лиги (тяжёлый)
    return await _find_team_by_id(team_id)


def _get_team_back_kb(team: Team | None) -> InlineKeyboardMarkup:
    """Клавиатура «Назад» для экранов команды.

    Берёт league_id из team.league_id и показывает:
      «⬅️ Назад к команде»  |  «🏠 Главное меню»
    [+ «⬅️ К лиге» если league_id известен]
    """
    league_id = team.league_id if team else ""
    return get_team_back_keyboard(league_id or "")


@router.callback_query(F.data == "back_to_team")
async def cb_back_to_team(callback: CallbackQuery, state: FSMContext) -> None:
    """Вернуться к карточке текущей команды."""
    state_data = await state.get_data()
    team: Team | None = state_data.get("selected_team")
    league_id = state_data.get("selected_league_id", "")

    if team is None:
        await callback.answer("Команда не найдена в кэше", show_alert=True)
        return

    is_subscribed = await deps.sub_repo.is_subscribed(callback.from_user.id, team.id)
    standing = await deps.football_service.get_team_position_in_table(team)

    await _safe_edit_text(
        callback,
        FootballFormatter.format_team_card(team, standing),
        reply_markup=get_team_menu_keyboard(team, league_id or "", is_subscribed),
    )
    await callback.answer()


# ── Навигация: главное меню ────────────────────────────────────────


@router.callback_query(F.data == "back_to_main")
async def cb_back_to_main(callback: CallbackQuery, state: FSMContext) -> None:
    """Вернуться в главное меню.

    Важно: ReplyKeyboardMarkup нельзя установить через edit_text,
    поэтому отвечаем новым сообщением.
    """
    await state.set_state(MainStates.idle)
    await state.clear()
    # Отправляем новое сообщение с reply-клавиатурой
    await callback.message.answer(
        "🏠 <b>Главное меню</b>",
        reply_markup=get_main_keyboard(),
    )
    # Помечаем исходное inline-сообщение как обработанное
    await callback.answer()


# ── Сезоны ─────────────────────────────────────────────────────────


@router.callback_query(F.data == "back_to_seasons")
async def cb_back_to_seasons(callback: CallbackQuery, state: FSMContext) -> None:
    """Вернуться к выбору сезонов."""
    from datetime import datetime
    current_year = str(datetime.now().year)

    await state.set_state(MainStates.viewing_leagues)
    await _safe_edit_text(
        callback,
        "⚽ <b>Выберите сезон</b>\n\n"
        "📅 Текущий сезон — активные турниры\n"
        "🗂 Выбрать сезон — все доступные сезоны\n"
        "🕘 Архив — прошлые сезоны",
        reply_markup=get_seasons_keyboard([], current_year),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("season_current:"))
async def cb_season_current(callback: CallbackQuery, state: FSMContext) -> None:
    """Показать турниры текущего сезона."""
    from datetime import datetime
    current_year = str(datetime.now().year)

    await callback.message.edit_text("⏳ Загрузка турниров текущего сезона...")

    leagues = await deps.football_service.get_current_season_leagues()
    if not leagues:
        await callback.message.answer(
            f"😔 Не найдено турниров за {current_year}.\n"
            "Попробуйте выбрать другой сезон.",
            reply_markup=get_seasons_keyboard([], current_year),
        )
        await callback.answer()
        return

    await state.update_data(selected_season=current_year)
    await state.set_state(MainStates.viewing_leagues)

    await _safe_edit_text(
        callback,
        FootballFormatter.format_leagues_list(leagues, f"Текущий сезон {current_year}"),
        reply_markup=get_leagues_inline_keyboard(leagues),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("season_list:"))
async def cb_season_list(callback: CallbackQuery, state: FSMContext) -> None:
    """Показать список всех сезонов или архив."""
    _, mode = parse_callback(callback.data)

    await callback.message.edit_text("⏳ Загрузка списка сезонов...")

    if mode == "archive":
        seasons = await deps.football_service.get_archive_seasons()
        title = "🕘 Архив сезонов"
    else:
        seasons = await deps.football_service.get_available_seasons()
        title = "🗂 Все сезоны"

    if not seasons:
        await callback.message.answer(
            "😔 Не удалось загрузить список сезонов.",
            reply_markup=get_seasons_keyboard([], "2026"),
        )
        await callback.answer()
        return

    await _safe_edit_text(
        callback,
        f"<b>{title}</b>\n\nДоступно сезонов: {len(seasons)}",
        reply_markup=get_seasons_list_keyboard(seasons, mode),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("season_select:"))
async def cb_season_select(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбрать конкретный сезон."""
    _, season = parse_callback(callback.data)

    await callback.message.edit_text(f"⏳ Загрузка турниров за {season}...")

    leagues = await deps.football_service.get_leagues_by_season(season)
    if not leagues:
        await callback.message.answer(
            f"😔 Не найдено турниров за {season}.",
            reply_markup=get_seasons_list_keyboard([], "all"),
        )
        await callback.answer()
        return

    await state.update_data(selected_season=season)
    await state.set_state(MainStates.viewing_leagues)

    await _safe_edit_text(
        callback,
        FootballFormatter.format_leagues_list(leagues, f"Сезон {season}"),
        reply_markup=get_leagues_inline_keyboard(leagues),
    )
    await callback.answer()


# ── Лиги ───────────────────────────────────────────────────────────


@router.message(F.text == "🏆 Лиги")
async def show_leagues_from_menu(message: Message, state: FSMContext) -> None:
    """Показать меню выбора сезонов из текстовой кнопки."""
    from datetime import datetime
    current_year = str(datetime.now().year)

    await state.set_state(MainStates.viewing_leagues)
    await message.answer(
        "⚽ <b>Выберите сезон</b>\n\n"
        "📅 <b>Текущий сезон</b> — активные турниры\n"
        "🗂 <b>Выбрать сезон</b> — все доступные сезоны\n"
        "🕘 <b>Архив</b> — прошлые сезоны",
        reply_markup=get_seasons_keyboard([], current_year),
    )


@router.callback_query(F.data.startswith("league:"))
async def cb_select_league(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбрать лигу."""
    _, league_id = parse_callback(callback.data)
    league = await deps.football_service.get_league_by_id(league_id)

    if league is None:
        await callback.answer("Лига не найдена", show_alert=True)
        return

    await deps.user_repo.set_selected_league(
        callback.from_user.id, league.id, league.name
    )
    await state.update_data(selected_league_id=league.id, selected_league=league)
    await state.set_state(MainStates.viewing_league)

    await _safe_edit_text(
        callback,
        FootballFormatter.format_league_menu(league),
        reply_markup=get_league_menu_keyboard(league),
    )
    await callback.answer()
    logger.info("Пользователь %s выбрал лигу: %s", callback.from_user.id, league.name)


@router.callback_query(F.data.startswith("league_menu:"))
async def cb_league_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Меню лиги (кнопка «Назад к лиге»)."""
    _, league_id = parse_callback(callback.data)
    league = await deps.football_service.get_league_by_id(league_id)

    if league is None:
        await callback.answer("Лига не найдена", show_alert=True)
        return

    await state.update_data(selected_league_id=league.id, selected_league=league)
    await state.set_state(MainStates.viewing_league)

    await _safe_edit_text(
        callback,
        FootballFormatter.format_league_menu(league),
        reply_markup=get_league_menu_keyboard(league),
    )
    await callback.answer()


# ── Команды в лиге ─────────────────────────────────────────────────


@router.callback_query(F.data.startswith("league_teams:"))
async def cb_league_teams(callback: CallbackQuery, state: FSMContext) -> None:
    """Показать команды выбранной лиги."""
    _, league_id = parse_callback(callback.data)

    await callback.message.edit_text("⏳ Загрузка команд...")

    league = await deps.football_service.get_league_by_id(league_id)
    if league is None:
        await message_answer_fallback(callback, "😔 Лига не найдена.")
        return

    teams = await deps.football_service.get_league_teams(league)
    if not teams:
        await callback.message.answer(
            f"😔 Не удалось загрузить команды лиги <b>{league.name}</b>.",
            reply_markup=get_league_menu_keyboard(league),
        )
        await callback.answer()
        return

    await state.update_data(
        selected_league_id=league.id,
        selected_league=league,
        teams_list=teams,
    )
    await state.set_state(MainStates.viewing_teams)

    await _safe_edit_text(
        callback,
        FootballFormatter.format_teams_list(teams, league.name),
        reply_markup=get_teams_keyboard(teams, league.id, page=0),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("teams_page:"))
async def cb_teams_page(callback: CallbackQuery, state: FSMContext) -> None:
    """Пагинация списка команд."""
    parts = parse_callback_multi(callback.data)
    if len(parts) < 3:
        await callback.answer("Некорректные данные пагинации", show_alert=True)
        return
    league_id = parts[1]
    try:
        page = int(parts[2])
    except ValueError:
        await callback.answer("Некорректный номер страницы", show_alert=True)
        return

    state_data = await state.get_data()
    teams: list[Team] = state_data.get("teams_list", [])

    league = await deps.football_service.get_league_by_id(league_id)
    if league is None:
        await callback.answer("Лига не найдена", show_alert=True)
        return

    await _safe_edit_text(
        callback,
        FootballFormatter.format_teams_list(teams, league.name),
        reply_markup=get_teams_keyboard(teams, league.id, page=page),
    )
    await callback.answer()


# ── Команда — карточка ─────────────────────────────────────────────


@router.callback_query(F.data.startswith("team:"))
async def cb_select_team(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбрать команду — показать карточку."""
    _, team_id = parse_callback(callback.data)

    await callback.message.edit_text("⏳ Загрузка данных команды...")

    state_data = await state.get_data()
    teams_list: list[Team] = state_data.get("teams_list", [])

    team: Team | None = None
    for t in teams_list:
        if t.id == team_id:
            team = t
            break

    if team is None:
        # Пробуем реконструировать URL команды из league_id, не сканируя все лиги
        league_id = state_data.get("selected_league_id")
        if league_id:
            league = await deps.football_service.get_league_by_id(league_id)
            if league:
                teams = await deps.football_service.get_league_teams(league)
                for t in teams:
                    if t.id == team_id:
                        team = t
                        teams_list = teams
                        break

        # Только если не нашли — сканируем все лиги (редкий fallback)
        if team is None:
            logger.debug("Команда %s не найдена в кэше, пробую поиск по всем лигам", team_id)
            team = await _find_team_by_id(team_id)

    if team is None:
        await callback.message.answer(
            "😔 Команда не найдена.\n"
            "Возможно, структура сайта изменилась — попробуйте позже."
        )
        await callback.answer()
        return

    league_id = team.league_id or state_data.get("selected_league_id", "")
    is_subscribed = await deps.sub_repo.is_subscribed(callback.from_user.id, team.id)

    await deps.user_repo.set_selected_team(callback.from_user.id, team.id, team.name)
    await state.update_data(
        selected_team_id=team.id,
        selected_team=team,
        teams_list=teams_list,
    )
    await state.set_state(MainStates.viewing_team)

    # Получаем название лиги для карточки
    league_name = None
    if league_id:
        league = await deps.football_service.get_league_by_id(league_id)
        if league:
            league_name = league.name

    standing = await deps.football_service.get_team_position_in_table(team)

    await _safe_edit_text(
        callback,
        FootballFormatter.format_team_card(team, standing, league_name=league_name),
        reply_markup=get_team_menu_keyboard(team, league_id or "", is_subscribed),
    )
    await callback.answer()
    logger.info(
        "Пользователь %s открыл команду: %s", callback.from_user.id, team.name
    )


# ── Меню команды — действия ────────────────────────────────────────


@router.callback_query(F.data.startswith("team_schedule:"))
async def cb_team_schedule(callback: CallbackQuery, state: FSMContext) -> None:
    """Полное расписание команды."""
    _, team_id = parse_callback(callback.data)
    await callback.message.edit_text("⏳ Загрузка расписания...")

    team = await _get_team_from_state_or_search(team_id, state)
    if team is None:
        await message_answer_fallback(callback, "😔 Не удалось найти команду.")
        return

    matches = await deps.football_service.get_team_matches(team)
    if not matches:
        await callback.message.answer(
            f"🗓 <b>Расписание</b>\n{escape_html(team.name)}\n\n"
            "Матчей пока нет или не удалось загрузить данные.",
            reply_markup=_get_team_back_kb(team),
        )
        await callback.answer()
        return

    # Расписание — все матчи, хронологически, с секциями
    all_sorted = sorted(matches, key=lambda m: m.match_date or datetime.max)
    await _safe_edit_text(
        callback,
        FootballFormatter.format_matches_list(
            all_sorted,
            title="🗓 Расписание",
            team_name=team.name,
            max_count=20,
            show_sections=True,
        ),
        reply_markup=_get_team_back_kb(team),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("team_upcoming:"))
async def cb_team_upcoming(callback: CallbackQuery, state: FSMContext) -> None:
    """Ближайшие матчи команды."""
    _, team_id = parse_callback(callback.data)
    await callback.message.edit_text("⏳ Загрузка ближайших матчей...")

    team = await _get_team_from_state_or_search(team_id, state)
    if team is None:
        await message_answer_fallback(callback, "😔 Не удалось найти команду.")
        return

    matches = await deps.football_service.get_team_upcoming_matches(team)
    if not matches:
        await callback.message.answer(
            f"📅 <b>Ближайшие матчи</b>\n{escape_html(team.name)}\n\n"
            "Предстоящих матчей пока нет.",
            reply_markup=_get_team_back_kb(team),
        )
        await callback.answer()
        return

    # Ближайшие — плоский список, без секций
    await _safe_edit_text(
        callback,
        FootballFormatter.format_matches_list(
            matches,
            title="📅 Ближайшие матчи",
            team_name=team.name,
            max_count=15,
            show_sections=False,
        ),
        reply_markup=_get_team_back_kb(team),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("team_results:"))
async def cb_team_results(callback: CallbackQuery, state: FSMContext) -> None:
    """Последние результаты команды."""
    _, team_id = parse_callback(callback.data)
    await callback.message.edit_text("⏳ Загрузка результатов...")

    team = await _get_team_from_state_or_search(team_id, state)
    if team is None:
        await message_answer_fallback(callback, "😔 Не удалось найти команду.")
        return

    results = await deps.football_service.get_team_recent_results(team)
    if not results:
        await callback.message.answer(
            f"🔥 <b>Последние результаты</b>\n{escape_html(team.name)}\n\n"
            "Завершённых матчей пока нет.",
            reply_markup=_get_team_back_kb(team),
        )
        await callback.answer()
        return

    # Результаты — плоский список, без секций
    await _safe_edit_text(
        callback,
        FootballFormatter.format_matches_list(
            results,
            title="🔥 Последние результаты",
            team_name=team.name,
            max_count=15,
            show_sections=False,
        ),
        reply_markup=_get_team_back_kb(team),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("team_standing:"))
async def cb_team_standing(callback: CallbackQuery, state: FSMContext) -> None:
    """Позиция команды в турнирной таблице."""
    _, team_id = parse_callback(callback.data)
    await callback.message.edit_text("⏳ Загрузка таблицы...")

    team = await _get_team_from_state_or_search(team_id, state)
    if team is None:
        await message_answer_fallback(callback, "😔 Не удалось найти команду.")
        return

    # Определяем лигу
    league: League | None = None
    if team.league_id:
        league = await deps.football_service.get_league_by_id(team.league_id)

    if league is None:
        league = await _find_league_for_team(team_id)

    if league is None:
        await callback.message.answer(
            "😔 Не удалось определить лигу команды.\n"
            "Попробуйте выбрать команду через раздел «Лиги»."
        )
        await callback.answer()
        return

    standings = await deps.football_service.get_league_standings(league)
    team_standing = None
    for row in standings:
        if row.team_name.lower() == team.name.lower():
            team_standing = row
            break

    if team_standing:
        text = FootballFormatter.format_standings(
            standings, league.name, highlight_team=team.name
        )
    else:
        text = (
            f"😔 Не удалось найти <b>{team.name}</b> "
            f"в таблице лиги {league.name}."
        )

    await _safe_edit_text(
        callback, text, reply_markup=_get_team_back_kb(team)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("team_subscribe:"))
async def cb_team_subscribe(callback: CallbackQuery, state: FSMContext) -> None:
    """Подписаться / отписаться от команды."""
    _, team_id = parse_callback(callback.data)

    team = await _get_team_from_state_or_search(team_id, state)
    if team is None:
        await callback.answer("Команда не найдена", show_alert=True)
        return

    is_subscribed = await deps.sub_repo.is_subscribed(callback.from_user.id, team.id)

    if is_subscribed:
        await deps.sub_repo.unsubscribe(callback.from_user.id, team.id)
        await callback.answer(f"Вы отписались от {team.name}", show_alert=False)
    else:
        league_name = ""
        if team.league_id:
            league = await deps.football_service.get_league_by_id(team.league_id)
            league_name = league.name if league else ""

        await deps.sub_repo.subscribe(
            callback.from_user.id, team.id, team.name, team.league_id, league_name
        )
        await callback.answer(f"Вы подписались на {team.name} 🔔", show_alert=False)

    # Обновляем клавиатуру
    league_id = team.league_id or ""
    await callback.message.edit_reply_markup(
        reply_markup=get_team_menu_keyboard(team, league_id, not is_subscribed)
    )


# ── Действия с лигой ───────────────────────────────────────────────


@router.callback_query(F.data.startswith("league_standings:"))
async def cb_league_standings(callback: CallbackQuery) -> None:
    """Турнирная таблица лиги."""
    _, league_id = parse_callback(callback.data)
    await callback.message.edit_text("⏳ Загрузка турнирной таблицы...")

    league = await deps.football_service.get_league_by_id(league_id)
    if league is None:
        await message_answer_fallback(callback, "😔 Лига не найдена.")
        return

    standings = await deps.football_service.get_league_standings(league)
    await _safe_edit_text(
        callback,
        FootballFormatter.format_standings(standings, league.name),
        reply_markup=get_league_menu_keyboard(league),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("league_upcoming:"))
async def cb_league_upcoming(callback: CallbackQuery) -> None:
    """Ближайшие матчи лиги."""
    _, league_id = parse_callback(callback.data)
    await callback.message.edit_text("⏳ Загрузка ближайших матчей...")

    league = await deps.football_service.get_league_by_id(league_id)
    if league is None:
        await message_answer_fallback(callback, "😔 Лига не найдена.")
        return

    matches = await deps.football_service.get_league_upcoming_matches(league)
    await _safe_edit_text(
        callback,
        FootballFormatter.format_matches_list(
            matches, f"Ближайшие матчи: {league.name}"
        ),
        reply_markup=get_league_menu_keyboard(league),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("league_results:"))
async def cb_league_results(callback: CallbackQuery) -> None:
    """Последние результаты лиги."""
    _, league_id = parse_callback(callback.data)
    await callback.message.edit_text("⏳ Загрузка результатов...")

    league = await deps.football_service.get_league_by_id(league_id)
    if league is None:
        await message_answer_fallback(callback, "😔 Лига не найдена.")
        return

    results = await deps.football_service.get_league_recent_results(league)
    await _safe_edit_text(
        callback,
        FootballFormatter.format_matches_list(
            results, f"Последние результаты: {league.name}"
        ),
        reply_markup=get_league_menu_keyboard(league),
    )
    await callback.answer()


# ── Поиск ──────────────────────────────────────────────────────────

# Тексты кнопок главного меню.
# Если в режиме поиска пользователь нажимает одну из них —
# выходим из поиска и обрабатываем кнопку как обычную.
_MENU_BUTTONS = frozenset({
    "🏆 Лиги",
    "📊 Турнирная таблица",
    "📅 Ближайшие матчи",
    "🔥 Последние результаты",
    "📬 Мои подписки",
    "❓ Помощь",
    "🔍 Найти команду",
})


@router.message(SearchStates.waiting_for_query)
async def handle_search_query(message: Message, state: FSMContext) -> None:
    """Обработка поискового запроса.

    Если текст совпадает с кнопкой главного меню — выходим из режима
    поиска и делегируем обработку этой кнопке.
    """
    text = message.text.strip()

    # ── Кнопка меню — выходим из поиска ────────────────────────────
    if text in _MENU_BUTTONS:
        await state.set_state(MainStates.idle)
        # Делегируем: вызываем соответствующий обработчик вручную
        if text == "🏆 Лиги":
            await _menu_leagues(message, state)
        elif text == "📊 Турнирная таблица":
            await _menu_standings(message)
        elif text == "📅 Ближайшие матчи":
            await _menu_upcoming(message)
        elif text == "🔥 Последние результаты":
            await _menu_results(message)
        elif text == "📬 Мои подписки":
            await _menu_subscriptions(message)
        elif text == "❓ Помощь":
            await _menu_help(message)
        # "🔍 Найти команду" — просто выходим из поиска, пользователь
        # может нажать кнопку снова, чтобы войти в поиск повторно.
        return

    # ── Обычный поисковый запрос ───────────────────────────────────
    if len(text) < 2:
        await message.answer("Введите хотя бы 2 символа для поиска.")
        return

    await message.answer("⏳ Поиск...")

    teams = await deps.football_service.search_teams(text)
    if not teams:
        await message.answer(
            f"😔 По запросу «{text}» ничего не найдено.\n"
            "Попробуйте другое название.",
            reply_markup=get_main_keyboard(),
        )
        await state.set_state(MainStates.idle)
        return

    await message.answer(
        FootballFormatter.format_search_results(teams, text),
        reply_markup=get_search_results_keyboard(teams),
    )
    await state.update_data(teams_list=teams)
    await state.set_state(MainStates.idle)


# ── Мини-обработчики кнопок меню (вызываются из режима поиска) ─────


async def _menu_leagues(message: Message, state: FSMContext) -> None:
    """Показать лиги (перенаправление из режима поиска)."""
    await message.answer("⏳ Загрузка списка лиг...")
    leagues_list = await deps.football_service.get_leagues()
    if not leagues_list:
        await message.answer(
            "😔 Не удалось загрузить список лиг.\n"
            "Проверьте доступность сайта altaifootball.ru и попробуйте позже.",
            reply_markup=get_main_keyboard(),
        )
        return
    await message.answer(
        FootballFormatter.format_leagues_list(leagues_list),
        reply_markup=get_leagues_inline_keyboard(leagues_list),
    )
    await state.set_state(MainStates.viewing_leagues)


async def _menu_standings(message: Message) -> None:
    """Турнирная таблица (перенаправление из режима поиска)."""
    selected = await deps.user_repo.get_selected_league(message.from_user.id)
    if selected is None:
        await message.answer(
            "Сначала выберите лигу в разделе «🏆 Лиги».",
            reply_markup=get_main_keyboard(),
        )
        return
    league_id, _ = selected
    league = await deps.football_service.get_league_by_id(league_id)
    if league is None:
        await message.answer(
            "😔 Не удалось загрузить лигу.",
            reply_markup=get_main_keyboard(),
        )
        return
    standings = await deps.football_service.get_league_standings(league)
    await message.answer(
        FootballFormatter.format_standings(standings, league.name)
    )


async def _menu_upcoming(message: Message) -> None:
    """Ближайшие матчи (перенаправление из режима поиска)."""
    selected = await deps.user_repo.get_selected_league(message.from_user.id)
    if selected is None:
        await message.answer(
            "Сначала выберите лигу в разделе «🏆 Лиги».",
            reply_markup=get_main_keyboard(),
        )
        return
    league_id, _ = selected
    league = await deps.football_service.get_league_by_id(league_id)
    if league is None:
        await message.answer(
            "😔 Не удалось загрузить лигу.",
            reply_markup=get_main_keyboard(),
        )
        return
    matches = await deps.football_service.get_league_upcoming_matches(league)
    await message.answer(
        FootballFormatter.format_matches_list(
            matches, f"Ближайшие матчи: {league.name}"
        )
    )


async def _menu_results(message: Message) -> None:
    """Последние результаты (перенаправление из режима поиска)."""
    selected = await deps.user_repo.get_selected_league(message.from_user.id)
    if selected is None:
        await message.answer(
            "Сначала выберите лигу в разделе «🏆 Лиги».",
            reply_markup=get_main_keyboard(),
        )
        return
    league_id, _ = selected
    league = await deps.football_service.get_league_by_id(league_id)
    if league is None:
        await message.answer(
            "😔 Не удалось загрузить лигу.",
            reply_markup=get_main_keyboard(),
        )
        return
    results = await deps.football_service.get_league_recent_results(league)
    await message.answer(
        FootballFormatter.format_matches_list(
            results, f"Последние результаты: {league.name}"
        )
    )


async def _menu_subscriptions(message: Message) -> None:
    """Подписки (перенаправление из режима поиска)."""
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


async def _menu_help(message: Message) -> None:
    """Помощь (перенаправление из режима поиска)."""
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
        "💡 <b>Совет:</b> начните с раздела «Лиги»."
    )


# ── Подписки ───────────────────────────────────────────────────────


@router.message(F.text == "📬 Мои подписки")
async def show_subscriptions_from_menu(message: Message) -> None:
    """Показать подписки из текстовой кнопки."""
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


@router.callback_query(F.data == "show_subscriptions")
async def show_subscriptions_from_callback(callback: CallbackQuery) -> None:
    """Показать подписки из inline-кнопки."""
    subscriptions = await deps.sub_repo.get_user_subscriptions(callback.from_user.id)

    if not subscriptions:
        await callback.message.answer(
            "📬 <b>Мои подписки</b>\n\nУ вас пока нет подписок.",
            reply_markup=get_main_keyboard(),
        )
    else:
        await callback.message.answer(
            FootballFormatter.format_subscriptions(subscriptions),
            reply_markup=get_subscriptions_keyboard(subscriptions),
        )
    await callback.answer()


# ── Текстовые кнопки главного меню ─────────────────────────────────


@router.message(F.text == "📊 Турнирная таблица")
async def handle_standings_button(message: Message) -> None:
    """Кнопка «Турнирная таблица»."""
    selected = await deps.user_repo.get_selected_league(message.from_user.id)
    if selected is None:
        await message.answer(
            "Сначала выберите лигу в разделе «🏆 Лиги».",
            reply_markup=get_main_keyboard(),
        )
        return

    league_id, _league_name = selected
    league = await deps.football_service.get_league_by_id(league_id)
    if league is None:
        await message.answer(
            "😔 Не удалось загрузить лигу. Выберите заново.",
            reply_markup=get_main_keyboard(),
        )
        return

    standings = await deps.football_service.get_league_standings(league)
    await message.answer(
        FootballFormatter.format_standings(standings, league.name)
    )


@router.message(F.text == "📅 Ближайшие матчи")
async def handle_upcoming_button(message: Message) -> None:
    """Кнопка «Ближайшие матчи»."""
    selected = await deps.user_repo.get_selected_league(message.from_user.id)
    if selected is None:
        await message.answer(
            "Сначала выберите лигу в разделе «🏆 Лиги».",
            reply_markup=get_main_keyboard(),
        )
        return

    league_id, _ = selected
    league = await deps.football_service.get_league_by_id(league_id)
    if league is None:
        await message.answer(
            "😔 Не удалось загрузить лигу.",
            reply_markup=get_main_keyboard(),
        )
        return

    matches = await deps.football_service.get_league_upcoming_matches(league)
    await message.answer(
        FootballFormatter.format_matches_list(
            matches, f"Ближайшие матчи: {league.name}"
        )
    )


@router.message(F.text == "🔥 Последние результаты")
async def handle_results_button(message: Message) -> None:
    """Кнопка «Последние результаты»."""
    selected = await deps.user_repo.get_selected_league(message.from_user.id)
    if selected is None:
        await message.answer(
            "Сначала выберите лигу в разделе «🏆 Лиги».",
            reply_markup=get_main_keyboard(),
        )
        return

    league_id, _ = selected
    league = await deps.football_service.get_league_by_id(league_id)
    if league is None:
        await message.answer(
            "😔 Не удалось загрузить лигу.",
            reply_markup=get_main_keyboard(),
        )
        return

    results = await deps.football_service.get_league_recent_results(league)
    await message.answer(
        FootballFormatter.format_matches_list(
            results, f"Последние результаты: {league.name}"
        )
    )


# ── Заявка и статистика команды ────────────────────────────────────


@router.callback_query(F.data.startswith("team_roster:"))
async def cb_team_roster(callback: CallbackQuery, state: FSMContext) -> None:
    """Заявка команды."""
    _, team_id = parse_callback(callback.data)
    await callback.message.edit_text("⏳ Загрузка заявки...")

    team = await _get_team_from_state_or_search(team_id, state)
    if team is None:
        await message_answer_fallback(callback, "😔 Не удалось найти команду.")
        return

    roster = await deps.football_service.get_team_roster(team)

    # Определяем название лиги для отображения
    league_name = None
    if team.league_id:
        league = await deps.football_service.get_league_by_id(team.league_id)
        if league:
            league_name = league.name

    await _safe_edit_text(
        callback,
        FootballFormatter.format_team_roster(roster, team.name),
        reply_markup=get_team_back_keyboard(team.league_id or ""),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("team_player_stats:"))
async def cb_team_player_stats(callback: CallbackQuery, state: FSMContext) -> None:
    """Статистика игроков команды."""
    _, team_id = parse_callback(callback.data)
    await callback.message.edit_text("⏳ Загрузка статистики игроков...")

    team = await _get_team_from_state_or_search(team_id, state)
    if team is None:
        await message_answer_fallback(callback, "😔 Не удалось найти команду.")
        return

    player_stats = await deps.football_service.get_team_player_stats(team)

    await _safe_edit_text(
        callback,
        FootballFormatter.format_team_player_stats(player_stats, team.name),
        reply_markup=get_team_back_keyboard(team.league_id or ""),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("team_prediction:"))
async def cb_team_prediction(callback: CallbackQuery, state: FSMContext) -> None:
    """Прогноз на ближайший матч команды."""
    _, team_id = parse_callback(callback.data)
    await callback.message.edit_text("⏳ Анализ формы команд...")

    team = await _get_team_from_state_or_search(team_id, state)
    if team is None:
        await message_answer_fallback(callback, "😔 Не удалось найти команду.")
        return

    prediction = await deps.football_service.get_team_match_prediction(team)
    if prediction is None:
        await callback.message.answer(
            f"🤖 <b>Прогноз</b>\n{escape_html(team.name)}\n\n"
            "😔 Не удалось составить прогноз:\n"
            "нет предстоящих матчей или недостаточно данных.",
            reply_markup=get_team_back_keyboard(team.league_id or ""),
        )
        await callback.answer()
        return

    await _safe_edit_text(
        callback,
        FootballFormatter.format_match_prediction(prediction),
        reply_markup=get_team_back_keyboard(team.league_id or ""),
    )
    await callback.answer()


# ── Утилиты ────────────────────────────────────────────────────────


async def message_answer_fallback(callback: CallbackQuery, text: str) -> None:
    """Ответить на callback сообщением (когда edit_text не подходит)."""
    await callback.message.answer(text)
    await callback.answer()
