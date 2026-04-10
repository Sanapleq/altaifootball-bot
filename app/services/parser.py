"""Парсер сайта altaifootball.ru.

Этот модуль отвечает за извлечение данных из HTML-страниц сайта.
Вся логика парсинга изолирована здесь — при изменении структуры сайта
нужно править только этот файл.

Структура сайта altaifootball.ru:
  - Главная:              /
  - Турниры:              /tournaments/
  - Турнир:               /tournaments/{year}/{tournament_id}/
  - Команда в турнире:    /tournaments/{year}/{tournament_id}/teams/{team_id}/
  - Календарь турнира:    /tournaments/{year}/{tournament_id}-NNNN/schedule/
  - Статистика турнира:   /tournaments/{year}/{tournament_id}/stats/
  - Протокол матча:       /tournaments/boxscore/{match_id}/
  - Превью матча:         /tournaments/boxscore/{match_id}/preview/
  - Общее расписание:     /schedule/

Ключевые CSS-классы таблиц:
  - Standings/матчи команды:  table_box_row
  - Общее расписание:         scoreboard
  - Навигация:                page, site
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.logger import logger
from app.models.football import League, Match, StandingRow, Team
from app.services.page_loader import PageLoader
from app.utils.dates import parse_russian_date
from app.utils.text import clean_text

# Debug-импорты
try:
    from app.services.debug_snapshot import save_debug_html
    _DEBUG_AVAILABLE = True
except ImportError:
    _DEBUG_AVAILABLE = False

# selectolax — быстрый CSS-парсер (основной для простых извлечений)
try:
    from selectolax.parser import HTMLParser as SelectolaxParser
    _SELECTOLAX_AVAILABLE = True
except ImportError:
    _SELECTOLAX_AVAILABLE = False
    SelectolaxParser = None  # type: ignore[misc,assignment]


def _debug_save(html: str, name: str, **kwargs) -> None:
    """Сохранить HTML для отладки если включён флаг."""
    if _DEBUG_AVAILABLE and getattr(settings, "debug_save_html", False):
        try:
            save_debug_html(html, name, **kwargs)
        except Exception as e:
            logger.debug("Ошибка сохранения debug HTML: %s", e)


def _fast_extract_links(html: str, pattern: str) -> list[tuple[str, str]]:
    """Быстрое извлечение ссылок через selectolax.

    Args:
        html: HTML-строка.
        pattern: CSS-селектор для ссылок (например 'a[href]').

    Returns:
        Список кортежей (href, text).
    """
    if _SELECTOLAX_AVAILABLE and SelectolaxParser is not None:
        try:
            tree = SelectolaxParser(html)
            results = []
            for node in tree.css(pattern):
                href = node.attributes.get("href", "")
                text = node.text(strip=True)
                if href and text:
                    results.append((href, text))
            return results
        except Exception:
            pass  # Fallback to BS4

    # Fallback: используем BS4
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    results = []
    for link in soup.select(pattern):
        href = link.get("href", "")
        text = link.get_text(strip=True)
        if href and text:
            results.append((href, text))
    return results

# ── Словарь мусорных текстов, которые НЕ должны попадать в данные ─────

_NAVIGATION_TEXTS = frozenset({
    "главная", "новости", "турниры", "таблицы и результаты",
    "участники", "контакты", "о сайте", "о нас", "реклама",
    "вход", "регистрация", "поиск", "меню", "rss",
    "home", "news", "tournaments", "tables", "participants",
    "contacts", "about", "search", "login", "register",
    "таблицы", "результаты", "статистика", "форум",
    "правила", "помощь", "faq",
})

# Тексты, которые не могут быть названием команды или лиги
_SHORT_TEXTS = frozenset({"", "-", "—", "|", "/", ":", ".", "..."})


def _is_navigation_text(text: str) -> bool:
    """Проверить, является ли текст навигационным мусором."""
    t = text.strip().lower()
    if not t or len(t) < 2:
        return True
    if t in _NAVIGATION_TEXTS:
        return True
    # Короткие ссылки вроде «2024», «2025» — это годы, не лиги
    if re.fullmatch(r"20\d{2}", t):
        return True
    return False


def _looks_like_score(text: str) -> bool:
    """Проверить, похож ли текст на счёт матча.

    Отлавливает: 5:0, 2:4, 3:3, 3:3 (3:2 пен), ?-?, 0:0, 13:3 и т.д.

    Args:
        text: Текст для проверки.

    Returns:
        True если текст похож на счёт матча.
    """
    t = text.strip()
    if not t:
        return True

    # Чистый счёт: 5:0, 2-4, 3:3
    if re.fullmatch(r"\d+\s*[:\-]\s*\d+", t):
        return True

    # Счёт с пенальти: 3:3 (3:2 пен), 3:3 (3:2 pen)
    if re.fullmatch(r"\d+\s*[:\-]\s*\d+\s*\(.*\d+\s*[:\-]\s*\d+.*\)", t):
        return True

    # Неизвестный счёт: ?-?, ?:?, ?-0
    if re.fullmatch(r"\?\s*[:\-]\s*\?", t):
        return True
    if re.fullmatch(r"\d+\s*[:\-]\s*\?", t):
        return True
    if re.fullmatch(r"\?\s*[:\-]\s*\d+", t):
        return True

    # Только цифры и разделители: 13:3, 5:0
    if re.fullmatch(r"[\d\s:\-]+", t) and any(c in t for c in ":-"):
        return True

    return False


def _looks_like_team_name(text: str) -> bool:
    """Проверить, похож ли текст на название команды.

    True: «Динамо Барнаул», «GM SPORT 22», «Алтай», «Libertas NEO STAR's Барнаул»
    False: «5:0», «главная», «2025», «?-?», «статистика», «Турнирная таблица»

    Args:
        text: Текст для проверки.

    Returns:
        True если текст похож на название команды.
    """
    t = text.strip()
    if not t or len(t) < 2:
        return False

    # Слишком длинные строки — не команда
    if len(t) > 80:
        return False

    # Отбрасываем счёты
    if _looks_like_score(t):
        return False

    # Отбрасываем навигацию
    if _is_navigation_text(t):
        return False

    lower = t.lower()

    # Служебные слова, характерные для заголовков разделов, а не команд
    service_words = [
        "таблицы", "результаты", "участники", "статистика",
        "новости", "календарь", "расписание", "турнир",
        "протокол", "составы", "бомбардиры", "вратари",
        "положение", "сетка", "регламент", "документ",
        "таблица", "отчёты", "обзор", "анонс", "превью",
        "архив", "сезон", "календарь игр",
    ]
    for word in service_words:
        if word in lower:
            return False

    # Только цифры и разделители — не команда
    if re.fullmatch(r"[\d\s\./\-:]+", t):
        return False

    # Должно содержать хотя бы одну букву
    if not re.search(r"[a-zA-Zа-яА-ЯёЁ]", t):
        return False

    return True


def _looks_like_league_name(text: str) -> bool:
    """Проверить, похож ли текст на название турнира/лиги.

    Принимает ТОЛЬКО строки с турнирными маркерами:
    «Чемпионат Алтайского края», «Кубок России», «Премьер-Лига»

    Отбрасывает:
    «5:0», «3:3 (3:2 пен)», «главная», «2025», «?-?»
    А также «длинную строку из двух слов» без турнирного маркера.

    Args:
        text: Текст для проверки.

    Returns:
        True если текст похож на название турнира.
    """
    t = text.strip()
    if not t or len(t) < 3:
        return False

    # Отбрасываем счёты матчей
    if _looks_like_score(t):
        return False

    # Отбрасываем навигацию
    if _is_navigation_text(t):
        return False

    lower = t.lower()

    # Турнирные маркеры — ОБЯЗАТЕЛЬНЫ для принятия
    tournament_markers = [
        "чемпионат", "первенство", "кубок", "лига", "дивизион",
        "турнир", "дфл", "u-", "юнош", "юниор", "вторая лига",
        "третья лига", "первая лига", "фнл", "рфл", "суперлига",
        "высшая лига", "межрегион", "мфк", "футбол", "mini-football",
    ]
    for marker in tournament_markers:
        if marker in lower:
            return True

    # Без турнирного маркера — отвергаем, даже если длинная
    return False


class SiteParserError(Exception):
    """Ошибка парсинга сайта."""

    pass


class SiteParser:
    """Парсер сайта altaifootball.ru.

    Все методы делают HTTP-запросы через PageLoader,
    парсят HTML и возвращают модели данных.
    При ошибках — логируют и возвращают fallback-значения.
    """

    def __init__(self, base_url: Optional[str] = None) -> None:
        """Инициализация парсера.

        Args:
            base_url: Базовый URL сайта (из настроек по умолчанию).
        """
        self.base_url = base_url or settings.base_url
        self._loader = PageLoader(
            base_url=self.base_url,
            use_playwright_fallback=getattr(settings, "use_playwright_fallback", False),
        )

    async def close(self) -> None:
        """Закрыть PageLoader (и все его бэкенды)."""
        await self._loader.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _fetch_page(self, url: str) -> str:
        """Загрузить HTML-страницу через PageLoader.

        Args:
            url: Относительный или абсолютный URL.

        Returns:
            HTML-содержимое страницы.

        Raises:
            SiteParserError: При ошибке загрузки.
        """
        from app.services.page_loader import PageLoaderError

        try:
            return await self._loader.fetch_page(url)
        except PageLoaderError as e:
            raise SiteParserError(str(e)) from e
        except Exception as e:
            raise SiteParserError(f"Неожиданная ошибка при загрузке {url}: {e}") from e

    def _parse_html(self, html: str) -> BeautifulSoup:
        """Распарсить HTML в BeautifulSoup.

        Args:
            html: HTML-содержимое.

        Returns:
            BeautifulSoup объект.

        Raises:
            SiteParserError: Если HTML пустой.
        """
        if not html or len(html) < 100:
            raise SiteParserError(f"Пустой HTML ({len(html) if html else 0} bytes)")
        return BeautifulSoup(html, "lxml")

    def _make_absolute_url(self, url: Optional[str]) -> str:
        """Преобразовать относительный URL в абсолютный.

        Args:
            url: URL (относительный или абсолютный).

        Returns:
            Абсолютный URL.
        """
        if not url:
            return ""
        return urljoin(self.base_url, url)

    def _extract_id_from_url(self, url: str) -> str:
        """Извлечь ID из URL.

        Пытается найти числовой или строковый ID в URL.

        Args:
            url: URL страницы.

        Returns:
            Строковый ID.
        """
        # Пытаемся найти последний сегмент URL
        url_clean = url.rstrip("/")
        parts = url_clean.split("/")
        if parts:
            return parts[-1]
        return url

    # ========================================================================
    # ЛИГИ
    # ========================================================================

    async def get_leagues(self) -> list[League]:
        """Получить список всех лиг / турниров.

        Основной путь: страница /tournaments/ — все ссылки вида
        /tournaments/{year}/{id}/ извлекаются как лиги.
        Это самый стабильный источник — сайт сам формирует этот список.

        Использует selectolax для быстрого извлечения ссылок,
        с fallback на BeautifulSoup.

        Returns:
            Список объектов League.
        """
        logger.info("[leagues] Загрузка списка лиг с /tournaments/")

        try:
            html = await self._fetch_page("/tournaments/")
        except SiteParserError as e:
            logger.error("[leagues] Не удалось загрузить страницу: %s", e)
            return []

        logger.debug("[leagues] HTML размер: %d байт", len(html))

        leagues: list[League] = []
        seen_urls: set[str] = set()

        # Извлекаем ВСЕ ссылки вида /tournaments/{year}/{id}/
        tournament_pattern = re.compile(r"/tournaments/\d+/\d+/$")

        # Быстрое извлечение через selectolax (или BS4 fallback)
        links = _fast_extract_links(html, "a[href]")

        for href, text in links:
            # Фильтруем только турнирные ссылки
            if not tournament_pattern.search(href):
                continue

            text = clean_text(text)
            if not text or len(text) < 2:
                logger.debug("[leagues] Пропущена ссылка без текста: %s", href)
                continue

            abs_url = self._make_absolute_url(href)
            if abs_url in seen_urls:
                continue
            seen_urls.add(abs_url)

            m = re.search(r"/tournaments/(\d+)/(\d+)/", href)
            if not m:
                continue

            year = m.group(1)
            league_id = m.group(2)

            leagues.append(League(
                id=league_id,
                name=text,
                url=abs_url,
                season=year,
            ))

        if not leagues:
            logger.warning("[leagues] Не найдено ни одной лиги на /tournaments/")
            _debug_save(html, "leagues_empty")

        logger.info(
            "[leagues] Найдено лиг: %d | URLs: %d | HTML: %d bytes",
            len(leagues), len(seen_urls), len(html)
        )
        return leagues

    # ========================================================================
    # КОМАНДЫ
    # ========================================================================

    async def get_league_teams(self, league: League) -> list[Team]:
        """Получить список команд лиги.

        Основной путь: страница турнира содержит таблицу standings
        (table_box_row) со ссылками на команды вида
        /tournaments/{year}/{id}/teams/{team_id}/.

        Args:
            league: Объект лиги.

        Returns:
            Список объектов Team.
        """
        logger.info("[league_teams] Загрузка команд лиги: %s (id=%s)", league.name, league.id)

        try:
            html = await self._fetch_page(league.url)
            soup = self._parse_html(html)
        except SiteParserError as e:
            logger.error("[league_teams] Не удалось загрузить страницу: %s", e)
            return []

        logger.debug("[league_teams] HTML размер: %d байт", len(html))

        teams: list[Team] = []
        seen_ids: set[str] = set()

        url_match = re.search(r"/tournaments/(\d+)/(\d+)/", league.url)
        league_year = url_match.group(1) if url_match else ""
        league_id_from_url = url_match.group(2) if url_match else league.id

        tables_found = 0
        for table in soup.find_all("table", class_="table_box_row"):
            tables_found += 1
            for row in table.find_all("tr"):
                link = row.find("a", href=True)
                if not link:
                    continue

                href = link.get("href", "")
                team_m = re.search(r"/tournaments/\d+/\d+/teams/(\d+)/", href)
                if not team_m:
                    continue

                team_id = team_m.group(1)
                if team_id in seen_ids:
                    continue

                raw_name = clean_text(link.get_text())
                team_name = self._split_team_name(raw_name)

                if not team_name or len(team_name) < 2:
                    continue

                seen_ids.add(team_id)
                teams.append(Team(
                    id=team_id,
                    name=team_name,
                    url=self._make_absolute_url(href),
                    league_id=league.id,
                ))

            if teams:
                break

        # Стратегия 2
        if not teams:
            logger.debug("[league_teams] table_box_row не дала команд, ищу все ссылки на команды")
            team_link_pattern = re.compile(
                rf"/tournaments/\d+/{re.escape(league_id_from_url)}/teams/(\d+)/"
            )
            for link in soup.find_all("a", href=team_link_pattern):
                href = link.get("href", "")
                raw_name = clean_text(link.get_text())
                if not raw_name or len(raw_name) < 2:
                    continue

                team_m = team_link_pattern.search(href)
                if not team_m:
                    continue

                team_id = team_m.group(1)
                if team_id in seen_ids:
                    continue

                seen_ids.add(team_id)
                team_name = self._split_team_name(raw_name)
                teams.append(Team(
                    id=team_id,
                    name=team_name,
                    url=self._make_absolute_url(href),
                    league_id=league.id,
                ))

        if not teams:
            logger.warning(
                "[league_teams] Лига '%s' — не найдено команд. table_box_row=%d",
                league.name, tables_found
            )
            _debug_save(html, "league_teams_empty", league_id=league.id)

        logger.info("[league_teams] Лига '%s' найдено команд: %d", league.name, len(teams))
        return teams

    def _find_standings_table(self, soup: BeautifulSoup) -> Optional[Tag]:
        """Найти таблицу standings на странице.

        Сначала ищет по CSS-классам, затем перебирает все таблицы
        и ищет похожую на standings/participants.

        Args:
            soup: BeautifulSoup объект.

        Returns:
            Тег таблицы или None.
        """
        # Приоритет 1: CSS-классы
        for selector in [
            "table.standings",
            "table.standing",
            "table.table.standings",
            "table.league-table",
            "table.tournament-table",
            "table.table-league",
            "div.standings table",
        ]:
            table = soup.select_one(selector)
            if table:
                return table

        # Приоритет 2: Перебираем все таблицы — ищем похожую на standings
        for table in soup.find_all("table"):
            if self._looks_like_standings_table(table):
                return table

        return None

    def _looks_like_standings_table(self, table: Tag) -> bool:
        """Проверить, похожа ли таблица на standings/participants.

        Критерии:
        - Минимум 3 строки
        - В строках есть ссылки (команды)
        - Есть числовые данные (очки, игры и т.д.)

        Args:
            table: Тег <table>.

        Returns:
            True если таблица похожа на standings.
        """
        rows = table.find_all("tr")
        if len(rows) < 3:
            return False

        # Проверяем первые 5 строк
        link_count = 0
        number_count = 0
        for row in rows[:5]:
            links = row.find_all("a", href=True)
            if links:
                link_count += 1
            cells = row.find_all(["td", "th"])
            for cell in cells:
                t = clean_text(cell.get_text())
                if re.fullmatch(r"\d+", t):
                    number_count += 1

        # Должно быть хотя бы 2 строки со ссылками и числовые данные
        return link_count >= 2 and number_count >= 3

    def _extract_team_from_standing_row(self, row: Tag) -> Optional[Team]:
        """Извлечь команду из строки standings-таблицы.

        Args:
            row: Тег <tr>.

        Returns:
            Team или None.
        """
        link = row.find("a", href=True)
        if not link:
            return None

        name = clean_text(link.get_text())
        if not _looks_like_team_name(name):
            return None

        href = link.get("href", "")
        team_id = self._extract_id_from_url(href)
        return Team(
            id=team_id,
            name=name,
            url=self._make_absolute_url(href),
        )

    def _extract_team_from_element(self, el: Tag) -> Optional[Team]:
        """Извлечь данные команды из элемента.

        Строгая фильтрация: отбрасывает навигацию, счёты, мусор.

        Args:
            el: BeautifulSoup тег.

        Returns:
            Team или None.
        """
        link = el if el.name == "a" else el.find("a")
        if not link:
            return None

        href = link.get("href", "")
        name = clean_text(link.get_text())

        if not href or not _looks_like_team_name(name):
            return None

        team_id = self._extract_id_from_url(href)
        logo_url = None
        img = el.find("img") or link.find("img")
        if img:
            logo_url = self._make_absolute_url(img.get("src") or img.get("data-src"))

        return Team(
            id=team_id,
            name=name,
            url=self._make_absolute_url(href),
            logo_url=logo_url,
        )

    def _split_team_name(self, raw_name: str) -> str:
        """Разделить слитное название команды.

        На сайте названия часто слиты: "Полимер-МБарнаул", "БияБийск".
        Нужно разделить название команды и город.

        Эвристика: ищем границу «латиница/дефис + кириллица» или
        «кириллица + кириллица (город)».

        Args:
            raw_name: Сырое название команды.

        Returns:
            Разделённое название.
        """
        if not raw_name:
            return ""

        # Паттерн: команда + город (кириллица + кириллица)
        # Ищем границу: слово из букв/дефисов/цифр + слово с заглавной кириллицей
        # Примеры: "Полимер-МБарнаул" → "Полимер-М Барнаул"
        #          "СШ-Динамо-БарнаулБарнаул" → "СШ-Динамо-Барнаул Барнаул"

        # Стратегия 1: Разделение по границе «строчная/заглавная кириллица»
        # Ищем позицию где после буквы/дефиса идёт заглавная кириллица
        m = re.search(r"([a-zA-Zа-яА-ЯёЁё0-9\-])([А-ЯЁ])([а-яё])", raw_name)
        if m:
            # Проверяем что это не начало слова (не акроним внутри названия)
            # "СШ-Динамо" → не разделять, "ДинамоБарнаул" → разделять
            before = m.group(1)
            # Если перед заглавной буквой стоит строчная — это граница
            if before.islower() or before in ("-", "М", ""):
                return raw_name[:m.start(2)] + " " + raw_name[m.start(2):]

        # Стратегия 2: Разделение по латиница → кириллица
        m = re.search(r"([a-zA-Z])([а-яА-ЯёЁ])", raw_name)
        if m:
            return raw_name[:m.start(2)] + " " + raw_name[m.start(2):]

        # Стратегия 3: Разделение кириллица → латиница (редко)
        m = re.search(r"([а-яА-ЯёЁ])([a-zA-Z])", raw_name)
        if m:
            return raw_name[:m.start(2)] + " " + raw_name[m.start(2):]

        # Не смогли разделить — возвращаем как есть
        return raw_name

    # ========================================================================
    # ТУРНИРНАЯ ТАБЛИЦА
    # ========================================================================

    async def get_league_standings(self, league_url: str) -> list[StandingRow]:
        """Получить турнирную таблицу лиги.

        На странице турнира ищем таблицу class="table_box_row".
        Формат строк: М | Команда | И | В | Н | П | Р/М | О

        Args:
            league_url: URL страницы лиги.

        Returns:
            Список строк таблицы.
        """
        logger.info("[standings] Загрузка таблицы: %s", league_url)

        try:
            html = await self._fetch_page(league_url)
            soup = self._parse_html(html)
        except SiteParserError as e:
            logger.error("[standings] Не удалось загрузить страницу: %s", e)
            return []

        logger.debug("[standings] HTML размер: %d байт", len(html))

        standings: list[StandingRow] = []

        tables_checked = 0
        for table in soup.find_all("table", class_="table_box_row"):
            tables_checked += 1
            standings = self._parse_standings_table_box(table)
            if standings:
                break

        # Fallback
        if not standings:
            logger.debug("[standings] table_box_row не дал результатов, пробую все таблицы")
            for table in soup.find_all("table"):
                if table.get("class") and ("page" in table.get("class") or "site" in table.get("class")):
                    continue
                tables_checked += 1
                standings = self._parse_standings_table_box(table)
                if len(standings) >= 2:
                    break
                standings = []

        if not standings:
            logger.warning(
                "[standings] Не найдено строк таблицы. Проверено таблиц: %d",
                tables_checked
            )
            _debug_save(html, "standings_empty")

        logger.info("[standings] Найдено строк: %d | проверено таблиц: %d", len(standings), tables_checked)
        return standings

    def _parse_standings_table_box(self, table: Tag) -> list[StandingRow]:
        """Распарсить таблицу class="table_box_row" как standings.

        Формат: М | Команда | И | В | Н | П | Р/М | О

        Args:
            table: BeautifulSoup тег <table>.

        Returns:
            Список строк standings.
        """
        standings: list[StandingRow] = []
        rows = table.find_all("tr")
        if len(rows) < 2:
            return []

        # Первая строка — заголовок, пропускаем
        for row in rows[1:]:
            standing = self._parse_standing_row_box(row)
            if standing:
                standings.append(standing)

        return standings

    def _parse_standing_row_box(self, row: Tag) -> Optional[StandingRow]:
        """Распарсить строку таблицы standings (table_box_row формат).

        Формат ячеек: М | Команда(ссылка) | И | В | Н | П | Р/М | О

        Args:
            row: Тег <tr>.

        Returns:
            StandingRow или None.
        """
        cells = row.find_all(["td", "th"])
        if len(cells) < 5:
            return None

        # Позиция
        try:
            pos_text = clean_text(cells[0].get_text())
            position = int(re.sub(r"[^\d]", "", pos_text))
            if position < 1 or position > 200:
                return None
        except (ValueError, IndexError):
            return None

        # Команда — ссылка
        team_cell = cells[1]
        team_link = team_cell.find("a", href=True)
        raw_name = clean_text(team_link.get_text() if team_link else team_cell.get_text())
        team_url = self._make_absolute_url(team_link.get("href", "")) if team_link else None
        team_name = self._split_team_name(raw_name)

        if not team_name or len(team_name) < 2:
            return None

        # Числовые данные: И В Н П Р/М О
        # Р/М может быть в формате "86-17"
        numbers: list[int] = []
        goals_for = 0
        goals_against = 0

        # Ячейки 2+: И, В, Н, П, Р/М, О
        for i, cell in enumerate(cells[2:]):
            text = clean_text(cell.get_text())
            # Проверяем на формат голов "86-17"
            goals_m = re.match(r"^(\d+)\s*[-:]\s*(\d+)$", text)
            if goals_m:
                goals_for = int(goals_m.group(1))
                goals_against = int(goals_m.group(2))
                continue

            nums = re.findall(r"\d+", text)
            if nums:
                numbers.extend(int(n) for n in nums)

        # Разбор: И В Н П ... О (очки — последнее число)
        if len(numbers) < 4:
            return None

        played = numbers[0]
        wins = numbers[1] if len(numbers) > 1 else 0
        draws = numbers[2] if len(numbers) > 2 else 0
        losses = numbers[3] if len(numbers) > 3 else 0
        points = numbers[-1]  # Последнее число — очки

        if points < 0 or points > 200:
            return None

        return StandingRow(
            position=position,
            team_name=team_name,
            team_url=team_url,
            played=played,
            wins=wins,
            draws=draws,
            losses=losses,
            goals_for=goals_for,
            goals_against=goals_against,
            points=points,
        )

    # ========================================================================
    # МАТЧИ
    # ========================================================================

    async def get_team_matches(self, team_url: str) -> list[Match]:
        """Получить все матчи команды.

        Страница команды на сайте:
        /tournaments/{year}/{tournament_id}/teams/{team_id}/

        Содержит таблицу class="table_box_row" с форматом:
        Дата | Этап | Соперник | Счет | | Место

        Args:
            team_url: URL страницы команды.

        Returns:
            Список объектов Match.
        """
        logger.info("[team_matches] Загрузка матчей команды: %s", team_url)

        try:
            html = await self._fetch_page(team_url)
            soup = self._parse_html(html)
        except SiteParserError as e:
            logger.error("[team_matches] Не удалось загрузить страницу: %s", e)
            _debug_save("", "team_matches_error", extra=team_url)
            return []

        logger.debug("[team_matches] HTML размер: %d байт", len(html))

        # Извлекаем название команды для логов
        team_name = self._extract_current_team_name(soup) or "unknown"

        matches = self._extract_team_matches_from_table_box(soup, team_url)

        if matches:
            # Статистика по статусам
            finished = sum(1 for m in matches if m.is_finished)
            scheduled = sum(1 for m in matches if m.status == "scheduled")
            unknown = sum(1 for m in matches if m.status == "unknown")
            live = sum(1 for m in matches if m.is_live)

            logger.info(
                "[team_matches] Команда '%s' найдено матчей: %d "
                "(finished=%d, scheduled=%d, unknown=%d, live=%d)",
                team_name, len(matches), finished, scheduled, unknown, live
            )
        else:
            logger.warning(
                "[team_matches] Команда '%s' — матчи не найдены. "
                "Пробую fallback парсинг...",
                team_name,
            )
            _debug_save(html, "team_matches_empty", extra=team_name)

            # Fallback: пробуем общий парсинг страницы
            matches = self._extract_matches_from_page(soup)
            if matches:
                logger.info(
                    "[team_matches] Fallback нашёл %d матчей", len(matches)
                )
            else:
                logger.warning(
                    "[team_matches] Команда '%s' — ни один метод не нашёл матчей. "
                    "URL: %s",
                    team_name, team_url,
                )

        return matches

    def _extract_team_matches_from_table_box(
        self, soup: BeautifulSoup, team_url: str
    ) -> list[Match]:
        """Извлечь матчи команды из таблицы class="table_box_row".

        Формат строки:
        Дата | Этап | Соперник | Счет | | Место

        Args:
            soup: BeautifulSoup объект.
            team_url: URL страницы команды (для определения home/away).

        Returns:
            Список объектов Match.
        """
        matches: list[Match] = []
        seen_ids: set[str] = set()

        # Извлекаем ID текущей команды из URL
        team_id_match = re.search(r"/teams/(\d+)/", team_url)
        current_team_id = team_id_match.group(1) if team_id_match else None

        # Находим название текущей команды из заголовка страницы
        current_team_name = self._extract_current_team_name(soup)

        for table in soup.find_all("table", class_="table_box_row"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            # Первая строка — заголовок: Дата | Этап | Соперник | Счет | | Место
            # Проверяем что это таблица матчей
            header_texts = [clean_text(td.get_text()).lower() for td in rows[0].find_all(["td", "th"])]
            has_date_col = any("дата" in t for t in header_texts)
            has_opponent_col = any("соперник" in t for t in header_texts)
            has_score_col = any("счет" in t for t in header_texts)

            if not (has_date_col and has_opponent_col and has_score_col):
                continue

            # Парсим строки матчей
            for row in rows[1:]:
                match = self._parse_team_match_row(row, current_team_name, team_url)
                if match and match.id not in seen_ids:
                    matches.append(match)
                    seen_ids.add(match.id)

            if matches:
                break

        return matches

    def _extract_current_team_name(self, soup: BeautifulSoup) -> str:
        """Извлечь название текущей команды из страницы.

        Стратегии (по приоритету):
        1. Тег <title> — содержит 'команды "Название" Город'
        2. Текст рядом со ссылкой "Расписание"
        3. Ссылка с именем команды в заголовке страницы

        Args:
            soup: BeautifulSoup объект.

        Returns:
            Название команды или пустая строка.
        """
        # Стратегия 1: <title> — самый надёжный источник
        title_tag = soup.find("title")
        if title_tag:
            title_text = title_tag.get_text()
            m = re.search(r'команды\s+"([^"]+)"\s*([^\-–—]+)', title_text, re.IGNORECASE)
            if m:
                name_part = m.group(1)
                city_part = m.group(2).strip().rstrip(" -–—")
                if city_part:
                    return f"{name_part} {city_part}"
                return name_part

        # Стратегия 2: текст рядом со ссылкой "Расписание"
        for link in soup.find_all("a", href=True):
            if "расписание" in link.get_text().lower():
                # Ищем вверх по дереву до div с именем команды
                parent = link.parent
                for _ in range(4):
                    if parent is None:
                        break
                    text = parent.get_text()
                    # Ищем текст в кавычках
                    m = re.search(r'"([^"]+)"\s*([^\d(]*?)\s*(?:место|\d|Расписание)', text)
                    if m:
                        name_part = m.group(1)
                        city_part = m.group(2).strip()
                        if city_part:
                            return f"{name_part} {city_part}"
                        return name_part
                    parent = parent.parent

        # Стратегия 3: первая ссылка с именем команды в верху страницы
        for link in soup.find_all("a", href=True):
            text = link.get_text().strip()
            if text and len(text) >= 3 and "расписание" not in text.lower():
                href = link.get("href", "").lower()
                if "/teams/" in href:
                    return text

        return ""

    def _parse_team_match_row(
        self, row: Tag, current_team_name: str, team_url: str
    ) -> Optional[Match]:
        """Распарсить строку матча из таблицы команды.

        Реальный формат на сайте (table_box_row):
        Дата | Этап | Соперник | Счёт | | Место(стадион)

        ВАЖНО: Счёт на странице команды показывается ОТ ЛИЦА КОМАНДЫ:
          "2:1" = команда забила 2, пропустила 1 (независимо от home/away).
        Суффикс: В = победа, П = поражение, Н = ничья.
        Колонка «Место» содержит стадион, НЕ home/away.

        Поэтому:
          home_team = текущая команда (всегда)
          away_team = соперник
          home_score = голы текущей команды
          away_score = голы соперника

        Это корректно для _calc_form_metrics, который проверяет
        m.home_team == team_name и использует home_score/away_score.

        Args:
            row: Тег <tr>.
            current_team_name: Название текущей команды.
            team_url: URL страницы команды.

        Returns:
            Match или None.
        """
        cells = row.find_all(["td", "th"])
        if len(cells) < 4:
            return None

        # Дата
        date_text = clean_text(cells[0].get_text())
        match_date = self._parse_team_date(date_text)

        # Этап
        round_text = clean_text(cells[1].get_text()) if len(cells) > 1 else ""

        # Соперник
        opponent_raw = clean_text(cells[2].get_text()) if len(cells) > 2 else ""
        opponent_name = self._split_team_name(opponent_raw)

        # Счёт: "2:1В", "3:7П", "1:1Н", "?-?"
        score_raw = clean_text(cells[3].get_text()) if len(cells) > 3 else ""

        if not opponent_name or len(opponent_name) < 2:
            return None

        # Суффикс
        result_suffix = ""
        for ch in reversed(score_raw):
            if ch in ("В", "Н", "П"):
                result_suffix = ch
                break

        # Boxscore ссылка
        score_cell = cells[3]
        score_link = score_cell.find("a", href=True) if score_cell else None
        is_preview = False
        if score_link:
            href = score_link.get("href", "")
            is_preview = "/preview/" in href

        # Парсим счёт
        home_score: int | None = None
        away_score: int | None = None
        status = "scheduled"

        score_m = re.match(r"^(\d+)\s*[:\-]\s*(\d+)", score_raw)
        if score_m:
            home_score = int(score_m.group(1))
            away_score = int(score_m.group(2))
            status = "finished"
        elif "+:-" in score_raw or "-:+" in score_raw:
            status = "finished"
        elif score_raw == "?-?":
            status = "scheduled" if match_date and match_date >= datetime.now() else "unknown"

        # ── home_team = текущая команда (всегда) ──
        # Счёт на странице команды ВСЕГДА от её лица (забито:пропущено).
        # Это НЕ фактический home:away матча.
        home_team = current_team_name if current_team_name else opponent_name
        away_team = opponent_name if current_team_name else "—"

        if not home_team or not away_team:
            return None

        if match_date is None and home_score is None:
            return None

        if home_score is None and match_date:
            if match_date < datetime.now():
                status = "unknown"
            else:
                status = "scheduled"

        # Стадион — последняя ячейка
        venue = ""
        if len(cells) > 4:
            for ci in range(len(cells) - 1, 3, -1):
                venue_text = clean_text(cells[ci].get_text())
                if venue_text:
                    for keyword in ["Дома", "Выезд"]:
                        venue_text = venue_text.replace(keyword, "").strip()
                    if venue_text:
                        venue = venue_text
                    break

        team_id_m = re.search(r"/teams/(\d+)/", team_url)
        team_id_part = team_id_m.group(1) if team_id_m else "unknown"

        date_part = match_date.strftime("%Y%m%d") if match_date else "nodate"
        match_id = f"{home_team}_{away_team}_{date_part}_{team_id_part}"

        return Match(
            id=match_id,
            home_team=home_team,
            away_team=away_team,
            match_date=match_date,
            status=status,
            home_score=home_score,
            away_score=away_score,
            round=round_text if round_text else None,
            venue=venue if venue else None,
        )

    def _parse_team_date(self, date_text: str) -> datetime | None:
        """Распарсить дату из формата страницы команды.

        Форматы:
        - "15.03.2026, Вс, 16:00" (с пробелами)
        - "15.03.2026,Вс,18:00" (без пробелов)
        - "19.04.2026, Вс" (без времени)
        - "17.05.2025" (просто дата)

        Args:
            date_text: Текст даты.

        Returns:
            datetime или None.
        """
        if not date_text:
            return None

        # Убираем пробелы после запятых для унификации
        normalized = re.sub(r",\s*", ",", date_text.strip())

        # Пробуем формат "DD.MM.YYYY,Дд,HH:MM"
        m = re.match(r"(\d{2})\.(\d{2})\.(\d{4}),\w+,(\d{2}):(\d{2})", normalized)
        if m:
            try:
                return datetime(
                    int(m.group(3)), int(m.group(2)),
                    int(m.group(1)), int(m.group(4)), int(m.group(5))
                )
            except ValueError:
                pass

        # Пробуем "DD.MM.YYYY,Дд" без времени
        m = re.match(r"(\d{2})\.(\d{2})\.(\d{4}),\w+", normalized)
        if m:
            try:
                return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass

        # Пробуем стандартный парсинг
        return parse_russian_date(date_text)

    def _extract_matches_from_team_page(self, soup: BeautifulSoup) -> list[Match]:
        """Агрессивный парсинг матчей со страницы команды.

        Ищет паттерны:
        - Строки/блоки с датой + 1-2 ссылки на команды + счёт
        - Секции «Результаты» / «Календарь» / «Расписание»
        - Любой блок, содержащий дату и хотя бы одну ссылку на соперника
        - Fallback: построчный парсинг текста страницы

        Args:
            soup: BeautifulSoup объект.

        Returns:
            Список объектов Match.
        """
        matches: list[Match] = []
        seen_ids: set[str] = set()

        # Определяем контекст страницы — ищем секции с матчами
        section_selectors = [
            "div.results",
            "div.fixtures",
            "div.calendar",
            "div.matches",
            "div.scheduled",
            "div.fixtures-results",
            "#results",
            "#fixtures",
            "#calendar",
            "#matches",
            "section.results",
            "section.fixtures",
            "div.kalendar",
            "div.raspisanie",
            "#kalendar",
        ]

        sections: list[Tag] = []
        for sel in section_selectors:
            sections.extend(soup.select(sel))

        # Если специфичные секции не найдены — берём основной контент
        if not sections:
            for sel in ["div.content", "div.main", "#content", "#main", "article"]:
                block = soup.select_one(sel)
                if block:
                    sections.append(block)

        if not sections:
            sections = [soup]

        # Ищем матчевые паттерны внутри секций
        for section in sections:
            # Стратегия A: таблицы внутри секции
            for table in section.find_all("table"):
                if self._is_navigation_table(table):
                    continue
                for row in table.find_all("tr"):
                    match = self._parse_match_element(row)
                    if match and match.id not in seen_ids:
                        matches.append(match)
                        seen_ids.add(match.id)

            if matches:
                break

            # Стратегия B: div/li блоки внутри секции — ищем матчевые карточки
            for tag_name in ["div", "li", "tr"]:
                for el in section.find_all(tag_name):
                    match = self._parse_match_element(el)
                    if match and match.id not in seen_ids:
                        matches.append(match)
                        seen_ids.add(match.id)

            if matches:
                break

            # Стратегия C: Ищем блоки, содержащие дату + ссылку + счёт
            for tag_name in ["div", "li"]:
                for el in section.find_all(tag_name):
                    match = self._try_parse_match_block(el)
                    if match and match.id not in seen_ids:
                        matches.append(match)
                        seen_ids.add(match.id)

            if matches:
                break

        # Стратегия D (fallback): построчный парсинг — ищем паттерн
        # «дата текст команда — команда счёт» в plain text
        if not matches:
            matches = self._extract_matches_from_plain_text(soup, seen_ids)

        return matches

    def _extract_matches_from_plain_text(
        self, soup: BeautifulSoup, seen_ids: set[str]
    ) -> list[Match]:
        """Построчный парсинг матчей из plain text страницы.

        Ищет строки, содержащие:
        - дату (DD.MM.YYYY или DD.MM)
        - хотя бы одну ссылку на команду
        - опционально счёт (X:Y или X-Y)

        Args:
            soup: BeautifulSoup объект.
            seen_ids: Уже найденные ID матчей.

        Returns:
            Список объектов Match.
        """
        matches: list[Match] = []

        # Берём основной контент
        content = None
        for sel in ["div.content", "div.main", "#content", "#main", "article"]:
            block = soup.select_one(sel)
            if block:
                content = block
                break
        if content is None:
            content = soup

        # Ищем таблицы — это наиболее вероятный контейнер матчей
        for table in content.find_all("table"):
            if self._is_navigation_table(table):
                continue
            for row in table.find_all("tr"):
                if self._is_navigation_table(row):
                    continue
                match = self._parse_match_element(row)
                if match and match.id not in seen_ids:
                    matches.append(match)
                    seen_ids.add(match.id)

        if matches:
            return matches

        # Fallback: ищем все div-блоки с классами содержащими match/fixture/calendar
        for tag_name in ["div", "li", "p"]:
            for el in content.find_all(tag_name):
                cls = el.get("class", [])
                cls_str = " ".join(str(c) for c in cls).lower()
                if any(
                    kw in cls_str
                    for kw in ["match", "fixture", "calendar", "game", "result",
                               "kalendar", "raspisanie", "match-item", "row"]
                ):
                    match = self._try_parse_match_block(el)
                    if match and match.id not in seen_ids:
                        matches.append(match)
                        seen_ids.add(match.id)

        return matches

    def _try_parse_match_block(self, el: Tag) -> Optional[Match]:
        """Попытаться распознать блок как матч.

        Критерии:
        - Есть дата (в блоке или родительском заголовке)
        - Есть хотя бы 1 ссылка на команду (не навигация)
        - Есть счёт ИЛИ ещё одна ссылка на команду
        - Не слишком много ссылок (не контейнер списка)

        Args:
            el: BeautifulSoup тег.

        Returns:
            Match или None.
        """
        # Фильтр: слишком много ссылок — это контейнер, не матч
        links = el.find_all("a", href=True)
        if len(links) > 8:
            return None

        # Слишком длинный текст — это не атомарный матч
        if len(el.get_text()) > 400:
            return None

        texts = [clean_text(s) for s in el.stripped_strings if clean_text(s)]
        if len(texts) < 2:
            return None

        # Ищем дату — сначала в самом блоке
        match_date: datetime | None = None
        for text in texts:
            parsed = parse_russian_date(text)
            if parsed:
                match_date = parsed
                break

        # Если не нашли — ищем в родительских заголовках (до 3 уровней)
        if match_date is None:
            parent = el.parent
            depth = 0
            while parent and depth < 3:
                for heading in parent.find_all(
                    ["h3", "h4", "h5", "div", "span"], limit=5
                ):
                    cls = heading.get("class", [])
                    tag = heading.name
                    if tag in ("h3", "h4", "h5") or any(
                        c in str(cls).lower()
                        for c in ("date", "header", "title", "day", "data")
                    ):
                        t = clean_text(heading.get_text())
                        parsed = parse_russian_date(t)
                        if parsed:
                            match_date = parsed
                            break
                    if parsed_date := parse_russian_date(clean_text(heading.get_text())):
                        match_date = parsed_date
                        break
                if match_date:
                    break
                parent = parent.parent
                depth += 1

        # Ищем ссылки-команды — ослабленный фильтр
        team_links: list[str] = []
        for link in links:
            name = clean_text(link.get_text())
            href_lower = link.get("href", "").lower()

            # Пропускаем навигацию и служебные ссылки
            skip = [
                "tournament", "league", "protocol", "statistic",
                "stats", "report", "summary", "details", "preview",
                "standings", "tables", "news", "article",
            ]
            if any(s in href_lower for s in skip):
                continue
            if not name or len(name) < 2:
                continue
            if _looks_like_score(name):
                continue
            # Не отбрасываем через _is_navigation_text — он слишком строг
            team_links.append(name)

        # Ищем счёт
        home_score: int | None = None
        away_score: int | None = None
        for text in texts:
            m = re.match(r"^(\d+)\s*[:\-]\s*(\d+)$", text)
            if m:
                home_score = int(m.group(1))
                away_score = int(m.group(2))
                break

        # Валидация: нужны хотя бы 1-2 команды
        if not team_links:
            return None

        home_team: str = ""
        away_team: str = ""

        if len(team_links) >= 2:
            home_team = team_links[0]
            away_team = team_links[1]
        elif len(team_links) == 1:
            # Одна команда + счёт — матч валиден
            if home_score is not None and away_score is not None:
                home_team = team_links[0]
                away_team = "—"
            elif match_date:
                # Одна команда + дата — тоже валиден как предстоящий матч
                home_team = team_links[0]
                away_team = "—"
            else:
                return None
        else:
            return None

        if home_team == away_team:
            return None

        # Определяем статус
        if home_score is not None and away_score is not None:
            status = "finished"
        elif match_date and match_date < datetime.now():
            status = "unknown"
        else:
            status = "scheduled"

        date_part = match_date.strftime("%Y%m%d") if match_date else "nodate"
        match_id = f"{home_team}_{away_team}_{date_part}"

        return Match(
            id=match_id,
            home_team=home_team,
            away_team=away_team,
            match_date=match_date,
            status=status,
            home_score=home_score,
            away_score=away_score,
        )

    async def get_team_upcoming_matches(self, team_url: str) -> list[Match]:
        """Получить предстоящие матчи команды."""
        all_matches = await self.get_team_matches(team_url)
        now = datetime.now()
        upcoming = [m for m in all_matches if m.match_date is None or m.match_date >= now]
        return sorted(upcoming, key=lambda m: m.match_date or datetime.max)

    async def get_team_recent_results(self, team_url: str) -> list[Match]:
        """Получить последние результаты команды."""
        all_matches = await self.get_team_matches(team_url)
        results = [m for m in all_matches if m.is_finished]
        return sorted(results, key=lambda m: m.match_date or datetime.min, reverse=True)

    async def get_league_upcoming_matches(self, league_url: str) -> list[Match]:
        """Получить предстоящие матчи лиги."""
        logger.info("Получение предстоящих матчей лиги: %s", league_url)

        try:
            html = await self._fetch_page(league_url)
            soup = self._parse_html(html)
        except SiteParserError as e:
            logger.error("Не удалось загрузить страницу матчей лиги: %s", e)
            return []

        all_matches = self._extract_matches_from_page(soup)
        now = datetime.now()
        upcoming = [m for m in all_matches if m.match_date is None or m.match_date >= now]
        return sorted(upcoming, key=lambda m: m.match_date or datetime.max)

    async def get_league_recent_results(self, league_url: str) -> list[Match]:
        """Получить последние результаты лиги."""
        logger.info("Получение последних результатов лиги: %s", league_url)

        try:
            html = await self._fetch_page(league_url)
            soup = self._parse_html(html)
        except SiteParserError as e:
            logger.error("Не удалось загрузить страницу результатов лиги: %s", e)
            return []

        all_matches = self._extract_matches_from_page(soup)
        results = [m for m in all_matches if m.is_finished]
        return sorted(results, key=lambda m: m.match_date or datetime.min, reverse=True)

    def _find_matches_container(self, soup: BeautifulSoup) -> list[Tag]:
        """Найти HTML-блоки, содержащие матчи.

        Возвращает список контейнеров в порядке приоритета.
        Если точный контейнер не найден — возвращает fallback-варианты.

        Returns:
            Список тегов-контейнеров (может быть пустым).
        """
        containers: list[Tag] = []

        # Приоритет 1: Точные селекторы матчевых блоков
        for selector in [
            "table.matches",
            "table.match-table",
            "table.scheduled",
            "table.fixtures",
            "table.results",
            "div.matches-list",
            "div.fixtures",
            "div.match-list",
            "div.scheduled-matches",
            "#matches",
            "#fixtures",
            "#results",
            "table.calendar",
            "div.calendar",
            "div.kalendar",
            "div.raspisanie",
            "#calendar",
            "#kalendar",
            "table.fixtures-results",
        ]:
            container = soup.select_one(selector)
            if container:
                containers.append(container)

        if containers:
            return containers

        # Приоритет 2: Любой блок с id/class, содержащим match/fixture/scheduled/results/calendar
        for pattern in [
            "match", "fixture", "scheduled", "calendar", "game",
            "kalendar", "raspisanie", "rezul", "fixtures",
        ]:
            for tag_name in ["table", "div", "section", "ul"]:
                for el in soup.find_all(tag_name, id=re.compile(pattern, re.IGNORECASE)):
                    containers.append(el)
                for el in soup.find_all(
                    tag_name, class_=re.compile(pattern, re.IGNORECASE)
                ):
                    if el not in containers:
                        containers.append(el)

        if containers:
            return containers

        # Приоритет 3: Ищем секции по заголовкам (h2/h3 с «матч», «календарь» и т.д.)
        match_keywords = ["матч", "календарь", "расписани", "результат", "fixture"]
        for keyword in match_keywords:
            for heading in soup.find_all(["h2", "h3", "h4"]):
                if keyword in heading.get_text().lower():
                    # Берём следующий за заголовком элемент — это контейнер
                    sibling = heading.find_next_sibling()
                    if sibling and sibling.name in ("table", "div", "section", "ul"):
                        if sibling not in containers:
                            containers.append(sibling)

        if containers:
            return containers

        # Приоритет 4: Основной контент страницы — ищем таблицы в нём
        for selector in ["div.content", "div.main", "#content", "#main", "article"]:
            main_block = soup.select_one(selector)
            if main_block:
                tables = main_block.find_all("table")
                if tables:
                    return tables

        return []

    def _extract_matches_from_page(self, soup: BeautifulSoup) -> list[Match]:
        """Извлечь матчи со страницы.

        Стратегии (по приоритету):
        1. Таблица class="scoreboard" — общее расписание
        2. Контейнеры матчей через _find_matches_container()
        3. Матчевые карточки (div.match-card и т.д.)
        4. Все таблицы на странице (fallback)

        Args:
            soup: BeautifulSoup объект.

        Returns:
            Список объектов Match.
        """
        matches: list[Match] = []
        seen_ids: set[str] = set()

        # Стратегия 1: scoreboard — основное расписание сайта
        scoreboard_matches = self._extract_scoreboard_matches(soup)
        if scoreboard_matches:
            return scoreboard_matches

        # Стратегия 2: Конкретные контейнеры матчей → <tr>
        containers = self._find_matches_container(soup)
        for container in containers:
            for row in container.find_all("tr"):
                match = self._parse_match_element(row)
                if match and match.id not in seen_ids:
                    matches.append(match)
                    seen_ids.add(match.id)

        if matches:
            return matches

        # Стратегия 3: Матчевые карточки (div, li)
        card_matches = self._extract_match_cards(soup)
        if card_matches:
            return card_matches

        # Стратегия 4: Таблицы в основном контенте
        for selector in ["div.content", "div.main", "#content", "#main", "article"]:
            main_block = soup.select_one(selector)
            if main_block:
                for table in main_block.find_all("table"):
                    if self._is_navigation_table(table):
                        continue
                    for row in table.find_all("tr"):
                        match = self._parse_match_element(row)
                        if match and match.id not in seen_ids:
                            matches.append(match)
                            seen_ids.add(match.id)

        if matches:
            return matches

        # Стратегия 5: Все таблицы на странице (fallback)
        for table in soup.find_all("table"):
            if self._is_navigation_table(table):
                continue
            for row in table.find_all("tr"):
                match = self._parse_match_element(row)
                if match and match.id not in seen_ids:
                    matches.append(match)
                    seen_ids.add(match.id)

        return matches

    def _extract_scoreboard_matches(self, soup: BeautifulSoup) -> list[Match]:
        """Извлечь матчи из таблицы class="scoreboard".

        Формат: время | home_team | score | away_team | stadium

        Args:
            soup: BeautifulSoup объект.

        Returns:
            Список объектов Match.
        """
        matches: list[Match] = []
        seen_ids: set[str] = set()

        for table in soup.find_all("table", class_="scoreboard"):
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) < 4:
                    continue

                # Время: "17:00"
                time_text = clean_text(cells[0].get_text())

                # Home team — ссылка
                home_link = cells[1].find("a", href=True)
                home_name = clean_text(home_link.get_text()) if home_link else clean_text(cells[1].get_text())

                # Score — ссылка на preview/boxscore
                score_cell = cells[2]
                score_link = score_cell.find("a", href=True)
                score_text = clean_text(score_cell.get_text())

                # Away team — ссылка
                away_link = cells[3].find("a", href=True)
                away_name = clean_text(away_link.get_text()) if away_link else clean_text(cells[3].get_text())

                # Стадион
                venue = ""
                if len(cells) > 4:
                    venue_cell = cells[4].find("a", href=True)
                    venue = clean_text(venue_cell.get_text()) if venue_cell else clean_text(cells[4].get_text())

                if not home_name or not away_name or len(home_name) < 2 or len(away_name) < 2:
                    continue

                # Парсим счёт
                home_score: int | None = None
                away_score: int | None = None
                status = "scheduled"

                score_m = re.match(r"^(\d+)\s*[:\-]\s*(\d+)", score_text)
                if score_m:
                    home_score = int(score_m.group(1))
                    away_score = int(score_m.group(2))
                    status = "finished"

                # Парсим время — добавляем сегодняшнюю дату
                match_date: datetime | None = None
                time_m = re.match(r"(\d{2}):(\d{2})", time_text)
                if time_m:
                    now = datetime.now()
                    match_date = now.replace(
                        hour=int(time_m.group(1)),
                        minute=int(time_m.group(2)),
                        second=0,
                        microsecond=0
                    )
                    if home_score is not None:
                        status = "finished"
                    elif match_date < datetime.now():
                        status = "unknown"

                # Boxscore URL
                match_url = ""
                if score_link:
                    match_url = self._make_absolute_url(score_link.get("href", ""))

                match_id = f"{home_name}_{away_name}_{match_date.strftime('%Y%m%d_%H%M') if match_date else 'nodate'}"
                if match_id in seen_ids:
                    continue
                seen_ids.add(match_id)

                matches.append(Match(
                    id=match_id,
                    home_team=self._split_team_name(home_name),
                    away_team=self._split_team_name(away_name),
                    match_date=match_date,
                    status=status,
                    home_score=home_score,
                    away_score=away_score,
                    url=match_url if match_url else None,
                    venue=venue if venue else None,
                ))

        return matches

    def _extract_match_cards(self, soup: BeautifulSoup) -> list[Match]:
        """Извлечь матчи из карточек (div/li/section), а не из таблиц.

        Ищем атомарные матчевые блоки, а не общие контейнеры разделов.

        Args:
            soup: BeautifulSoup объект.

        Returns:
            Список объектов Match.
        """
        matches: list[Match] = []
        seen_ids: set[str] = set()

        # Ищем карточки матчей по конкретным классам
        card_selectors = [
            "div.match-card",
            "div.match-item",
            "div.fixture",
            "div.game-card",
            "div.match-block",
            "div.result-card",
            "li.match-card",
            "li.fixture",
            "div.calendar-item",
        ]

        cards: list[Tag] = []
        for sel in card_selectors:
            cards.extend(soup.select(sel))

        # Fallback: ищем div/li с match/fixture/game в class, но только
        # атомарные блоки (не общие контейнеры)
        if not cards:
            for tag_name in ["div", "li"]:
                for el in soup.find_all(
                    tag_name,
                    class_=re.compile(r"(match|fixture|game|result)", re.IGNORECASE),
                ):
                    # Фильтруем большие контейнеры — это разделы, а не карточки
                    if self._is_match_container_section(el):
                        continue
                    if el not in cards:
                        cards.append(el)

        for card in cards:
            match = self._parse_match_card(card)
            if match and match.id not in seen_ids:
                matches.append(match)
                seen_ids.add(match.id)

        return matches

    def _is_match_container_section(self, el: Tag) -> bool:
        """Проверить, является ли элемент контейнером раздела (не карточкой).

        Контейнер раздела — это большой блок, содержащий много ссылок
        или вложенные матчевые карточки.

        Args:
            el: BeautifulSoup тег.

        Returns:
            True если это контейнер раздела, а не атомарная карточка.
        """
        # Слишком много ссылок — это контейнер списка
        links = el.find_all("a", href=True)
        if len(links) > 5:
            return True

        # Содержит вложенные match-card/fixture — значит это обёртка
        if el.select("div.match-card, div.match-item, div.fixture, div.game-card"):
            return True

        # Слишком много текста (>500 символов) — скорее раздел
        text_len = len(el.get_text())
        if text_len > 500:
            return True

        return False

    def _parse_match_card(self, card: Tag) -> Optional[Match]:
        """Распарсить карточку матча (div/li).

        Ищем:
        - 2 ссылки на команды (строго отфильтрованные)
        - опционально дату (только внутри карточки или в ближайшем заголовке секции)
        - опционально счёт

        Дата опциональна: если есть 2 команды + счёт, матч валиден без даты.

        Args:
            card: Тег карточки.

        Returns:
            Match или None.
        """
        # 1. Ищем дату ТОЛЬКО внутри карточки
        match_date: datetime | None = None
        for text in card.stripped_strings:
            t = clean_text(text)
            parsed = parse_russian_date(t)
            if parsed:
                match_date = parsed
                break

        # 2. Если не нашли — ищем в ближайшем заголовке секции (1 уровень)
        if match_date is None:
            parent = card.parent
            if parent:
                for heading in parent.find_all(["h3", "h4", "h5", "div"]):
                    cls = heading.get("class", [])
                    tag = heading.name
                    if tag in ("h3", "h4", "h5") or any(
                        c in str(cls).lower() for c in ("date", "header", "title", "day")
                    ):
                        t = clean_text(heading.get_text())
                        parsed = parse_russian_date(t)
                        if parsed:
                            match_date = parsed
                            break

        # 3. Ищем и фильтруем ссылки — только те, что похожи на команды
        links = card.find_all("a", href=True)
        candidates: list[tuple[str, Tag]] = []  # (name, link)

        for link in links:
            name = clean_text(link.get_text())
            if not name or not _looks_like_team_name(name):
                continue

            # Отбрасываем ссылки на турнир/протокол/статистику по href
            href_lower = link.get("href", "").lower()
            skip_in_href = [
                "tournament", "league", "protocol", "statistic",
                "stats", "report", "summary", "details", "preview",
                "standings", "tables", "news", "article",
            ]
            if any(skip in href_lower for skip in skip_in_href):
                continue

            candidates.append((name, link))

        home_team: str = ""
        away_team: str = ""

        if len(candidates) >= 2:
            # Если больше 2 кандидатов — выбираем наиболее вероятные
            # По приоритету: ссылки, ближайшие к счёту (по DOM-дереву)
            if len(candidates) > 2:
                # Ищем счёт в карточке
                score_el = None
                for text_node in card.stripped_strings:
                    t = clean_text(text_node)
                    if re.match(r"^\d+\s*[:\-]\s*\d+$", t):
                        # Нашли элемент со счётом — находим сам тег
                        for el in card.find_all(string=re.compile(r"^\d+\s*[:\-]\s*\d+$")):
                            score_el = el.parent
                            break
                        break

                if score_el:
                    # Сортируем кандидатов по расстоянию до счёта в DOM
                    def dom_distance(pair: tuple[str, Tag]) -> int:
                        _, lnk = pair
                        # Считаем количество родительских элементов до общей
                        dist = 0
                        cur: Tag | None = lnk
                        while cur and cur is not score_el:
                            dist += 1
                            cur = cur.parent
                            if dist > 10:
                                break
                        return dist

                    candidates.sort(key=dom_distance)

            # Берём первые 2
            home_team = candidates[0][0]
            away_team = candidates[1][0]
        else:
            return None

        if home_team.lower() == away_team.lower():
            return None

        # 4. Ищем счёт
        home_score: int | None = None
        away_score: int | None = None
        for text in card.stripped_strings:
            t = clean_text(text)
            m = re.match(r"^(\d+)\s*[:\-]\s*(\d+)$", t)
            if m:
                home_score = int(m.group(1))
                away_score = int(m.group(2))
                break

        # 5. Определяем статус
        if home_score is not None and away_score is not None:
            status = "finished"
        elif match_date and match_date < datetime.now():
            status = "unknown"
        else:
            status = "scheduled"

        date_part = match_date.strftime("%Y%m%d") if match_date else "nodate"
        match_id = f"{home_team}_{away_team}_{date_part}"

        return Match(
            id=match_id,
            home_team=home_team,
            away_team=away_team,
            match_date=match_date,
            status=status,
            home_score=home_score,
            away_score=away_score,
        )

    def _is_navigation_table(self, table: Tag) -> bool:
        """Проверить, является ли таблица навигацией/меню.

        Навигационные таблицы обычно содержат ссылки типа «главная»,
        «новости» и не содержат дат или числовых данных.

        Args:
            table: Тег <table>.

        Returns:
            True если это навигация.
        """
        texts = []
        for cell in table.find_all(["td", "th"]):
            t = clean_text(cell.get_text()).lower()
            if t:
                texts.append(t)

        # Если большинство текстов — навигация, это не таблица матчей
        nav_count = sum(1 for t in texts if _is_navigation_text(t))
        total = len(texts)
        if total > 0 and nav_count / total > 0.5:
            return True
        return False

    def _parse_match_element(self, el: Tag) -> Optional[Match]:
        """Распарсить строку матча (<tr>).

        Валидация:
        - Предпочтительно: дата в строке
        - Fallback: если нет даты, но есть 2 команды + счёт — это матч
        - Разрешены строки с 2+ ячейками (компактные таблицы)
        - Названия команд не навигация и не счёт

        Args:
            el: BeautifulSoup тег (обычно <tr>).

        Returns:
            Match или None.
        """
        cells = el.find_all(["td", "th"])
        if len(cells) < 2:
            return None

        texts = [clean_text(c.get_text()) for c in cells]

        # 1. Ищем дату
        match_date: datetime | None = None
        for text in texts:
            parsed = parse_russian_date(text)
            if parsed:
                match_date = parsed
                break

        # 2. Ищем ссылки на команды — ослабленный фильтр
        links = el.find_all("a", href=True)
        team_links: list[str] = []
        for link in links:
            name = clean_text(link.get_text())
            # Ослабленная фильтрация: пропускаем если похоже на команду
            if name and len(name) >= 2 and not _looks_like_score(name):
                # Проверяем только явную навигацию
                lower = name.lower()
                skip_words = {
                    "главная", "новости", "турниры", "участники",
                    "контакты", "о сайте", "поиск", "меню",
                    "статистика", "таблицы", "результаты",
                    "home", "news", "tournaments", "tables",
                    "participants", "contacts", "about",
                    "протокол", "статистика", "отчёт",
                }
                if lower in skip_words:
                    continue
                team_links.append(name)

        home_team: str = ""
        away_team: str = ""

        if len(team_links) >= 2:
            home_team = team_links[0]
            away_team = team_links[1]
        elif len(team_links) == 1:
            # Одна ссылка — пробуем найти вторую команду из текста ячеек
            home_team = team_links[0]
            candidates = []
            for text in texts:
                t = text.strip()
                if not t:
                    continue
                # Пропускаем даты, счёты, числа, навигацию
                if parse_russian_date(t):
                    continue
                if _looks_like_score(t):
                    continue
                if re.fullmatch(r"[\d\./\-:]+", t):
                    continue
                if len(t) < 2:
                    continue
                # Оставляем только тексты с буквами
                if re.search(r"[a-zA-Zа-яА-ЯёЁ]", t):
                    candidates.append(t)
            if candidates:
                # Берём первый кандидат, который не совпадает с home_team
                for c in candidates:
                    if c.lower() != home_team.lower():
                        away_team = c
                        break
                if not away_team:
                    # Все кандидаты совпали — значит вторая команда не найдена
                    # Но если есть счёт — матч всё равно валиден
                    pass
            # Если нет второй команды, но есть счёт — всё равно считаем матчем
            # (away_team останется пустым, обработаем ниже)
        elif len(team_links) == 0:
            # Нет ссылок — извлекаем команды из текста
            candidates = []
            for text in texts:
                t = text.strip()
                if not t:
                    continue
                if parse_russian_date(t):
                    continue
                if _looks_like_score(t):
                    continue
                if re.fullmatch(r"[\d\./\-:]+", t):
                    continue
                if len(t) < 2:
                    continue
                if _is_navigation_text(t):
                    continue
                if re.search(r"[a-zA-Zа-яА-ЯёЁ]", t):
                    candidates.append(t)
            if len(candidates) >= 2:
                home_team = candidates[0]
                away_team = candidates[1]
            else:
                return None
        else:
            return None

        if not away_team:
            # Вторая команда не найдена — матч невалиден
            return None

        if home_team.lower() == away_team.lower():
            return None
        if _looks_like_score(home_team) or _looks_like_score(away_team):
            return None

        # 3. Ищем счёт
        home_score: int | None = None
        away_score: int | None = None
        for text in texts:
            m = re.match(r"^(\d+)\s*[:\-]\s*(\d+)$", text)
            if m:
                home_score = int(m.group(1))
                away_score = int(m.group(2))
                break

        # 4. Если нет даты и нет счёта — не матч
        if match_date is None and home_score is None and away_score is None:
            return None

        # 5. Определяем статус
        if home_score is not None and away_score is not None:
            status = "finished"
        elif match_date and match_date < datetime.now():
            status = "unknown"
        else:
            status = "scheduled"

        # 6. Генерируем ID
        date_part = match_date.strftime("%Y%m%d") if match_date else "nodate"
        match_id = f"{home_team}_{away_team}_{date_part}"

        return Match(
            id=match_id,
            home_team=home_team,
            away_team=away_team,
            match_date=match_date,
            status=status,
            home_score=home_score,
            away_score=away_score,
        )

    # ========================================================================
    # ПОИСК КОМАНД
    # ========================================================================

    async def search_teams(self, query: str) -> list[Team]:
        """Поиск команды по названию.

        Args:
            query: Поисковый запрос.

        Returns:
            Список найденных команд.
        """
        logger.info(f"Поиск команды: {query}")

        # Пробуем поиск на сайте (endpoint может отсутствовать — это нормально)
        soup: BeautifulSoup | None = None
        try:
            html = await self._fetch_page(f"/search?q={quote(query)}")
            soup = self._parse_html(html)
        except SiteParserError:
            # Endpoint /search может не существовать — это не ошибка,
            # просто переходим к fallback-поиску через лиги.
            logger.debug("Поиск на сайте недоступен, используется fallback")
            soup = None

        teams = []
        seen_ids: set[str] = set()

        if soup:
            # Ищем результаты поиска
            for selector in [
                "div.search-results a",
                "div.results a",
                "table.search-table a",
                "a[href*='team']",
                "a[href*='club']",
            ]:
                for link in soup.select(selector):
                    text = clean_text(link.get_text())
                    if query.lower() in text.lower():
                        team = self._extract_team_from_element(link)
                        if team and team.id not in seen_ids:
                            teams.append(team)
                            seen_ids.add(team.id)

            # Fallback: ищем через все лиги
        if not teams:
            leagues = await self.get_leagues()
            # Проходим по всем лигам (кеширование команд делает повторные
            # поиски быстрыми — данные уже в кеше после первого запроса)
            for league in leagues:
                try:
                    league_teams = await self.get_league_teams(league)
                    for team in league_teams:
                        if query.lower() in team.name.lower():
                            if team.id not in seen_ids:
                                teams.append(team)
                                seen_ids.add(team.id)
                except Exception as e:
                    logger.warning("Ошибка поиска в лиге %s: %s", league.name, e)
                    continue

        logger.info(f"Найдено команд по запросу '{query}': {len(teams)}")
        return teams

    # ========================================================================
    # ЗАЯВКА КОМАНДЫ (ROSTER)
    # ========================================================================

    async def get_team_roster(self, team_url: str) -> list:
        """Получить заявку (состав) команды.

        URL заявки строится из URL команды:
          /tournaments/{season}/{tournament_id}/teams/{team_id}/  →
          /tournaments/{season}/{tournament_id}/teams/{team_id}/roster/

        Args:
            team_url: URL страницы команды.

        Returns:
            Список объектов Player.
        """
        from app.models.football import Player

        roster_url = self._build_team_sub_url(team_url, "roster/")
        if not roster_url:
            return []

        logger.info("[roster] Загрузка заявки команды: %s", roster_url)

        try:
            html = await self._fetch_page(roster_url)
            soup = self._parse_html(html)
        except SiteParserError as e:
            logger.error("[roster] Не удалось загрузить страницу: %s", e)
            return []

        logger.debug("[roster] HTML размер: %d байт", len(html))

        players = self._parse_roster_table(soup)

        if not players:
            logger.warning("[roster] Не найдено игроков на странице")
            _debug_save(html, "roster_empty", extra=roster_url)

        logger.info("[roster] Найдено игроков: %d", len(players))
        return players

    def _build_team_sub_url(self, team_url: str, sub_path: str) -> str:
        """Построить URL подраздела команды.

        Из URL команды строит URL подраздела (roster, stats и т.д.):
          /tournaments/2026/3607/teams/6662/  →  .../6662/roster/

        Args:
            team_url: URL страницы команды.
            sub_path: Подраздел (например "roster/", "stats/").

        Returns:
            URL подраздела или пустая строка.
        """
        # Нормализуем — убираем trailing slash
        url = team_url.rstrip("/")
        # Проверяем что URL заканчивается на teams/{id}
        if not re.search(r"/teams/\d+$", url):
            logger.warning("[url_build] Не recognised team URL: %s", team_url)
            return ""
        return url + "/" + sub_path

    def _parse_roster_table(self, soup: BeautifulSoup) -> list:
        """Распарсить таблицу заявки команды.

        Реальная структура (table_box_row):
        № | Имя | Дата рождения | Возраст | Рост | Вес | Дата заявки | |

        Амплуа определяется строками-разделителями:
          <td class="bg_light ...">Вратари</td>
          <td class="bg_light ...">Защитники</td>
          <td class="bg_light ...">Нападающие</td>
          <td class="bg_light ...">Полевые игроки</td>
        """
        from app.models.football import Player

        players: list[Player] = []
        current_position: str | None = None

        for table in soup.find_all("table", class_="table_box_row"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            # Проверяем что это таблица заявки (есть колонка "Имя")
            header_cells = rows[0].find_all(["th", "td"])
            has_name_col = any(
                "имя" in clean_text(c.get_text()).lower()
                for c in header_cells
            )
            if not has_name_col:
                continue

            for row in rows[1:]:
                cells = row.find_all(["td", "th"])

                # Строка-разделитель амплуа (colspan) — проверяем ДО len(cells) < 2
                if len(cells) == 1 and cells[0].get("colspan"):
                    pos_text = clean_text(cells[0].get_text())
                    if pos_text and len(pos_text) < 30:
                        current_position = pos_text
                    continue

                if len(cells) < 2:
                    continue

                # Обычная строка игрока
                player = self._extract_player_from_roster_row(cells, current_position)
                if player:
                    players.append(player)

            if players:
                break  # Нашли правильную таблицу

        return players

    def _extract_player_from_roster_row(self, cells: list, position: str | None):
        """Извлечь игрока из строки таблицы заявки.

        Колонки: № | Имя | Дата рождения | Возраст | Рост | Вес | Дата заявки | |
        """
        from app.models.football import Player

        def get_text(idx: int) -> str:
            if idx < 0 or idx >= len(cells):
                return ""
            return clean_text(cells[idx].get_text())

        def get_int(idx: int) -> int:
            text = get_text(idx)
            nums = re.findall(r"\d+", text)
            return int(nums[0]) if nums else 0

        # Имя — ссылка
        name_link = cells[1].find("a", href=True) if len(cells) > 1 else None
        name = clean_text(name_link.get_text()) if name_link else get_text(1)
        if not name or len(name) < 2:
            return None

        # Номер
        number = None
        num_text = get_text(0).strip()
        if num_text and num_text.isdigit():
            number = int(num_text)

        # Дата рождения
        birth_date = None
        birth_text = get_text(2)
        if birth_text:
            parsed = parse_russian_date(birth_text)
            if parsed:
                birth_date = parsed.date()

        try:
            return Player(
                number=number,
                name=name,
                position=position,
                birth_date=birth_date,
                matches=0,
                goals=0,
            )
        except Exception:
            return None

    # ========================================================================
    # СТАТИСТИКА ИГРОКОВ КОМАНДЫ
    # ========================================================================

    async def get_team_player_stats(self, team_url: str) -> list:
        """Получить статистику игроков команды.

        URL статистики строится из URL команды:
          /tournaments/{season}/{tournament_id}/teams/{team_id}/  →
          /tournaments/{season}/{tournament_id}/teams/{team_id}/stats/

        Args:
            team_url: URL страницы команды.

        Returns:
            Список объектов PlayerStat.
        """
        from app.models.football import PlayerStat

        stats_url = self._build_team_sub_url(team_url, "stats/")
        if not stats_url:
            return []

        logger.info("[player_stats] Загрузка статистики: %s", stats_url)

        try:
            html = await self._fetch_page(stats_url)
            soup = self._parse_html(html)
        except SiteParserError as e:
            logger.error("[player_stats] Не удалось загрузить страницу: %s", e)
            return []

        logger.debug("[player_stats] HTML размер: %d байт", len(html))

        player_stats = self._parse_player_stats_table(soup)

        if not player_stats:
            logger.warning("[player_stats] Не найдено статистики")
            _debug_save(html, "player_stats_empty", extra=stats_url)

        logger.info("[player_stats] Найдено игроков со статистикой: %d", len(player_stats))
        return player_stats

    def _parse_player_stats_table(self, soup: BeautifulSoup) -> list:
        """Распарсить таблицу статистики игроков.

        Реальная структура (table_box_cell m_bottom):
        Имя | Игр | Мин | Голы | Пен | НПен | КК | ЖК | Замены

        Значения: <a href="...">4</a> или <span class="light">0</span>
        или <span class="light"></span> (пусто).
        """
        from app.models.football import PlayerStat

        stats: list[PlayerStat] = []
        seen_names: set[str] = set()

        for table in soup.find_all("table", class_="table_box_cell"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            # Проверяем заголовок
            header_cells = rows[0].find_all(["th", "td"])
            has_name_col = any(
                "имя" in clean_text(c.get_text()).lower()
                for c in header_cells
            )
            if not has_name_col:
                continue

            # Парсим строки
            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue

                stat = self._extract_player_stat_from_stats_row(cells)
                if stat and stat.name not in seen_names:
                    stats.append(stat)
                    seen_names.add(stat.name)

            if stats:
                break

        return stats

    def _extract_player_stat_from_stats_row(self, cells: list):
        """Извлечь статистику из строки таблицы stats.

        Колонки: Имя | Игр | Мин | Голы | Пен | НПен | КК | ЖК | Замены
        """
        from app.models.football import PlayerStat

        def get_cell_value(idx: int) -> str:
            """Получить текст из ячейки, предпочитая <a> над <span>."""
            if idx < 0 or idx >= len(cells):
                return ""
            cell = cells[idx]
            # Сначала ищем <a> с числом
            link = cell.find("a")
            if link:
                text = link.get_text(strip=True)
                if text:
                    return text
            # Затем <span>
            span = cell.find("span")
            if span:
                return span.get_text(strip=True)
            return clean_text(cell.get_text())

        def get_int(idx: int) -> int:
            text = get_cell_value(idx)
            nums = re.findall(r"\d+", text)
            return int(nums[0]) if nums else 0

        # Имя — ссылка
        name_link = cells[0].find("a", href=True) if len(cells) > 0 else None
        name = clean_text(name_link.get_text()) if name_link else get_cell_value(0)
        if not name or len(name) < 2:
            return None

        try:
            return PlayerStat(
                name=name,
                matches=get_int(1),  # Игр
                goals=get_int(3),    # Голы
                assists=0,           # Нет на сайте
                yellow_cards=get_int(7),  # ЖК
                red_cards=get_int(6),     # КК
                minutes=get_int(2),       # Мин
            )
        except Exception:
            return None
