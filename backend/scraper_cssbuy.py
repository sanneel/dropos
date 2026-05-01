"""
CSSBuy scraper — Playwright-based login + HTML parsing.

Verified from live site inspection (cssbuy.com/login):
  - Username:  input#username  (name="username")
  - Password:  input#password  (name="password")
  - Image captcha: img#captcha_img  (src=/captcha/admin?...)
  - Captcha input: input#code  (name="captcha")
  - reCAPTCHA:  div.g-recaptcha  (sitekey=6LeJ_noqAAAAAIOBR2APiofxlH0DQuEsm1qace0t)
  - Submit:  p#login.button  (click — no onclick, handled by JS event listener)

Search results are server-side rendered HTML at:
  /search?keyword={keyword}&source=taobao

Flow:
  1. Restore saved session cookies → skip login if still valid
  2. If not logged in: fill form → solve image captcha → solve reCAPTCHA → click submit
  3. For each keyword: navigate to search → parse HTML product cards
"""

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote

log = logging.getLogger(__name__)

SESSION_FILE = Path(__file__).parent / "cssbuy_session.json"
BASE_URL = "https://www.cssbuy.com"
LOGIN_URL = f"{BASE_URL}/login"
RECAPTCHA_SITEKEY = "6LeJ_noqAAAAAIOBR2APiofxlH0DQuEsm1qace0t"

# Verified selectors from live site inspection
_SEL_USERNAME     = "#username"
_SEL_PASSWORD     = "#password"
_SEL_CAPTCHA_IMG  = "#captcha_img"
_SEL_CAPTCHA_IN   = "#code"
_SEL_RECAPTCHA    = ".g-recaptcha"
_SEL_SUBMIT       = "p#login"


async def scrape(
    keywords: list,
    max_per_keyword: int = 50,
    username: str = "",
    password: str = "",
    captcha_key: str = "",
) -> list:
    """Entry point — returns list of products in DropOS format."""
    if not username or not password:
        log.warning("CSSBuy credentials not set — skipping")
        return []

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
        return []

    # Show browser window when no captcha solver → manual captcha solve
    headless = bool(captcha_key)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = await _restore_context(browser)
        page = await ctx.new_page()
        await page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

        try:
            logged_in = await _check_login(page)
            if not logged_in:
                log.info("CSSBuy: not logged in, starting login flow")
                await _login(page, username, password, captcha_key)
                await _save_session(ctx)
                log.info("CSSBuy: login successful, session saved")
            else:
                log.info("CSSBuy: session still valid, skipping login")

            products: list = []
            for keyword in keywords:
                kw_products = await _search(page, keyword, max_per_keyword)
                log.info("CSSBuy: keyword '%s' → %d products", keyword, len(kw_products))
                products.extend(kw_products)

            return products

        except Exception as e:
            log.error("CSSBuy scrape error: %s", e)
            try:
                await page.screenshot(path=str(Path(__file__).parent / "cssbuy_debug.png"))
                log.info("Debug screenshot saved to backend/cssbuy_debug.png")
            except Exception:
                pass
            return []
        finally:
            await browser.close()


# ── Login ──────────────────────────────────────────────────────────────────────

async def _check_login(page) -> bool:
    """Returns True if current session is still authenticated."""
    try:
        await page.goto(f"{BASE_URL}/web/user", wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(1)
        return "login" not in page.url
    except Exception:
        return False


async def _login(page, username: str, password: str, captcha_key: str) -> None:
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=20000)
    await asyncio.sleep(1.5)

    # Pre-fill credentials in both cases
    await page.fill(_SEL_USERNAME, username)
    await page.fill(_SEL_PASSWORD, password)

    if captcha_key:
        # Auto mode: solve both captchas then click submit
        captcha_img = await page.query_selector(_SEL_CAPTCHA_IMG)
        if captcha_img:
            log.info("CSSBuy: solving image captcha via 2captcha...")
            solution = await _solve_image_captcha(page, captcha_img, captcha_key)
            if solution:
                await page.fill(_SEL_CAPTCHA_IN, solution)
                log.info("CSSBuy: image captcha filled: '%s'", solution)

        recaptcha_el = await page.query_selector(_SEL_RECAPTCHA)
        if recaptcha_el:
            log.info("CSSBuy: solving reCAPTCHA via 2captcha...")
            token = await _solve_recaptcha(captcha_key)
            if token:
                await page.evaluate(
                    "document.querySelector('#g-recaptcha-response,textarea[name=g-recaptcha-response]').value = arguments[0]",
                    token,
                )
                log.info("CSSBuy: reCAPTCHA token injected")

        await page.click(_SEL_SUBMIT)
        timeout_ms = 25000
    else:
        # Manual mode: browser is visible, credentials are pre-filled.
        # Just wait for the user to solve captcha and click Login themselves.
        log.info(
            "CSSBuy: browser window is open with credentials pre-filled. "
            "Please solve the captcha and click Login. Waiting up to 5 minutes..."
        )
        timeout_ms = 300000  # 5 minutes

    try:
        await page.wait_for_function(
            "!window.location.href.includes('/login')",
            timeout=timeout_ms,
        )
    except Exception:
        raise RuntimeError(
            f"CSSBuy login failed — still on {page.url}. "
            "Add captcha_2captcha_key in Settings for auto-solve."
        )


async def _solve_image_captcha(page, img_element, captcha_key: str) -> Optional[str]:
    if not captcha_key:
        return None
    try:
        from twocaptcha import TwoCaptcha
        import base64
        solver = TwoCaptcha(captcha_key)
        img_bytes = await img_element.screenshot()
        b64 = base64.b64encode(img_bytes).decode()
        result = solver.normal(b64)
        return result.get("code", "") or None
    except Exception as e:
        log.warning("CSSBuy: 2captcha image solve failed: %s", e)
        return None


async def _solve_recaptcha(captcha_key: str) -> Optional[str]:
    if not captcha_key:
        return None
    try:
        from twocaptcha import TwoCaptcha
        solver = TwoCaptcha(captcha_key)
        result = solver.recaptcha(sitekey=RECAPTCHA_SITEKEY, url=LOGIN_URL)
        return result.get("code", "") or None
    except Exception as e:
        log.warning("CSSBuy: 2captcha reCAPTCHA solve failed: %s", e)
        return None


# ── Search ─────────────────────────────────────────────────────────────────────

async def _search(page, keyword: str, max_results: int) -> list:
    """Navigate to search results and parse HTML product cards."""
    captured_json: list = []

    async def handle_response(response):
        ct = response.headers.get("content-type", "")
        if "json" not in ct:
            return
        url = response.url
        if not any(x in url for x in ("search", "product", "item", "goods", "list", "api")):
            return
        try:
            data = await response.json()
            captured_json.append({"url": url, "data": data})
        except Exception:
            pass

    page.on("response", handle_response)

    search_url = f"{BASE_URL}/search?keyword={quote(keyword)}&source=taobao"
    await page.goto(search_url, wait_until="networkidle", timeout=30000)
    await asyncio.sleep(2)

    # Scroll to trigger lazy loading
    for _ in range(3):
        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await asyncio.sleep(0.8)

    page.remove_listener("response", handle_response)

    # Try XHR products first
    products = _extract_from_json(captured_json, keyword)

    # Try window.__INITIAL_STATE__ or similar embedded data
    if not products:
        products = await _extract_from_window(page, keyword)

    # Fallback: parse HTML cards
    if not products:
        log.info("CSSBuy: trying HTML parse for '%s'", keyword)
        products = await _parse_html(page, keyword)

    if not products:
        log.warning(
            "CSSBuy: 0 products for '%s'. XHR responses: %s",
            keyword,
            [c["url"] for c in captured_json],
        )

    return products[:max_results]


async def _extract_from_window(page, keyword: str) -> list:
    """Check window globals for embedded product data (common in Vue/React SSR sites)."""
    try:
        data = await page.evaluate("""
            (() => {
                for (const key of ['__INITIAL_STATE__','__NUXT__','__data__','__PAGE_DATA__','initialState']) {
                    if (window[key]) return window[key];
                }
                return null;
            })()
        """)
        if data:
            items = _find_product_array(data)
            if items:
                log.info("CSSBuy: found %d products in window globals", len(items))
                return [p for p in (_normalize(i, keyword, "window") for i in items) if p]
    except Exception as e:
        log.debug("CSSBuy: window global extraction failed: %s", e)
    return []


def _extract_from_json(captured: list, keyword: str) -> list:
    """Find product list in captured XHR JSON responses."""
    for capture in captured:
        items = _find_product_array(capture["data"])
        if items:
            log.info("CSSBuy: found %d items in XHR %s", len(items), capture["url"])
            return [p for p in (_normalize(i, keyword, capture["url"]) for i in items) if p]
    return []


def _find_product_array(data, depth: int = 0) -> Optional[list]:
    """Recursively search JSON for a list of product-like dicts."""
    if depth > 6:
        return None
    if isinstance(data, list) and len(data) >= 3:
        if isinstance(data[0], dict) and _looks_like_product(data[0]):
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


def _looks_like_product(d: dict) -> bool:
    has_price = any(k in d for k in ("price", "salePrice", "sale_price", "priceStr", "origin_price", "itemPrice"))
    has_title = any(k in d for k in ("title", "name", "goodsName", "goods_name", "productName", "itemTitle"))
    has_image = any(k in d for k in ("image", "img", "picUrl", "pic_url", "mainImage", "cover", "imgUrl"))
    return has_price and (has_title or has_image)


def _normalize(item: dict, keyword: str, source_url: str) -> Optional[dict]:
    price_raw = (
        item.get("price") or item.get("salePrice") or item.get("sale_price") or
        item.get("priceStr") or item.get("origin_price") or item.get("itemPrice") or 0
    )
    try:
        price_cny = float(re.sub(r"[^\d.]", "", str(price_raw))) if price_raw else 0
    except Exception:
        price_cny = 0
    if not price_cny:
        return None

    title = (
        item.get("title") or item.get("name") or item.get("goodsName") or
        item.get("goods_name") or item.get("productName") or item.get("itemTitle") or ""
    )

    image = (
        item.get("image") or item.get("img") or item.get("picUrl") or
        item.get("pic_url") or item.get("mainImage") or item.get("cover") or
        item.get("imgUrl") or ""
    )
    if image and not image.startswith("http"):
        image = "https:" + image if image.startswith("//") else BASE_URL + image

    item_id = str(
        item.get("id") or item.get("itemId") or item.get("goodsId") or
        item.get("goods_id") or item.get("productId") or item.get("numIid") or
        hashlib.md5(f"{title}{price_cny}".encode()).hexdigest()[:10]
    )

    orders_raw = (
        item.get("sold") or item.get("orders") or item.get("tradeCount") or
        item.get("salesVolume") or item.get("soldNum") or 0
    )
    try:
        orders = int(re.sub(r"[^\d]", "", str(orders_raw))) if orders_raw else 0
    except Exception:
        orders = 0

    rating = float(item.get("rating") or item.get("score") or item.get("rateScore") or 4.5)
    rating = min(5.0, max(0.0, rating))

    url = (
        item.get("url") or item.get("link") or item.get("detailUrl") or
        item.get("itemUrl") or item.get("taobaoUrl") or
        f"{BASE_URL}/item-{item_id}.html"
    )

    return {
        "source": "cssbuy",
        "source_id": f"cssbuy_{item_id}",
        "title": title,
        "title_translated": title,
        "price_cny": price_cny,
        "orders": orders,
        "rating": rating,
        "images": [image] if image else [],
        "url": url,
        "category": item.get("category") or item.get("catName") or "",
        "keyword": keyword,
        "merchant": item.get("shop") or item.get("shopName") or item.get("seller") or "",
    }


# ── HTML fallback ──────────────────────────────────────────────────────────────

async def _parse_html(page, keyword: str) -> list:
    """Parse product cards from server-rendered search HTML."""
    products = []
    selectors = [
        ".goods-item", ".product-item", ".item-wrap", ".search-item",
        "[class*='goods-list'] li", "[class*='item-list'] li",
        ".pitem", ".gitem", "ul.list > li", ".result-item",
    ]

    cards = []
    for sel in selectors:
        found = await page.query_selector_all(sel)
        if found:
            log.info("CSSBuy HTML: selector '%s' found %d cards", sel, len(found))
            cards = found
            break

    for card in cards:
        try:
            title_el = await card.query_selector("[class*='title'],[class*='name'],[class*='tit']")
            price_el = await card.query_selector("[class*='price'],[class*='Price']")
            img_el   = await card.query_selector("img")
            link_el  = await card.query_selector("a")

            title = (await title_el.inner_text()).strip() if title_el else ""
            price_txt = (await price_el.inner_text()).strip() if price_el else "0"
            img_src = await img_el.get_attribute("src") if img_el else ""
            if not img_src and img_el:
                img_src = await img_el.get_attribute("data-src") or ""
            link_href = await link_el.get_attribute("href") if link_el else ""

            price_cny = float(re.sub(r"[^\d.]", "", price_txt) or 0)
            if not price_cny:
                continue

            if img_src and not img_src.startswith("http"):
                img_src = "https:" + img_src if img_src.startswith("//") else BASE_URL + img_src
            if link_href and not link_href.startswith("http"):
                link_href = BASE_URL + link_href

            products.append({
                "source": "cssbuy",
                "source_id": "cssbuy_" + hashlib.md5(f"{title}{price_cny}".encode()).hexdigest()[:10],
                "title": title,
                "title_translated": title,
                "price_cny": price_cny,
                "orders": 0,
                "rating": 4.5,
                "images": [img_src] if img_src else [],
                "url": link_href or BASE_URL,
                "category": "",
                "keyword": keyword,
                "merchant": "",
            })
        except Exception:
            continue

    log.info("CSSBuy HTML parse: %d products from %d cards", len(products), len(cards))
    return products


# ── Session helpers ────────────────────────────────────────────────────────────

async def _restore_context(browser):
    if SESSION_FILE.exists():
        try:
            storage = json.loads(SESSION_FILE.read_text())
            log.info("CSSBuy: restoring session from %s", SESSION_FILE)
            return await browser.new_context(storage_state=storage)
        except Exception as e:
            log.warning("CSSBuy: could not restore session: %s", e)
    return await browser.new_context()


async def _save_session(ctx) -> None:
    storage = await ctx.storage_state()
    SESSION_FILE.write_text(json.dumps(storage))
    log.info("CSSBuy: session saved to %s", SESSION_FILE)
