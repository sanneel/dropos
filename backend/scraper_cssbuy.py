"""
CSSBuy scraper — sync response listener + scroll pagination.

Sources
-------
1688   getCrossKeywordSearch  fires on page load + each scroll page
Taobao taoBaoGoodsByKeyWord  fires after clicking the Taobao tab + each scroll

Strategy
--------
Register a synchronous page.on("response") listener (async handlers are broken
in Playwright Python). The listener collects Response objects; the page loads
normally with zero interception delay. After navigating and scrolling, we await
each Response.json() from the buffered objects.

Login selectors (verified live):
  #username  #password  #code  p#login  div.g-recaptcha
"""

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote

log = logging.getLogger(__name__)

SESSION_FILE      = Path(__file__).parent / "cssbuy_session.json"
BASE_URL          = "https://www.cssbuy.com"
LOGIN_URL         = f"{BASE_URL}/login"
RECAPTCHA_SITEKEY = "6LeJ_noqAAAAAIOBR2APiofxlH0DQuEsm1qace0t"

_SEL_USERNAME    = "#username"
_SEL_PASSWORD    = "#password"
_SEL_CAPTCHA_IMG = "#captcha_img"
_SEL_CAPTCHA_IN  = "#code"
_SEL_RECAPTCHA   = ".g-recaptcha"
_SEL_SUBMIT      = "p#login"

Source = Literal["1688", "taobao", "both"]


# ── Public entry point ─────────────────────────────────────────────────────────

async def scrape(
    keywords: list,
    max_per_keyword: int = 50,
    username: str = "",
    password: str = "",
    captcha_key: str = "",
    source: Source = "1688",
) -> list:
    if not username or not password:
        log.warning("CSSBuy credentials not set — skipping")
        return []

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
        return []

    headless = bool(captcha_key)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = await _restore_context(browser)
        page = await ctx.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )

        try:
            if not await _check_login(page):
                log.info("CSSBuy: not logged in — starting login")
                await _login(page, username, password, captcha_key)
                await _save_session(ctx)
                log.info("CSSBuy: login OK")
            else:
                log.info("CSSBuy: session valid")

            products: list = []
            modal_done = False
            for keyword in keywords:
                kw = await _search_keyword(page, keyword, max_per_keyword, source, modal_done)
                if kw:
                    modal_done = True
                products.extend(kw)

            return products

        except Exception as e:
            log.error("CSSBuy scrape error: %s", e)
            try:
                await page.screenshot(path=str(Path(__file__).parent / "cssbuy_debug.png"))
            except Exception:
                pass
            return []
        finally:
            await browser.close()


# ── Per-keyword search ─────────────────────────────────────────────────────────

async def _search_keyword(
    page, keyword: str, max_results: int, source: Source, modal_done: bool
) -> list:
    """
    1. Register a sync response listener (page loads normally, no interception lag).
    2. Navigate + dismiss modal.
    3. Scroll until max_results items or two stale scrolls.
    4. Read json() from all buffered Response objects.
    """
    source      = str(source)   # DB may return int 1688 via json.loads()
    want_1688   = source in ("1688", "both")
    want_taobao = source in ("taobao", "both")
    search_url  = f"{BASE_URL}/productlist?keyWork={quote(keyword)}"
    products    = []

    resp_1688:   list = []   # Response objects from getCrossKeywordSearch
    resp_taobao: list = []   # Response objects from taoBaoGoodsByKeyWord

    # Sync listener — captures Response objects without blocking the page
    def on_response(response):
        url = response.url
        status = response.status
        if "getCrossKeywordSearch" in url and status == 200:
            resp_1688.append(response)
            print(f"[CSSBUY] captured 1688 XHR #{len(resp_1688)}", flush=True)
        elif "taoBaoGoodsByKeyWord" in url and status == 200:
            resp_taobao.append(response)
            print(f"[CSSBUY] captured taobao XHR #{len(resp_taobao)}", flush=True)

    page.on("response", on_response)

    try:
        # ── Navigate ──────────────────────────────────────────────────────────
        print(f"[CSSBUY] navigating keyword={keyword!r}", flush=True)
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        print(f"[CSSBUY] goto done url={page.url}", flush=True)

        if not modal_done:
            await _dismiss_modal(page)

        # ── 1688: scroll pages until max_results ──────────────────────────────
        if want_1688:
            # Wait for initial XHR (fires on page load)
            for _ in range(20):
                if resp_1688:
                    break
                await asyncio.sleep(0.5)

            if not resp_1688:
                # Page might need a nudge to trigger lazy load
                await page.evaluate("window.scrollTo(0, 400)")
                for _ in range(10):
                    if resp_1688:
                        break
                    await asyncio.sleep(0.5)

            if not resp_1688:
                log.warning("CSSBuy 1688: no XHR for '%s'", keyword)
            else:
                await _scroll_until_enough(page, resp_1688, max_results)

        # ── Taobao: click tab then scroll ─────────────────────────────────────
        if want_taobao:
            if not want_1688:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                if not modal_done:
                    await _dismiss_modal(page)

            try:
                await page.evaluate("""
                    (() => {
                        const li = [...document.querySelectorAll('li')]
                            .find(el => el.innerText?.trim() === 'Taobao');
                        if (li) li.dispatchEvent(
                            new MouseEvent('click', {bubbles:true, cancelable:true, view:window})
                        );
                    })()
                """)
                print("[CSSBUY] Taobao tab clicked", flush=True)
            except Exception as exc:
                print(f"[CSSBUY] Taobao click error: {exc}", flush=True)

            # Wait for initial Taobao XHR
            for _ in range(20):
                if resp_taobao:
                    break
                await asyncio.sleep(0.5)

            if resp_taobao:
                await _scroll_until_enough(page, resp_taobao, max_results)
            else:
                log.warning("CSSBuy Taobao: no XHR for '%s'", keyword)

    finally:
        page.remove_listener("response", on_response)

    # ── Read json from all buffered Response objects ───────────────────────────
    if want_1688:
        captured: list = []
        for r in resp_1688:
            try:
                captured.append(await r.json())
            except Exception:
                pass
        all_items = _merge_raw_items(captured)
        print(f"[CSSBUY] 1688 responses={len(captured)} items={len(all_items)}", flush=True)
        for item in all_items[:max_results]:
            p = _normalize_1688(item, keyword)
            if p:
                products.append(p)
        log.info("CSSBuy 1688 '%s': %d products", keyword, len(products))

    if want_taobao:
        captured_tb: list = []
        for r in resp_taobao:
            try:
                captured_tb.append(await r.json())
            except Exception:
                pass
        all_items_tb = _merge_raw_items(captured_tb)
        print(f"[CSSBUY] taobao responses={len(captured_tb)} items={len(all_items_tb)}", flush=True)
        tb: list = []
        for item in all_items_tb[:max_results]:
            p = _normalize_taobao(item, keyword)
            if p:
                tb.append(p)
        log.info("CSSBuy Taobao '%s': %d products", keyword, len(tb))
        products.extend(tb)

    return products


async def _scroll_until_enough(page, resp_list: list, max_results: int) -> None:
    """
    Scroll to bottom and wait for XHR. When the page stalls (already at bottom),
    scroll back to top first so the lazy-loader sees the viewport moving again.
    """
    max_scrolls = max(4, (max_results // 20) + 3)
    scrolls = 0
    recovered = False   # only try the top-recovery once

    # Let the first batch fully render before scrolling
    await asyncio.sleep(3)

    while scrolls < max_scrolls:
        prev = len(resp_list)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        print(f"[CSSBUY] scroll #{scrolls + 1}, waiting for XHR…", flush=True)

        # Wait up to 8 s for the next XHR
        for _ in range(16):
            await asyncio.sleep(0.5)
            if len(resp_list) > prev:
                break

        scrolls += 1

        if len(resp_list) > prev:
            # Got a new batch — pause for it to render, then continue
            stale = 0
            recovered = False
            print(f"[CSSBUY] XHR #{len(resp_list)} captured", flush=True)
            await asyncio.sleep(2)
        else:
            # Nothing came — try scrolling back to top to reset lazy-loader
            if not recovered:
                print("[CSSBUY] stale — scrolling to top to reset lazy-loader", flush=True)
                await page.evaluate("window.scrollTo(0, 0)")
                await asyncio.sleep(2)
                recovered = True
                # Don't count this as a wasted scroll
                scrolls -= 1
            else:
                # Already tried recovery — truly end of results
                print("[CSSBUY] stale after recovery — stopping", flush=True)
                break


async def _dismiss_modal(page) -> None:
    for attempt in range(30):
        btn = await page.query_selector(".fxts span.button:last-child")
        if btn:
            log.info("CSSBuy: modal found (attempt %d) — dismissing", attempt)
            await page.evaluate(
                "document.querySelector('.fxts span.button:last-child')"
                ".dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}))"
            )
            await asyncio.sleep(2)
            if not await page.query_selector(".fxts"):
                log.info("CSSBuy: modal dismissed OK")
                return
        await asyncio.sleep(0.5)
    try:
        await page.screenshot(path=str(Path(__file__).parent / "cssbuy_modal_debug.png"))
        log.warning("CSSBuy: modal not dismissed after 15s (screenshot saved)")
    except Exception:
        pass


# ── Normalizers ────────────────────────────────────────────────────────────────

def _normalize_1688(item: dict, keyword: str) -> Optional[dict]:
    price_raw = (item.get("offerPrice") or {}).get("price") or item.get("price") or 0
    try:
        price_cny = float(re.sub(r"[^\d.]", "", str(price_raw))) if price_raw else 0
    except Exception:
        price_cny = 0
    if not price_cny:
        return None

    title = item.get("subject") or item.get("title") or ""
    if not title:
        return None

    image = (item.get("offerImage") or {}).get("imageUrl") or item.get("imageUrl") or ""
    if image and image.startswith("//"):
        image = "https:" + image

    offer_id = str(
        item.get("offerId") or item.get("id") or
        hashlib.md5(f"{title}{price_cny}".encode()).hexdigest()[:10]
    )
    sold = int(item.get("sold") or item.get("soldCount") or item.get("monthSold") or item.get("totalSold") or 0)
    # Debug: dump all keys containing "sold" from the first few items
    sold_keys = {k: v for k, v in item.items() if "sold" in k.lower() or "sale" in k.lower() or "order" in k.lower()}
    if sold_keys or sold == 0:
        print(f"[CSSBUY-SOLD] offer={item.get('offerId','')} sold={sold} raw_keys={sold_keys}", flush=True)

    return {
        "source": "cssbuy",
        "source_platform": "1688",
        "source_id": f"cssbuy_1688_{offer_id}",
        "title": title,
        "title_translated": title,
        "price_cny": price_cny,
        "orders": sold,
        "rating": 4.5,
        "images": [image] if image else [],
        "url": f"{BASE_URL}/item-1688-{offer_id}.html",
        "category": "",
        "keyword": keyword,
        "merchant": item.get("sellerName") or item.get("shop") or "",
    }


def _normalize_taobao(item: dict, keyword: str) -> Optional[dict]:
    info = item.get("dataInfo") or {}

    price_raw = item.get("reserve_price") or info.get("price") or item.get("price") or 0
    try:
        price_cny = float(re.sub(r"[^\d.]", "", str(price_raw))) if price_raw else 0
    except Exception:
        price_cny = 0
    if not price_cny:
        return None

    title_en = (
        item.get("title") or
        (info.get("multi_language_info") or {}).get("title") or
        info.get("title") or ""
    )
    if not title_en:
        return None

    image = item.get("pict_url") or info.get("main_image_url") or ""
    if image and image.startswith("//"):
        image = "https:" + image

    item_id = str(
        item.get("item_id") or item.get("num_iid") or
        hashlib.md5(f"{title_en}{price_cny}".encode()).hexdigest()[:10]
    )

    try:
        rating = float(info.get("shopDsr") or 4.5)
    except Exception:
        rating = 4.5
    rating = min(5.0, max(0.0, rating))

    url = item.get("item_url") or f"{BASE_URL}/item-{item_id}.html"
    if "taobao.com" in url or "tmall.com" in url:
        url = f"{BASE_URL}/item-{item_id}.html"

    return {
        "source": "cssbuy",
        "source_platform": "taobao",
        "source_id": f"cssbuy_tb_{item_id}",
        "title": info.get("title") or title_en,
        "title_translated": title_en,
        "price_cny": price_cny,
        "orders": 0,
        "rating": rating,
        "images": [image] if image else [],
        "url": url,
        "category": "",
        "keyword": keyword,
        "merchant": info.get("shop_name") or "",
    }


# ── JSON helpers ───────────────────────────────────────────────────────────────

def _find_product_array(data, depth: int = 0) -> Optional[list]:
    if depth > 6:
        return None
    if isinstance(data, list) and len(data) >= 1 and isinstance(data[0], dict):
        return data
    if isinstance(data, dict):
        for key in ("data", "list", "items", "records", "result", "products", "goods", "rows"):
            if key in data:
                r = _find_product_array(data[key], depth + 1)
                if r:
                    return r
        for v in data.values():
            r = _find_product_array(v, depth + 1)
            if r:
                return r
    return None


def _merge_raw_items(responses: list) -> list:
    seen: set = set()
    out: list = []
    for data in responses:
        for item in (_find_product_array(data) or []):
            uid = str(
                item.get("offerId") or item.get("item_id") or
                item.get("num_iid") or item.get("id") or ""
            )
            if uid and uid in seen:
                continue
            if uid:
                seen.add(uid)
            out.append(item)
    return out


# ── Login ──────────────────────────────────────────────────────────────────────

async def _check_login(page) -> bool:
    try:
        await page.goto(f"{BASE_URL}/web/user", wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(1)
        return "login" not in page.url
    except Exception:
        return False


async def _login(page, username: str, password: str, captcha_key: str) -> None:
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=20000)
    await asyncio.sleep(1.5)
    await page.fill(_SEL_USERNAME, username)
    await page.fill(_SEL_PASSWORD, password)

    if captcha_key:
        captcha_img = await page.query_selector(_SEL_CAPTCHA_IMG)
        if captcha_img:
            solution = await _solve_image_captcha(page, captcha_img, captcha_key)
            if solution:
                await page.fill(_SEL_CAPTCHA_IN, solution)
        recaptcha_el = await page.query_selector(_SEL_RECAPTCHA)
        if recaptcha_el:
            token = await _solve_recaptcha(captcha_key)
            if token:
                await page.evaluate(
                    "document.querySelector('#g-recaptcha-response,"
                    "textarea[name=g-recaptcha-response]').value = arguments[0]",
                    token,
                )
        await page.click(_SEL_SUBMIT)
        timeout_ms = 25000
    else:
        log.info("CSSBuy: browser open — solve captcha and click Login (5 min timeout)")
        timeout_ms = 300000

    try:
        await page.wait_for_function(
            "!window.location.href.includes('/login')", timeout=timeout_ms
        )
    except Exception:
        raise RuntimeError(f"CSSBuy login failed — still on {page.url}")


async def _solve_image_captcha(page, img_element, captcha_key: str) -> Optional[str]:
    try:
        from twocaptcha import TwoCaptcha
        import base64
        b64 = base64.b64encode(await img_element.screenshot()).decode()
        return (TwoCaptcha(captcha_key).normal(b64) or {}).get("code") or None
    except Exception as e:
        log.warning("CSSBuy: image captcha failed: %s", e)
        return None


async def _solve_recaptcha(captcha_key: str) -> Optional[str]:
    try:
        from twocaptcha import TwoCaptcha
        return (TwoCaptcha(captcha_key).recaptcha(sitekey=RECAPTCHA_SITEKEY, url=LOGIN_URL) or {}).get("code") or None
    except Exception as e:
        log.warning("CSSBuy: reCAPTCHA failed: %s", e)
        return None


# ── Session helpers ────────────────────────────────────────────────────────────

async def _restore_context(browser):
    if SESSION_FILE.exists():
        try:
            storage = json.loads(SESSION_FILE.read_text())
            log.info("CSSBuy: restoring session")
            return await browser.new_context(storage_state=storage)
        except Exception as e:
            log.warning("CSSBuy: session restore failed: %s", e)
    return await browser.new_context()


async def _save_session(ctx) -> None:
    SESSION_FILE.write_text(json.dumps(await ctx.storage_state()))
    log.info("CSSBuy: session saved")
