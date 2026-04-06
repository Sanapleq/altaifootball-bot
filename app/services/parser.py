"""Парсер сайта altaifootball.ru.

Этот модуль отвечает за извлечение данных из HTML-страниц сайта.
Вся логика парсинга изолирована здесь — при изменении структуры сайта
нужно править только этот файл и selectors_config.py.

TODO: HTML-структура сайта может измениться. При проблемах с парсингом:
  1. Откройте страницу команды/лиги в браузере.
  2. Посмотрите реальные CSS-классы таблиц матчей и standings.
  3. Обновите селекторы в _find_matches_container / _find_standings_table.
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
from app.utils.dates import parse_russian_date
from app.utils.text import clean_text

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

    Все методы делают HTTP-запросы, парсят HTML и возвращают модели данных.
    При ошибках — логируют и возвращают fallback-значения.
    """

    def __init__(self, base_url: Optional[str] = None) -> None:
        """Инициализация парсера.

        Args:
            base_url: Базовый URL сайта (из настроек по умолчанию).
        """
        self.base_url = base_url or settings.base_url
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Получить или создать HTTP-клиент."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=settings.request_timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                },
            )
        return self._client

    async def close(self) -> None:
        """Закрыть HTTP-клиент."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _fetch_page(self, url: str) -> str:
        """Загрузить HTML-страницу.

        Args:
            url: Относительный или абсолютный URL.

        Returns:
            HTML-содержимое страницы.

        Raises:
            SiteParserError: При ошибке загрузки.
        """
        client = await self._get_client()
        full_url = url if url.startswith("http") else urljoin(self.base_url, url)

        try:
            response = await client.get(full_url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP ошибка при загрузке {full_url}: {e.response.status_code}")
            raise SiteParserError(f"HTTP {e.response.status_code} при загрузке страницы")
        except httpx.RequestError as e:
            logger.error(f"Ошибка запроса к {full_url}: {e}")
            raise SiteParserError(f"Ошибка соединения: {e}")

    def _parse_html(self, html: str) -> BeautifulSoup:
        """Распарсить HTML в BeautifulSoup.

        Args:
            html: HTML-содержимое.

        Returns:
            BeautifulSoup объект.
        """
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

        Основной путь: только ссылки с /tournaments/ в URL +
        строгая проверка через _looks_like_league_name().

        Fallback-пути не должны возвращать мусор.

        Returns:
            Список объектов League.
        """
        logger.info("Получение списка лиг")

        try:
            html = await self._fetch_page("/")
            soup = self._parse_html(html)
        except SiteParserError as e:
            logger.error("Не удалось загрузить страницу лиг: %s", e)
            return []

        leagues: list[League] = []
        seen_urls: set[str] = set()

        # Стратегия 1 (приоритет): ссылки с /tournaments/ — самый надёжный признак
        for link in soup.find_all("a", href=re.compile(r"/tournaments/", re.IGNORECASE)):
            league = self._extract_league_from_link(link, seen_urls)
            if league:
                leagues.append(league)
                seen_urls.add(league.url)

        # Стратегия 2: контейнеры лиг (только если стратегия 1 дала 0)
        if not leagues:
            for selector in [
                "div.leagues",
                "div.tournaments",
                "ul.leagues-list",
                "ul.tournaments-list",
                ".league-list",
                ".tournament-list",
            ]:
                container = soup.select_one(selector)
                if container:
                    for link in container.find_all("a", href=True):
                        league = self._extract_league_from_link(link, seen_urls)
                        if league:
                            leagues.append(league)
                            seen_urls.add(league.url)
                    if leagues:
                        break

        # Финальная очистка: дедупликация + повторная проверка имени
        final: list[League] = []
        seen_final: set[str] = set()
        for lg in leagues:
            if lg.url not in seen_final and _looks_like_league_name(lg.name):
                final.append(lg)
                seen_final.add(lg.url)

        logger.info("Найдено лиг: %d", len(final))
        return final

    def _extract_league_from_link(self, link: Tag, seen_urls: set[str]) -> Optional[League]:
        """Извлечь данные лиги из HTML-ссылки.

        Строгая фильтрация: только ссылки, похожие на турниры.

        Args:
            link: BeautifulSoup тег <a>.
            seen_urls: Уже обработанные URL (для дедупликации).

        Returns:
            League или None.
        """
        href = link.get("href", "")
        text = clean_text(link.get_text())

        if not href or not text:
            return None

        # Дедупликация по URL
        abs_url = self._make_absolute_url(href)
        if abs_url in seen_urls:
            return None

        # Главный критерий: текст должен быть похож на название турнира
        if not _looks_like_league_name(text):
            return None

        # Дополнительная проверка: URL должен содержать tournament/league/season
        href_lower = href.lower()
        url_hints = ["tournament", "league", "season", "turnir", "ligen"]
        if not any(h in href_lower for h in url_hints):
            return None

        league_id = self._extract_id_from_url(href)
        return League(
            id=league_id,
            name=text,
            url=abs_url,
        )

    # ========================================================================
    # КОМАНДЫ
    # ========================================================================

    async def get_league_teams(self, league_url: str) -> list[Team]:
        """Получить список команд лиги.

        Стратегии (по приоритету):
        1. Таблица/список команд (селекторы teams/teams-table)
        2. Турнирная таблица standings — извлекаем команды оттуда
        3. Ссылки с 'team'/'club'/'command' в href
        4. Fallback: общие таблицы/списки в основном контенте страницы
           — извлекаем ссылки, если текст похож на название команды
        """
        logger.info("Получение команд лиги: %s", league_url)

        try:
            html = await self._fetch_page(league_url)
            soup = self._parse_html(html)
        except SiteParserError as e:
            logger.error("Не удалось загрузить страницу команд: %s", e)
            return []

        teams: list[Team] = []
        seen_ids: set[str] = set()

        # Стратегия 1: Ищем таблицу команд по конкретным селекторам
        for selector in [
            "table.teams-table tbody tr",
            "table.teams tr",
            "div.team-item a",
            "a.team-link",
        ]:
            elements = soup.select(selector)
            for el in elements:
                team = self._extract_team_from_element(el)
                if team and team.id not in seen_ids:
                    teams.append(team)
                    seen_ids.add(team.id)
            if teams:
                break

        # Стратегия 2: Извлекаем команды из турнирной таблицы (standings)
        if not teams:
            standings_table = self._find_standings_table(soup)
            if standings_table:
                for row in standings_table.find_all("tr"):
                    team = self._extract_team_from_standing_row(row)
                    if team and team.id not in seen_ids:
                        teams.append(team)
                        seen_ids.add(team.id)

        # Стратегия 3: Ищем все ссылки с 'team' или 'club' в href
        if not teams:
            for link in soup.find_all("a", href=re.compile(r"(team|club|command)", re.IGNORECASE)):
                team = self._extract_team_from_element(link)
                if team and team.id not in seen_ids:
                    teams.append(team)
                    seen_ids.add(team.id)

        # Стратегия 4: Fallback — ищем команды в общих таблицах/списках
        # в основном контенте, даже если href не содержит team/club
        if not teams:
            teams = self._extract_teams_from_content(soup, seen_ids)

        logger.info("Найдено команд: %d", len(teams))
        return teams

    def _extract_teams_from_content(
        self, soup: BeautifulSoup, seen_ids: set[str]
    ) -> list[Team]:
        """Извлечь команды из общего контента страницы (fallback).

        Ищет ссылки в таблицах и списках основного контента.
        Берёт ссылки, если текст похож на название команды
        (отбрасывает навигацию, счёты, служебные строки).

        Args:
            soup: BeautifulSoup объект.
            seen_ids: Уже обработанные ID (для дедупликации).

        Returns:
            Список объектов Team.
        """
        teams: list[Team] = []

        # Ищем в основном контенте страницы
        content_blocks = []
        for selector in ["div.content", "div.main", "#content", "#main", "article"]:
            block = soup.select_one(selector)
            if block:
                content_blocks.append(block)

        if not content_blocks:
            content_blocks = [soup]

        for block in content_blocks:
            # Ищем в таблицах
            for table in block.find_all("table"):
                if self._is_navigation_table(table):
                    continue
                for link in table.find_all("a", href=True):
                    team = self._extract_team_from_generic_link(link)
                    if team and team.id not in seen_ids:
                        teams.append(team)
                        seen_ids.add(team.id)

            # Если команды найдены — останавливаемся
            if teams:
                break

            # Ищем в списках (ul, ol)
            for list_tag in block.find_all(["ul", "ol"]):
                for link in list_tag.find_all("a", href=True):
                    team = self._extract_team_from_generic_link(link)
                    if team and team.id not in seen_ids:
                        teams.append(team)
                        seen_ids.add(team.id)

            if teams:
                break

        return teams

    def _extract_team_from_generic_link(self, link: Tag) -> Optional[Team]:
        """Извлечь команду из произвольной ссылки.

        Фильтрует ссылки, отбрасывая:
        - навигацию,
        - счёты матчей,
        - служебные страницы,
        - слишком длинные/короткие тексты.

        Args:
            link: BeautifulSoup тег <a>.

        Returns:
            Team или None.
        """
        href = link.get("href", "")
        name = clean_text(link.get_text())

        if not href or not _looks_like_team_name(name):
            return None

        # Отбрасываем ссылки на служебные страницы
        href_lower = href.lower()
        skip_hrefs = ["news", "about", "contact", "help", "login", "search",
                      "admin", "settings", "profile", "statistics", "calendar"]
        if any(skip in href_lower for skip in skip_hrefs):
            return None

        team_id = self._extract_id_from_url(href)
        return Team(
            id=team_id,
            name=name,
            url=self._make_absolute_url(href),
        )

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

    # ========================================================================
    # ТУРНИРНАЯ ТАБЛИЦА
    # ========================================================================

    async def get_league_standings(self, league_url: str) -> list[StandingRow]:
        """Получить турнирную таблицу лиги.

        Находит реальную таблицу standings, парсит только валидные строки.
        Отбрасывает заголовки, мусор, строки без команды.

        Args:
            league_url: URL страницы лиги.

        Returns:
            Список строк таблицы.
        """
        logger.info("Получение турнирной таблицы: %s", league_url)

        try:
            html = await self._fetch_page(league_url)
            soup = self._parse_html(html)
        except SiteParserError as e:
            logger.error("Не удалось загрузить страницу таблицы: %s", e)
            return []

        standings: list[StandingRow] = []

        # Стратегия 1: Ищем таблицу с конкретным классом
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
                standings = self._parse_standings_table(table)
                if standings:
                    break

        # Стратегия 2: Ищем любую таблицу, которая содержит строки
        # с числовыми данными и ссылками на команды
        if not standings:
            for table in soup.find_all("table"):
                standings = self._parse_standings_table(table)
                if len(standings) >= 2:  # Минимум 2 команды — это реальная таблица
                    break
                standings = []

        # Финальная фильтрация: убираем строки без нормальных названий
        standings = [
            s for s in standings
            if s.team_name
            and not _is_navigation_text(s.team_name)
            and len(s.team_name) >= 2
        ]

        logger.info("Найдено строк в таблице: %d", len(standings))
        return standings

    def _parse_standings_table(self, table: Tag) -> list[StandingRow]:
        """Распарсить конкретную таблицу как standings.

        Args:
            table: BeautifulSoup тег <table>.

        Returns:
            Список строк standings.
        """
        standings: list[StandingRow] = []
        rows = table.find_all("tr")

        for row in rows:
            standing = self._parse_standing_row(row)
            if standing:
                standings.append(standing)

        return standings

    def _parse_standing_row(self, row: Tag) -> Optional[StandingRow]:
        """Распарсить строку турнирной таблицы.

        Валидация:
        - Позиция — число
        - Команда — непустая строка, не навигация, минимум 2 символа
        - Минимум 3 ячейки с числами (сыграно, победы, очки или аналог)

        Args:
            row: Тег <tr>.

        Returns:
            StandingRow или None.
        """
        cells = row.find_all(["td", "th"])
        if len(cells) < 3:
            return None

        # Позиция — должна быть числом в первой ячейке
        try:
            position_text = clean_text(cells[0].get_text())
            position = int(re.sub(r"[^\d]", "", position_text))
            if position < 1 or position > 200:
                return None  # Нереалистичная позиция
        except (ValueError, IndexError):
            return None

        # Команда — вторая ячейка, обязательна ссылка или текст
        team_cell = cells[1]
        team_link = team_cell.find("a")
        team_name = clean_text(team_link.get_text() if team_link else team_cell.get_text())
        team_url = self._make_absolute_url(team_link.get("href", "")) if team_link else None

        # Валидация названия команды
        if not team_name or _is_navigation_text(team_name) or len(team_name) < 2:
            return None

        # Числовые данные (игры, победы, ничьи, поражения, голы, очки)
        numbers: list[int] = []
        for cell in cells[2:]:
            text = clean_text(cell.get_text())
            nums = re.findall(r"(\d+)", text)
            if nums:
                numbers.extend(int(n) for n in nums)

        # Минимум: played(1), wins(2), draws(3), losses(4), points(N)
        # Если чисел меньше 3 — строка подозрительна
        if len(numbers) < 3:
            return None

        # Разбор в зависимости от количества чисел
        if len(numbers) >= 7:
            # Полный формат: И В Н П ГЗ ГП О
            played, wins, draws, losses = numbers[0], numbers[1], numbers[2], numbers[3]
            goals_for, goals_against = numbers[4], numbers[5]
            points = numbers[-1]
        elif len(numbers) >= 5:
            # Минимальный: И В Н П О
            played, wins, draws, losses = numbers[0], numbers[1], numbers[2], numbers[3]
            goals_for, goals_against = 0, 0
            points = numbers[-1]
        else:
            # Только И В Н — очков нет, пропускаем
            return None

        # Дополнительная проверка: очки должны быть разумными
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

        Использует расширенную стратегию для страниц команд:
        - Стандартный парсинг матчевых таблиц/карточек
        - Fallback: парсинг компактных строк «дата — соперник — счёт»
        - Fallback: извлечение матчей из div/li блоков с датами и ссылками

        Args:
            team_url: URL страницы команды.

        Returns:
            Список объектов Match.
        """
        logger.info("Получение матчей команды: %s", team_url)

        try:
            html = await self._fetch_page(team_url)
            soup = self._parse_html(html)
        except SiteParserError as e:
            logger.error("Не удалось загрузить страницу матчей: %s", e)
            return []

        matches = self._extract_matches_from_page(soup)

        # Если стандартные методы не нашли матчей — пробуем
        # агрессивный парсинг страницы команды
        if not matches:
            matches = self._extract_matches_from_team_page(soup)

        logger.info("Найдено матчей: %d", len(matches))
        return matches

    def _extract_matches_from_team_page(self, soup: BeautifulSoup) -> list[Match]:
        """Агрессивный парсинг матчей со страницы команды.

        Ищет паттерны:
        - Строки/блоки с датой + 1-2 ссылки на команды + счёт
        - Секции «Результаты» / «Календарь» / «Расписание»
        - Любой блок, содержащий дату и хотя бы одну ссылку на соперника

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
            # Проходим по всем div/li и ищем паттерн матча
            for tag_name in ["div", "li"]:
                for el in section.find_all(tag_name):
                    match = self._try_parse_match_block(el)
                    if match and match.id not in seen_ids:
                        matches.append(match)
                        seen_ids.add(match.id)

            if matches:
                break

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
        if len(links) > 6:
            return None

        # Слишком длинный текст — это не атомарный матч
        if len(el.get_text()) > 300:
            return None

        texts = [clean_text(s) for s in el.stripped_strings if clean_text(s)]
        if len(texts) < 2:
            return None

        # Ищем дату
        match_date: datetime | None = None
        for text in texts:
            parsed = parse_russian_date(text)
            if parsed:
                match_date = parsed
                break

        # Ищем ссылки-команды
        team_links: list[str] = []
        for link in links:
            name = clean_text(link.get_text())
            href_lower = link.get("href", "").lower()

            # Пропускаем навигацию и служебные ссылки
            skip = [
                "tournament", "league", "protocol", "statistic",
                "stats", "report", "summary", "details", "preview",
                "standings", "tables", "news", "article", "team/",
            ]
            # team/ — ссылки на другие команды — это ок, но tournament/league — нет
            skip_without_team = [s for s in skip if s != "team/"]
            if any(s in href_lower for s in skip_without_team):
                continue
            if not name or not _looks_like_team_name(name):
                continue
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

        # Валидация: нужна хотя бы 1 команда + (дата или счёт или вторая команда)
        if not team_links:
            return None

        home_team: str = ""
        away_team: str = ""

        if len(team_links) >= 2:
            home_team = team_links[0]
            away_team = team_links[1]
        elif len(team_links) == 1:
            # Одна команда + счёт — это матч (вторую команду не знаем)
            if home_score is not None and away_score is not None:
                home_team = team_links[0]
                away_team = "—"  # Неизвестный соперник
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
        # TODO: Если структура сайта меняется — обновите селекторы.
        # Откройте страницу команды в браузере, посмотрите CSS-классы
        # таблицы/блока с матчами и добавьте сюда.

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
        ]:
            container = soup.select_one(selector)
            if container:
                containers.append(container)

        if containers:
            return containers

        # Приоритет 2: Любой блок с id/class, содержащим match/fixture/scheduled/results/calendar
        for pattern in ["match", "fixture", "scheduled", "calendar", "game"]:
            for tag_name in ["table", "div", "section", "ul"]:
                for el in soup.find_all(tag_name, id=re.compile(pattern, re.IGNORECASE)):
                    containers.append(el)
                for el in soup.find_all(tag_name, class_=re.compile(pattern, re.IGNORECASE)):
                    if el not in containers:
                        containers.append(el)

        if containers:
            return containers

        # Приоритет 3: Основной контент страницы — ищем таблицы в нём
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
        1. Контейнер матчей → парсим <tr>
        2. Таблицы в основном контенте → парсим <tr>
        3. Матчевые карточки (div.match-card, div.fix-item и т.д.)
        4. Все таблицы на странице (fallback, с фильтрацией)

        Args:
            soup: BeautifulSoup объект.

        Returns:
            Список объектов Match.
        """
        matches: list[Match] = []
        seen_ids: set[str] = set()

        # Стратегия 1: Конкретные контейнеры матчей → <tr>
        containers = self._find_matches_container(soup)
        for container in containers:
            for row in container.find_all("tr"):
                match = self._parse_match_element(row)
                if match and match.id not in seen_ids:
                    matches.append(match)
                    seen_ids.add(match.id)

        if matches:
            return matches

        # Стратегия 2: Матчевые карточки (div, li) — без требования <tr>
        card_matches = self._extract_match_cards(soup)
        if card_matches:
            return card_matches

        # Стратегия 3: Таблицы в основном контенте
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

        # Стратегия 4: Все таблицы на странице (fallback)
        for table in soup.find_all("table"):
            if self._is_navigation_table(table):
                continue
            for row in table.find_all("tr"):
                match = self._parse_match_element(row)
                if match and match.id not in seen_ids:
                    matches.append(match)
                    seen_ids.add(match.id)

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
        # Ослаблено: раньше было < 3, теперь < 2
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

        # 2. Ищем ссылки на команды
        links = el.find_all("a", href=True)
        team_links = []
        for link in links:
            name = clean_text(link.get_text())
            if name and not _is_navigation_text(name) and not _looks_like_score(name) and len(name) >= 2:
                team_links.append(name)

        home_team: str = ""
        away_team: str = ""

        if len(team_links) >= 2:
            home_team = team_links[0]
            away_team = team_links[1]
        elif len(team_links) == 0:
            # Нет ссылок — извлекаем из текста
            candidates = []
            for text in texts:
                t = text.strip()
                if not t or _is_navigation_text(t) or _looks_like_score(t):
                    continue
                if re.fullmatch(r"[\d\./\-:]+", t):
                    continue
                if len(t) >= 2 and re.search(r"[a-zA-Zа-яА-ЯёЁ]", t):
                    candidates.append(t)
            if len(candidates) >= 2:
                home_team = candidates[0]
                away_team = candidates[1]
            else:
                return None
        else:
            # 1 ссылка — пробуем дополнить из текста
            home_team = team_links[0]
            candidates = []
            for text in texts:
                t = text.strip()
                if not t or _is_navigation_text(t) or _looks_like_score(t):
                    continue
                if re.fullmatch(r"[\d\./\-:]+", t):
                    continue
                if len(t) >= 2 and re.search(r"[a-zA-Zа-яА-ЯёЁ]", t) and t != home_team:
                    candidates.append(t)
            if candidates:
                away_team = candidates[0]
            else:
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

        # 4. Если нет даты, но есть счёт — это всё равно матч
        if match_date is None and home_score is None and away_score is None:
            return None  # Нет ни даты, ни счёта — не матч

        # 5. Определяем статус
        if home_score is not None and away_score is not None:
            status = "finished"
        elif match_date and match_date < datetime.now():
            status = "unknown"
        else:
            status = "scheduled"

        # 5. Генерируем ID — используем дату + команды
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
                    league_teams = await self.get_league_teams(league.url)
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
