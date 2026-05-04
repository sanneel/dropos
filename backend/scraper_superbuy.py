"""
Superbuy public search API scraper.

Endpoint: POST https://front.superbuy.com/crawler/search-product
Platforms: tb (Taobao) | 1688
No login required. Titles are pre-translated to English.
Returns up to 1000 items per keyword (50 pages × 20).

Cookie strategy: Playwright visits the search page once to get a real browser
cookie jar, saves it to superbuy_cookies.json, then httpx reuses those cookies
for all API calls. Cookies are refreshed when the file is >6 hours old.
"""

import asyncio
import hashlib
import json
import logging
import math
import time
from pathlib import Path
from typing import Literal, Optional

import httpx

log = logging.getLogger(__name__)

_SEARCH_URL   = "https://front.superbuy.com/crawler/search-product"
_WARMUP_URL   = "https://www.superbuy.com/en/page/search/?keyword=gift&platform=taobao"
_COOKIE_FILE  = Path(__file__).parent / "superbuy_cookies.json"
_COOKIE_TTL   = 6 * 3600  # refresh every 6 hours

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.superbuy.com/en/page/search/?keyword=gift&platform=taobao",
    "Origin":  "https://www.superbuy.com",
}
_PAGE_SIZE = 30

Source = Literal["1688", "taobao", "both"]


# ── Cookie management ─────────────────────────────────────────────────────────

async def _get_cookies() -> dict:
    """Return a valid cookie dict, refreshing via Playwright if stale."""
    if _COOKIE_FILE.exists():
        age = time.time() - _COOKIE_FILE.stat().st_mtime
        if age < _COOKIE_TTL:
            try:
                data = json.loads(_COOKIE_FILE.read_text())
                log.debug("Superbuy: using cached cookies (age=%.0fs)", age)
                return data
            except Exception:
                pass

    log.info("Superbuy: refreshing cookies via browser (one-time, ~5s)…")
    cookies = await _fetch_cookies_playwright()
    if cookies:
        _COOKIE_FILE.write_text(json.dumps(cookies))
        log.info("Superbuy: cookies saved (%d keys)", len(cookies))
    return cookies


async def _fetch_cookies_playwright() -> dict:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[SUPERBUY] Playwright not installed — run: pip install playwright && playwright install chromium", flush=True)
        return {}

    print("[SUPERBUY] Launching browser to pass Cloudflare challenge…", flush=True)
    try:
        async with async_playwright() as pw:
            # headed=False fails Cloudflare JS challenge — use headed briefly
            browser = await pw.chromium.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            ctx = await browser.new_context(
                user_agent=_HEADERS["User-Agent"],
                locale="en-US",
            )
            await ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            page = await ctx.new_page()
            print(f"[SUPERBUY] Navigating to {_WARMUP_URL}", flush=True)
            await page.goto(_WARMUP_URL, wait_until="domcontentloaded", timeout=30000)

            # Wait for Cloudflare "Just a moment..." challenge to pass (up to 15s)
            for _ in range(30):
                title = await page.title()
                print(f"[SUPERBUY] Page title: {title!r}", flush=True)
                if "just a moment" not in title.lower():
                    break
                await asyncio.sleep(0.5)

            await asyncio.sleep(2)  # let JS set all cookies
            raw = await ctx.cookies()
            await browser.close()
            print(f"[SUPERBUY] Got {len(raw)} cookies total", flush=True)

        result = {c["name"]: c["value"] for c in raw}
        cf = "cf_clearance" in result
        print(f"[SUPERBUY] Kept {len(result)} cookies, cf_clearance={'YES' if cf else 'NO'}: {list(result.keys())}", flush=True)
        return result
    except Exception as exc:
        print(f"[SUPERBUY] Playwright cookie fetch failed: {exc}", flush=True)
        log.warning("Superbuy: Playwright cookie fetch failed: %s", exc)
        return {}


# ── Public entry point ─────────────────────────────────────────────────────────

async def scrape(
    keywords: list,
    max_per_keyword: int = 50,
    source: Source = "taobao",
) -> list:
    source = str(source)
    want_tb   = source in ("taobao", "both")
    want_1688 = source in ("1688", "both")

    cookies = await _get_cookies()

    products: list = []
    async with httpx.AsyncClient(
        timeout=20,
        headers=_HEADERS,
        cookies=cookies,
        follow_redirects=True,
    ) as client:
        for keyword in keywords:
            if want_tb:
                tb = await _fetch_keyword(client, keyword, "tb", max_per_keyword)
                log.info("Superbuy Taobao '%s': %d products", keyword, len(tb))
                products.extend(tb)

            if want_1688:
                items_1688 = await _fetch_keyword(client, keyword, "1688", max_per_keyword)
                log.info("Superbuy 1688 '%s': %d products", keyword, len(items_1688))
                products.extend(items_1688)

    return products


# ── Pagination ─────────────────────────────────────────────────────────────────

async def _fetch_keyword(
    client: httpx.AsyncClient,
    keyword: str,
    platform: str,
    max_results: int,
) -> list:
    items: list = []
    pages_needed = math.ceil(max_results / _PAGE_SIZE)

    for page_no in range(1, pages_needed + 1):
        batch = await _fetch_page(client, keyword, platform, page_no)
        if not batch:
            break

        for raw in batch:
            p = _normalize(raw, keyword, platform)
            if p:
                items.append(p)

        if len(batch) < _PAGE_SIZE:
            break  # last page

        if len(items) >= max_results:
            break

    return items[:max_results]


async def _fetch_page(
    client: httpx.AsyncClient,
    keyword: str,
    platform: str,
    page_no: int,
) -> list:
    try:
        resp = await client.post(
            _SEARCH_URL,
            content=f"keyword={_enc(keyword)}&platform={platform}&pageNo={page_no}&pageSize={_PAGE_SIZE}",
            headers={"content-type": "application/x-www-form-urlencoded; charset=UTF-8"},
        )
        if resp.status_code != 200:
            log.warning("Superbuy %s p%d → HTTP %d | %s", platform, page_no, resp.status_code, resp.text[:300])
            return []

        body = resp.json()
        if body.get("state") != 0:
            log.warning("Superbuy API error: %s", body.get("msg", "unknown"))
            return []

        datas = body.get("data", {}).get("datas") or []
        if not datas:
            return []

        # intResults lives inside the first (only) element of datas
        return datas[0].get("intResults") or []

    except Exception as exc:
        log.warning("Superbuy fetch error (kw=%r p=%s page=%d): %s", keyword, platform, page_no, exc)
        return []


# ── Normalizer ─────────────────────────────────────────────────────────────────

def _normalize(item: dict, keyword: str, platform: str) -> Optional[dict]:
    price_raw = item.get("price", 0)
    try:
        price_cny = float(price_raw) if price_raw else 0.0
    except Exception:
        price_cny = 0.0
    if not price_cny:
        return None

    title = (item.get("title") or "").strip()
    if not title:
        return None

    img = item.get("imgUrl") or ""
    if img and img.startswith("//"):
        img = "https:" + img

    goods_id = str(item.get("goodsId") or hashlib.md5(f"{title}{price_cny}".encode()).hexdigest()[:10])
    goods_url = item.get("goodsUrl") or ""

    src_platform = "taobao" if platform == "tb" else "1688"

    return {
        "source":           "superbuy",
        "source_platform":  src_platform,
        "source_id":        f"superbuy_{src_platform}_{goods_id}",
        "title":            title,
        "title_translated": title,
        "price_cny":        price_cny,
        "orders":           int(item.get("sold") or item.get("soldCount") or 0),
        "rating":           float(item.get("rating") or 4.5),
        "images":           [img] if img else [],
        "url":              goods_url or f"https://www.superbuy.com/en/page/buy/?url={goods_url}",
        "category":         "",
        "keyword":          keyword,
        "merchant":         item.get("shopName") or "",
    }


def _enc(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")
