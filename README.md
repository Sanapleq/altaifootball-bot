# ⚽ Altaifootball Telegram Bot

Telegram-бот для просмотра футбольных данных с сайта **altaifootball.ru**.
Показывает лиги, команды, турнирные таблицы, расписание матчей и результаты.

## Возможности

- 🏆 **Просмотр лиг** — список всех доступных турниров
- 👥 **Команды** — состав участников выбранной лиги
- 📊 **Турнирная таблица** — актуальное положение команд
- 📅 **Расписание** — ближайшие матчи команды или лиги
- 🔥 **Результаты** — последние завершённые матчи
- 🔍 **Поиск** — поиск команды по названию (частичное совпадение)
- 📬 **Подписки** — подписка на команды для отслеживания
- 💾 **Кеширование** — TTL-кеш для снижения нагрузки на сайт

## Установка

### 1. Клонируйте репозиторий

```bash
git clone <repository_url>
cd BOT_altaifootball.ru
```

### 2. Создайте виртуальное окружение

```bash
python -m venv venv
```

**Windows:**
```bash
venv\Scripts\activate
```

**Linux/macOS:**
```bash
source venv/bin/activate
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

```bash
cp .env.example .env
```

Откройте `.env` и укажите:

```env
# Токен Telegram-бота (получить у @BotFather)
BOT_TOKEN=your_bot_token_here

# Базовый URL сайта
BASE_URL=https://altaifootball.ru

# Таймаут HTTP-запросов в секундах
REQUEST_TIMEOUT=30

# Уровень логирования: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL=INFO

# Путь к SQLite базе данных
DB_PATH=data/bot.db
```

### 5. Получите токен бота

1. Откройте Telegram и найдите [@BotFather](https://t.me/BotFather)
2. Отправьте `/newbot`
3. Следуйте инструкциям
4. Скопируйте полученный токен в `.env`

## Запуск

```bash
python -m app.main
```

Или:

```bash
python app/main.py
```

## Структура проекта

```
project/
├── app/
│   ├── main.py                 # Точка входа, инициализация бота
│   ├── states.py               # FSM состояния (MainStates, SearchStates)
│   ├── config.py               # Настройки (pydantic-settings)
│   ├── logger.py               # Логирование
│   ├── dependencies.py         # Глобальные DI-синглтоны
│   │
│   ├── keyboards/
│   │   ├── main.py             # Все клавиатуры
│   │   └── callbacks.py        # Парсинг callback-данных
│   │
│   ├── handlers/
│   │   ├── start.py            # /start, /menu, /help, кнопки
│   │   └── leagues.py          # Лиги, команды, матчи, подписки
│   │
│   ├── services/
│   │   ├── parser.py           # Парсер сайта (HTML → модели)
│   │   ├── football_service.py # Бизнес-логика + кеш
│   │   ├── cache.py            # TTL-кеш (in-memory)
│   │   ├── formatter.py        # Форматирование сообщений
│   │   └── selectors_config.py # CSS-селекторы (документация)
│   │
│   ├── models/
│   │   └── football.py         # Pydantic-модели
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
│   └── test_models.py
│
├── .env.example
├── requirements.txt
├── pyproject.toml
└── README.md
```

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Запустить бота |
| `/menu` | Главное меню |
| `/help` | Справка |
| `/leagues` | Список лиг |
| `/search` | Поиск команды |
| `/subscriptions` | Мои подписки |

## Кеширование

| Данные | TTL |
|--------|-----|
| Лиги | 6 часов |
| Команды лиги | 6 часов |
| Турнирная таблица | 1 час |
| Матчи | 30 минут |
| Поиск | 3 часа |

Кеш in-memory. Для перехода на Redis замените бэкенд в `CacheService`.

## Ограничения текущей версии

> ⚠️ **Важно:** парсинг сайта altaifootball.ru зависит от HTML-структуры, которая может измениться.
> Селекторы и логика извлечения данных находятся в `app/services/parser.py`.
> Если бот перестал находить лиги, команды или матчи — проверьте актуальную HTML-структуру сайта
> и обновите методы `_extract_*` в парсере.

1. **Парсинг** — CSS-селекторы могут потребовать корректировки под реальную структуру сайта
2. **Уведомления** — подписки пока не отправляют push-уведомления (задел)
3. **Пагинация** — только для списков команд
4. **Нет Rate Limiting** — при частых запросах сайт может заблокировать

## Адаптация под реальную структуру сайта

Если при запуске бот не находит данные:

1. Откройте `app/services/selectors_config.py`
2. Обновите CSS-селекторы под актуальную HTML-структуру сайта
3. При необходимости — скорректируйте методы `_extract_*` в `parser.py`
4. Включите `LOG_LEVEL=DEBUG` в `.env` для подробного логирования

## Идеи для развития

- [ ] Фоновые уведомления о новых результатах (APScheduler)
- [ ] Redis вместо in-memory кеша
- [ ] Экспорт данных в CSV/Excel
- [ ] Статистика игроков
- [ ] Сравнение команд
- [ ] Прогнозы и аналитика
- [ ] Деплой на сервер (Docker, systemd)
- [ ] Webhook вместо polling
- [ ] Мультиязычность

## Технологии

- **Python 3.11+**
- **aiogram 3.x** — Telegram Bot Framework
- **httpx** — асинхронные HTTP-запросы
- **beautifulsoup4 + lxml** — парсинг HTML
- **pydantic** — модели данных
- **aiosqlite** — асинхронная работа с SQLite
- **tenacity** — retry при ошибках сети
- **python-dotenv** — загрузка `.env`

## Лицензия

MIT — для личного использования.
