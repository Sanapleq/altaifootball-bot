"""Утилита сохранения реальных HTML-страниц сайта для fixtures и тестов.

Использует текущий PageLoader со всеми fallback'ами (httpx → curl_cffi → Playwright).

Использование:
    python -m tests.fixtures.save_site_html          # сохранить все
    python -m tests.fixtures.save_site_html --match  # только матчи/boxscore
    python -m tests.fixtures.save_site_html --roster # только roster/stats
    python -m tests.fixtures.save_site_html --list   # показать список URL
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

# Добавляем проект в path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.services.page_loader import PageLoader, PageLoaderError

FIXTURES_DIR = Path(__file__).resolve().parent / "site_html"


@dataclass
class FixtureURL:
    """Описание URL для сохранения в fixtures."""
    filename: str
    url: str
    description: str


# ============================================================
# Контрольный набор эталонных HTML-страниц
# ============================================================

ALL_FIXTURES: list[FixtureURL] = [
    # ── Навигация ─────────────────────────────────────────────
    FixtureURL(
        "tournaments.html",
        "/tournaments/",
        "Список всех турниров и сезонов",
    ),

    # ── Лиги (разные сезоны) ──────────────────────────────────
    FixtureURL(
        "league_3607.html",
        "/tournaments/2026/3607/",
        "Десятая лига 2026 (зима) — основная лига GM SPORT/СКА",
    ),
    FixtureURL(
        "league_3530.html",
        "/tournaments/2026/3530/",
        "Супер-лига 2026 — другой сезон/уровень",
    ),

    # ── Команды (страницы матчей) ─────────────────────────────
    FixtureURL(
        "team_6662.html",
        "/tournaments/2026/3607/teams/6662/",
        "GM SPORT 22 Барнаул — матчи",
    ),
    FixtureURL(
        "team_5790.html",
        "/tournaments/2026/3607/teams/5790/",
        "СКА Сибирский ЗАТО — матчи",
    ),
    FixtureURL(
        "team_6659.html",
        "/tournaments/2026/3607/teams/6659/",
        "Товарка 22 Барнаул — матчи (ещё одна команда)",
    ),
    FixtureURL(
        "team_6734.html",
        "/tournaments/2026/3607/teams/6734/",
        "Libertas NEO STAR's Барнаул — матчи",
    ),
    FixtureURL(
        "team_5628.html",
        "/tournaments/2026/3607/teams/5628/",
        "АТТ фермер Алейск — матчи",
    ),
    FixtureURL(
        "team_6377.html",
        "/tournaments/2026/3607/teams/6377/",
        "ASM Group Барнаул — матчи",
    ),
    FixtureURL(
        "team_6281.html",
        "/tournaments/2026/3607/teams/6281/",
        "Барнаульский завод АТИ Барнаул — матчи",
    ),

    # ── Заявка команды (roster) ───────────────────────────────
    FixtureURL(
        "team_6662_roster.html",
        "/tournaments/2026/3607/teams/6662/roster/",
        "GM SPORT 22 — заявка (roster)",
    ),
    FixtureURL(
        "team_5790_roster.html",
        "/tournaments/2026/3607/teams/5790/roster/",
        "СКА — заявка (roster)",
    ),

    # ── Статистика игроков ────────────────────────────────────
    FixtureURL(
        "team_6662_stats.html",
        "/tournaments/2026/3607/teams/6662/stats/",
        "GM SPORT 22 — статистика игроков",
    ),
    FixtureURL(
        "team_5790_stats.html",
        "/tournaments/2026/3607/teams/5790/stats/",
        "СКА — статистика игроков",
    ),

    # ── Boxscore (протокол матча) ─────────────────────────────
    FixtureURL(
        "boxscore_140352.html",
        "/tournaments/boxscore/140352/",
        "Протокол: GM SPORT 22 vs АТТ фермер (2:1)",
    ),
    FixtureURL(
        "boxscore_140597.html",
        "/tournaments/boxscore/140597/",
        "Протокол: GM SPORT 22 vs Товарка 22 (3:7)",
    ),

    # ── Preview (предварительный просмотр) ────────────────────
    FixtureURL(
        "preview_140750.html",
        "/tournaments/boxscore/140750/preview/",
        "Превью: GM SPORT 22 vs СКА (предстоящий)",
    ),
]

# Группировка для фильтрации
GROUPS = {
    "all": ALL_FIXTURES,
    "match": [f for f in ALL_FIXTURES if any(k in f.filename for k in ("team_", "boxscore_", "preview_"))],
    "roster": [f for f in ALL_FIXTURES if any(k in f.filename for k in ("roster", "stats"))],
    "league": [f for f in ALL_FIXTURES if "league_" in f.filename],
    "boxscore": [f for f in ALL_FIXTURES if any(k in f.filename for k in ("boxscore_", "preview_"))],
}


async def save_fixtures(fixtures: list[FixtureURL], force: bool = False) -> dict[str, str]:
    """Скачать и сохранить HTML fixtures.

    Args:
        fixtures: Список URL для сохранения.
        force: Перезаписать существующие файлы.

    Returns:
        Словарь {filename: результат} — "ok", "exists", "fail: reason".
    """
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    loader = PageLoader()
    results: dict[str, str] = {}

    print(f"[fixtures] Сохраняю {len(fixtures)} страниц...")
    print(f"[fixtures] Папка: {FIXTURES_DIR}")
    print()

    for fixture in fixtures:
        filepath = FIXTURES_DIR / fixture.filename

        # Пропускаем если уже есть
        if filepath.exists() and not force:
            results[fixture.filename] = "exists"
            print(f"[  SKIP] {fixture.filename}")
            print(f"        {fixture.description}")
            print()
            continue

        try:
            html = await loader.fetch_page(fixture.url)
            filepath.write_text(html, encoding="utf-8")
            results[fixture.filename] = "ok"
            print(f"[  OK  ] {fixture.filename}")
            print(f"        {fixture.description}")
            print(f"        -> {len(html):,} bytes")
        except PageLoaderError as e:
            results[fixture.filename] = f"fail: {e}"
            print(f"[FAIL  ] {fixture.filename}")
            print(f"        {fixture.description}")
            print(f"        -> Ошибка: {e}")
        except Exception as e:
            results[fixture.filename] = f"error: {type(e).__name__}: {e}"
            print(f"[ERROR ] {fixture.filename}")
            print(f"        {fixture.description}")
            print(f"        -> {type(e).__name__}: {e}")
        print()

    await loader.close()

    # Итог
    ok = sum(1 for v in results.values() if v == "ok")
    skip = sum(1 for v in results.values() if v == "exists")
    fail = sum(1 for v in results.values() if v.startswith(("fail", "error")))
    print(f"[fixtures] Готово: {ok} сохранено, {skip} пропущено, {fail} ошибок")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Сохранить HTML fixtures с altaifootball.ru")
    parser.add_argument(
        "--match", action="store_const", const="match", dest="group",
        help="Только матчи/boxscore/preview",
    )
    parser.add_argument(
        "--roster", action="store_const", const="roster", dest="group",
        help="Только roster/stats",
    )
    parser.add_argument(
        "--league", action="store_const", const="league", dest="group",
        help="Только страницы лиг",
    )
    parser.add_argument(
        "--boxscore", action="store_const", const="boxscore", dest="group",
        help="Только boxscore/preview",
    )
    parser.add_argument(
        "--list", action="store_true", help="Показать список URL и выйти",
    )
    parser.add_argument(
        "--force", action="store_true", help="Перезаписать существующие файлы",
    )

    args = parser.parse_args()

    # --list
    if args.list:
        print(f"{'Filename':<35} {'URL':<60} {'Описание'}")
        print("-" * 130)
        for f in ALL_FIXTURES:
            print(f"{f.filename:<35} {f.url:<60} {f.description}")
        print(f"\nВсего: {len(ALL_FIXTURES)} fixtures")
        return

    # Выбираем группу
    group = args.group or "all"
    fixtures = GROUPS.get(group, ALL_FIXTURES)

    asyncio.run(save_fixtures(fixtures, force=args.force))


if __name__ == "__main__":
    main()
