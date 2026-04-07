"""Абстракция загрузки страниц.

Основной режим: httpx + BeautifulSoup.
Fallback режим: Playwright (для страниц, которые отдают JS-рендеринг).

Конфигурируется через настройки:
    settings.use_playwright_fallback = False  # по умолчанию

Использование:
    from app.services.page_loader import PageLoader

    loader = PageLoader()
    html = await loader.fetch_page("/tournaments/")
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings
from app.logger import logger


# ============================================================
# Абстрактный интерфейс загрузчика страниц
# ============================================================

class PageLoaderBackend(ABC):
    """Абстрактный бэкенд загрузки страниц."""

    @abstractmethod
    async def fetch(self, url: str, base_url: str) -> str:
        """Загрузить HTML страницы.

        Args:
            url: Относительный или абсолютный URL.
            base_url: Базовый URL сайта.

        Returns:
            HTML-содержимое страницы.
        """
        ...


# ============================================================
# HTTPX бэкенд (основной)
# ============================================================

class HttpxBackend(PageLoaderBackend):
    """Бэкенд на базе httpx с retry и корректными заголовками."""

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/130.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                              "image/avif,image/webp,image/apng,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "same-origin",
                    "Upgrade-Insecure-Requests": "1",
                },
            )
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
        reraise=True,
    )
    async def fetch(self, url: str, base_url: str) -> str:
        client = await self._get_client()
        full_url = url if url.startswith("http") else base_url.rstrip("/") + "/" + url.lstrip("/")

        logger.debug("HTTP GET: %s (retry policy: %d attempts)", full_url, self._max_retries)

        try:
            response = await client.get(full_url)
            response.raise_for_status()
            html_len = len(response.text)

            # Пустой HTML — отдельная ошибка
            if html_len < 100:
                logger.warning(
                    "Пустой HTML (%d bytes): %s", html_len, full_url
                )
                raise PageLoaderError(
                    f"Пустая страница ({html_len} bytes): {full_url}",
                    status_code=response.status_code,
                )

            logger.debug("HTTP %d: %s (%d bytes)", response.status_code, full_url, html_len)
            return response.text

        except PageLoaderError:
            raise  # Пробрасываем свои ошибки без обёртки

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("Страница не найдена (404): %s", full_url)
                raise PageLoaderError(f"Страница не найдена: {full_url}", status_code=404)
            elif e.response.status_code == 403:
                logger.warning("Доступ запрещён (403): %s", full_url)
                raise PageLoaderError(f"Доступ запрещён: {full_url}", status_code=403)
            else:
                logger.error("HTTP ошибка %d: %s", e.response.status_code, full_url)
                raise PageLoaderError(
                    f"HTTP {e.response.status_code} при загрузке {full_url}",
                    status_code=e.response.status_code,
                )

        except httpx.TimeoutException:
            logger.error("Таймаут запроса: %s", full_url)
            raise PageLoaderError(f"Таймаут при загрузке: {full_url}")

        except httpx.ConnectError as e:
            logger.error("Ошибка соединения: %s — %s", full_url, e)
            raise PageLoaderError(f"Ошибка соединения с {full_url}: {e}")

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


# ============================================================
# Playwright бэкенд (fallback)
# ============================================================

class PlaywrightBackend(PageLoaderBackend):
    """Бэкенд на базе Playwright для JS-рендеринга страниц.

    Используется как fallback для страниц, которые не отдают
    нормальный HTML через httpx (например, требуют JS-рендеринга).
    """

    def __init__(self) -> None:
        self._browser = None

    async def _get_browser(self):
        if self._browser is None:
            try:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=True)
                logger.info("Playwright браузер запущен (fallback mode)")
            except ImportError:
                logger.warning("Playwright не установлен. Установите: pip install playwright")
                raise PageLoaderError("Playwright не установлен")

        return self._browser

    async def fetch(self, url: str, base_url: str) -> str:
        browser = await self._get_browser()
        full_url = url if url.startswith("http") else base_url.rstrip("/") + "/" + url.lstrip("/")

        logger.info("Playwright GET (fallback): %s", full_url)

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="ru-RU",
        )

        try:
            page = await context.new_page()
            await page.goto(full_url, wait_until="networkidle", timeout=30000)

            # Ждём дополнительную загрузку контента
            await asyncio.sleep(1)

            html = await page.content()
            logger.debug("Playwright: %s (%d bytes)", full_url, len(html))
            return html

        except Exception as e:
            logger.error("Playwright ошибка при загрузке %s: %s", full_url, e)
            raise PageLoaderError(f"Playwright ошибка при загрузке {full_url}: {e}")

        finally:
            await context.close()

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if hasattr(self, "_playwright"):
            await self._playwright.stop()


# ============================================================
# PageLoader — фасад
# ============================================================

class PageLoaderError(Exception):
    """Ошибка загрузки страницы."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PageLoader:
    """Фасад загрузки страниц.

    Основной режим: httpx.
    При ошибке и включённом флаге USE_PLAYWRIGHT_FALLBACK — Playwright.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        use_playwright_fallback: bool = False,
    ) -> None:
        self._base_url = base_url or settings.base_url
        self._use_playwright = use_playwright_fallback or getattr(settings, "use_playwright_fallback", False)
        self._httpx = HttpxBackend(timeout=settings.request_timeout)
        self._playwright: Optional[PlaywrightBackend] = None

    async def fetch_page(self, url: str) -> str:
        """Загрузить HTML страницу.

        Args:
            url: Относительный или абсолютный URL.

        Returns:
            HTML-содержимое страницы.

        Raises:
            PageLoaderError: При ошибке загрузки.
        """
        # Пробуем httpx
        try:
            return await self._httpx.fetch(url, self._base_url)
        except PageLoaderError as e:
            if self._use_playwright and e.status_code in (403, 500, 503):
                logger.info("Переключаюсь на Playwright fallback для %s", url)
                return await self._fetch_via_playwright(url)
            raise

    async def _fetch_via_playwright(self, url: str) -> str:
        """Fallback через Playwright."""
        if self._playwright is None:
            self._playwright = PlaywrightBackend()
        return await self._playwright.fetch(url, self._base_url)

    async def close(self) -> None:
        """Закрыть все бэкенды."""
        await self._httpx.close()
        if self._playwright:
            await self._playwright.close()
