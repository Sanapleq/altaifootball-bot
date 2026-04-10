# ⚽ Altaifootball Telegram Bot

Telegram-бот для просмотра футбольных данных с сайта **altaifootball.ru**.
Показывает лиги, команды, турнирные таблицы, расписание матчей, заявки и статистику игроков.

## Возможности

- 📅 **Выбор сезона** — текущий сезон, выбор сезона, архив
- 🏆 **Просмотр лиг** — список турниров выбранного сезона
- 👥 **Команды** — состав участников выбранной лиги
- 📊 **Турнирная таблица** — актуальное положение команд
- 📅 **Расписание** — ближайшие матчи и полное расписание команды
- 🔥 **Результаты** — последние завершённые матчи команды
- 👥 **Заявка** — состав команды с амплуа и датами рождения
- 📈 **Статистика игроков** — голы, карточки, матчи
- 🤖 **Прогноз** — статистический прогноз на ближайший матч
- 🔍 **Поиск** — поиск команды по названию
- 📬 **Подписки** — подписка на команды для отслеживания
- 💾 **Кеширование** — TTL-кеш для снижения нагрузки на сайт

## Установка

### 1. Клонируйте репозиторий

```bash
git clone <repository_url>
cd BOT_altaifootball.ru
```

### 2. Создайте виртуальное окружение

**Windows:**
```bash
python -m venv .venv
.venv\Scripts\activate
```

**Linux/macOS:**
```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Установите зависимости

```bash
pip install -r requirements.txt
```

> **Windows + lxml:** если lxml не собирается, используйте:
> ```bash
> pip install lxml --only-binary=all
> pip install -r requirements.txt
> ```

### 4. Настройте `.env`

**Windows (PowerShell):**
```bash
copy .env.example .env
```

**Linux/macOS:**
```bash
cp .env.example .env
```

Откройте `.env` и укажите `BOT_TOKEN`.

### 5. Получите токен бота

1. Откройте Telegram и найдите [@BotFather](https://t.me/BotFather)
2. Отправьте `/newbot`
3. Скопируйте токен в `.env`

## Запуск

### Через .bat (Windows)

Просто дважды кликните:

| Файл | Описание |
|------|----------|
| `run_bot.bat` | Обычный запуск |
| `run_bot_debug.bat` | Debug-режим (показывает версию Python, код завершения) |

### Через командную строку

```bash
python -m app.main
```

## Навигация

```
/start
  ↓
📅 Выбор сезона
  ├── 📅 Текущий сезон → турниры текущего сезона
  ├── 🗂 Выбрать сезон → список всех сезонов
  └── 🕘 Архив → прошлые сезоны
  ↓
🏟 Выбранная лига
  ├── 👥 Команды → выбор команды
  ├── 📊 Турнирная таблица
  ├── 📅 Ближайшие матчи
  └── 🔥 Результаты
  ↓
⚽ Команда
  ├── 📅 Ближайшие    🗓 Расписание
  ├── 🔥 Результаты   📊 Таблица
  ├── 👥 Заявка       📈 Игроки
  ├── 🤖 Прогноз
  └── 🔔 Подписаться
```

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Запустить бота |
| `/menu` | Главное меню |
| `/help` | Справка |
| `/leagues` | Выбор сезона и лиг |
| `/search` | Поиск команды |
| `/subscriptions` | Мои подписки |

## Кеширование

| Данные | TTL |
|--------|-----|
| Лиги | 6 часов |
| Команды лиги | 6 часов |
| Турнирная таблица | 1 час |
| Матчи | 30 минут |
| Заявка команды | 6 часов |
| Статистика игроков | 3 часа |
| Поиск | 3 часа |

## Pipeline загрузки страниц

```
1. httpx — быстрый основной бэкенд
2. curl_cffi — промежуточный fallback (TLS impersonation, обход 403)
3. Playwright — последний fallback (JS-рендеринг, требует установки)
```

Пустой HTML (< 100 bytes) считается ошибкой, а не успешной загрузкой.

## HTML Fixtures и тесты

В проекте есть набор реальных HTML-страниц для тестирования:

```
tests/fixtures/
├── save_site_html.py      # Скрипт обновления fixtures
├── __init__.py
└── site_html/
    ├── tournaments.html
    ├── league_3607.html
    ├── league_3530.html
    ├── team_6662.html           # GM SPORT 22 Барнаул
    ├── team_5790.html           # СКА Сибирский ЗАТО
    ├── team_6659.html           # Товарка 22 Барнаул
    ├── team_6734.html           # Libertas NEO STAR's Барнаул
    ├── team_5628.html           # АТТ фермер Алейск
    ├── team_6662_roster.html    # GM SPORT 22 — заявка
    ├── team_5790_roster.html    # СКА — заявка
    ├── team_6662_stats.html     # GM SPORT 22 — статистика
    ├── team_5790_stats.html     # СКА — статистика
    ├── boxscore_140352.html     # Протокол матча
    ├── boxscore_140597.html     # Протокол матча
    └── preview_140750.html      # Превью матча
```

### Обновление fixtures

```bash
# Обновить все fixtures:
python -m tests.fixtures.save_site_html --force

# Только матчи/boxscore:
python -m tests.fixtures.save_site_html --match

# Показать список URL:
python -m tests.fixtures.save_site_html --list
```

### Запуск тестов

```bash
python -m pytest tests/ -v          # все тесты
python -m pytest tests/test_fixtures.py -v  # fixture-тесты
```

### Диагностика прогноза (источники матчей)

```bash
python -m scripts.prediction_diagnostics --team "СКА Сибирский ЗАТО" --league-id 3607
```

Скрипт печатает JSON с источниками данных для прогноза:
- ближайший матч (`preview/boxscore/fallback`)
- последние матчи обеих команд с источниками
- источник H2H (`boxscore` или `mixed`)

### Sanity-check лиги (W/D/L vs таблица)

```bash
python -m scripts.check_league_consistency --league-id 3607
```

Скрипт сравнивает W/D/L по командным fixtures с таблицей выбранной лиги:
- проверяет все команды, для которых есть `team_<id>.html`
- показывает `missing_fixtures` и `mismatches`
- возвращает код `0`, если всё ок, иначе `1`

## Структура проекта

```
project/
├── app/
│   ├── main.py                 # Точка входа
│   ├── states.py               # FSM состояния
│   ├── config.py               # Настройки (pydantic-settings)
│   ├── logger.py               # Логирование
│   ├── dependencies.py         # Глобальные DI-синглтоны
│   │
│   ├── keyboards/
│   │   ├── main.py             # Все клавиатуры (вкл. сезоны)
│   │   └── callbacks.py        # Парсинг callback-данных
│   │
│   ├── handlers/
│   │   ├── start.py            # /start, /menu, /help
│   │   └── leagues.py          # Сезоны, лиги, команды, матчи, roster, stats, прогноз
│   │
│   ├── services/
│   │   ├── parser.py           # Парсер сайта (HTML → модели)
│   │   ├── football_service.py # Бизнес-логика + кеш + прогноз
│   │   ├── formatter.py        # Форматирование сообщений
│   │   ├── cache.py            # TTL-кеш (in-memory)
│   │   ├── page_loader.py      # Pipeline: httpx → curl_cffi → Playwright
│   │   ├── debug_snapshot.py   # Сохранение HTML для отладки
│   │   └── selectors_config.py # CSS-селекторы (документация)
│   │
│   ├── models/
│   │   └── football.py         # League, Team, Match, StandingRow, Player, PlayerStat, MatchPrediction
│   │
│   ├── repositories/
│   │   ├── user_repo.py        # Состояние пользователей (SQLite)
│   │   └── subscription_repo.py# Подписки (SQLite)
│   │
│   └── utils/
│       ├── dates.py            # Парсинг и форматирование дат
│       └── text.py             # Текстовые утилиты
│
├── tests/
│   ├── conftest.py
│   ├── test_cache.py
│   ├── test_dates.py
│   ├── test_formatter.py
│   ├── test_models.py
│   ├── test_new_features.py   # Тесты новых фич
│   ├── test_fixtures.py       # Тесты на реальных HTML fixtures
│   └── fixtures/
│       ├── save_site_html.py  # Скрипт обновления fixtures
│       └── site_html/         # 13 HTML-файлов
│
├── run_bot.bat                # Запуск бота (Windows)
├── run_bot_debug.bat          # Debug-запуск (Windows)
├── .env.example
├── requirements.txt
├── pyproject.toml
└── README.md
```

## Ограничения

> ⚠️ Парсинг сайта altaifootball.ru зависит от HTML-структуры, которая может измениться.
> Если бот перестал находить данные — проверьте актуальную HTML-структуру сайта
> и обновите методы в `app/services/parser.py`.

1. **Парсинг** — CSS-селекторы могут потребовать корректировки
2. **Уведомления** — подписки пока не отправляют push-уведомления
3. **curl_cffi** — по умолчанию включён как fallback (переменная `USE_CURL_CFFI=true`)
4. **Playwright** — требует `pip install playwright && playwright install chromium`

## Технологии

- **Python 3.11+**
- **aiogram 3.x** — Telegram Bot Framework
- **httpx** — асинхронные HTTP-запросы
- **curl_cffi** — TLS impersonation (fallback при 403)
- **beautifulsoup4 + lxml** — парсинг HTML
- **selectolax** — быстрый CSS-парсер (для простых извлечений)
- **pydantic** — модели данных
- **aiosqlite** — асинхронная работа с SQLite
- **tenacity** — retry при ошибках сети
- **python-dotenv** — загрузка `.env`

## Лицензия

MIT — для личного использования.
