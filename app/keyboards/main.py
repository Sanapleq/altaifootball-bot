"""Клавиатуры главного меню и inline-навигации."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

from app.models.football import League, Team


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главная клавиатура (Reply)."""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🏆 Лиги"),
                KeyboardButton(text="🔍 Найти команду"),
            ],
            [
                KeyboardButton(text="📊 Турнирная таблица"),
                KeyboardButton(text="📅 Ближайшие матчи"),
            ],
            [
                KeyboardButton(text="🔥 Последние результаты"),
                KeyboardButton(text="📬 Мои подписки"),
            ],
            [
                KeyboardButton(text="❓ Помощь"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите раздел...",
    )
    return keyboard


def get_leagues_inline_keyboard(leagues: list[League]) -> InlineKeyboardMarkup:
    """Inline-клавиатура со списком лиг (фильтруется по сезону)."""
    buttons: list[list[InlineKeyboardButton]] = []
    for league in leagues:
        season_tag = f" ({league.season})" if league.season else ""
        buttons.append([
            InlineKeyboardButton(
                text=f"{league.name}{season_tag}",
                callback_data=f"league:{league.id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад к сезонам",
            callback_data="back_to_seasons"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_seasons_keyboard(seasons: list[str], current_year: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора сезонов.

    Структура:
    📅 Текущий сезон (YYYY)
    🗂 Выбрать сезон
    🕘 Архив
    ⬅️ Назад
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"📅 Текущий сезон ({current_year})",
                callback_data=f"season_current:{current_year}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="🗂 Выбрать сезон",
                callback_data="season_list:all"
            ),
        ],
        [
            InlineKeyboardButton(
                text="🕘 Архив",
                callback_data="season_list:archive"
            ),
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="back_to_main"
            ),
        ],
    ])


def get_seasons_list_keyboard(seasons: list[str], mode: str) -> InlineKeyboardMarkup:
    """Клавиатура со списком конкретных сезонов.

    mode: 'all' — все сезоны, 'archive' — только архивные.
    """
    buttons: list[list[InlineKeyboardButton]] = []
    for season in seasons:
        buttons.append([
            InlineKeyboardButton(
                text=f"📆 {season}",
                callback_data=f"season_select:{season}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад к сезонам",
            callback_data="back_to_seasons"
        ),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_league_menu_keyboard(league: League) -> InlineKeyboardMarkup:
    """Меню выбранной лиги."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="👥 Команды",
                callback_data=f"league_teams:{league.id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="📊 Турнирная таблица",
                callback_data=f"league_standings:{league.id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="📅 Ближайшие матчи",
                callback_data=f"league_upcoming:{league.id}"
            ),
            InlineKeyboardButton(
                text="🔥 Результаты",
                callback_data=f"league_results:{league.id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="back_to_main"
            ),
        ],
    ])


def get_teams_keyboard(teams: list[Team], league_id: str, page: int = 0) -> InlineKeyboardMarkup:
    """Клавиатура со списком команд (с пагинацией)."""
    page_size = 10
    start = page * page_size
    end = start + page_size
    page_teams = teams[start:end]

    buttons: list[list[InlineKeyboardButton]] = []
    for team in page_teams:
        buttons.append([
            InlineKeyboardButton(
                text=team.name,
                callback_data=f"team:{team.id}"
            )
        ])

    # Пагинация
    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"teams_page:{league_id}:{page - 1}"
        ))
    if end < len(teams):
        nav_row.append(InlineKeyboardButton(
            text="Далее ➡️",
            callback_data=f"teams_page:{league_id}:{page + 1}"
        ))

    if nav_row:
        buttons.append(nav_row)

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ К лиге",
            callback_data=f"league_menu:{league_id}"
        ),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_team_menu_keyboard(team: Team, league_id: str, is_subscribed: bool = False) -> InlineKeyboardMarkup:
    """Меню команды.

    Кнопки:
      📅 Ближайшие   🗓 Расписание
      🔥 Результаты  📊 Таблица
      👥 Заявка      📈 Игроки
      🤖 Прогноз
      🔔 Подписаться
      ⬅️ Назад
    """
    sub_text = "✅ Отписаться" if is_subscribed else "🔔 Подписаться"

    buttons: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="📅 Ближайшие",
                callback_data=f"team_upcoming:{team.id}"
            ),
            InlineKeyboardButton(
                text="🗓 Расписание",
                callback_data=f"team_schedule:{team.id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="🔥 Результаты",
                callback_data=f"team_results:{team.id}"
            ),
            InlineKeyboardButton(
                text="📊 Таблица",
                callback_data=f"team_standing:{team.id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="👥 Заявка",
                callback_data=f"team_roster:{team.id}"
            ),
            InlineKeyboardButton(
                text="📈 Игроки",
                callback_data=f"team_player_stats:{team.id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="🤖 Прогноз",
                callback_data=f"team_prediction:{team.id}"
            ),
        ],
        [
            InlineKeyboardButton(text=sub_text, callback_data=f"team_subscribe:{team.id}"),
        ],
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="back_to_main"
            ),
        ],
    ]

    if league_id:
        buttons.insert(-1, [
            InlineKeyboardButton(
                text="⬅️ К командам",
                callback_data=f"league_teams:{league_id}"
            ),
            InlineKeyboardButton(
                text="⬅️ К лиге",
                callback_data=f"league_menu:{league_id}"
            ),
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_search_results_keyboard(teams: list[Team]) -> InlineKeyboardMarkup:
    """Клавиатура результатов поиска."""
    buttons: list[list[InlineKeyboardButton]] = []
    for team in teams[:10]:
        buttons.append([
            InlineKeyboardButton(
                text=team.name,
                callback_data=f"team:{team.id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="back_to_main"
        ),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_subscriptions_keyboard(subscriptions: list[dict]) -> InlineKeyboardMarkup:
    """Клавиатура подписок."""
    buttons: list[list[InlineKeyboardButton]] = []
    for sub in subscriptions[:10]:
        buttons.append([
            InlineKeyboardButton(
                text=f"⚽ {sub['team_name']}",
                callback_data=f"team:{sub['team_id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="back_to_main"
        ),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_main_back_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с переходом в главное меню."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🏠 Главное меню",
            callback_data="back_to_main"
        )],
    ])


def get_team_back_keyboard(league_id: str) -> InlineKeyboardMarkup:
    """Клавиатура «Назад» для экранов команды (расписание, результаты, ближайшие).

    Кнопки:
      ⬅️ Назад к команде  |  🏠 Главное меню
      [+ ⬅️ К лиге]
    """
    buttons: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="⬅️ Назад к команде",
                callback_data="back_to_team"
            ),
            InlineKeyboardButton(
                text="🏠 Главное меню",
                callback_data="back_to_main"
            ),
        ],
    ]

    if league_id:
        buttons.append([
            InlineKeyboardButton(
                text="⬅️ К лиге",
                callback_data=f"league_menu:{league_id}"
            ),
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
