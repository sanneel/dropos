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
    """Navigate to search results and parse HTML product cards.

    Real URL verified from live site: /productlist?keyWork={keyword}
    Card selector verified: .itemlist .item
    """
    # Real search URL (verified from live site inspection)
    search_url = f"{BASE_URL}/productlist?keyWork={quote(keyword)}"
    await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)

    # Dismiss "Search Terms" modal if it appears
    try:
        accept_btn = await page.wait_for_selector("button:has-text('Accept'), .btn-confirm, [class*='confirm']", timeout=4000)
        if accept_btn:
            await accept_btn.click()
            log.info("CSSBuy: dismissed search terms modal")
            await asyncio.sleep(1.5)
    except Exception:
        pass  # modal didn't appear

    # Wait for Vue to replace skeleton placeholders with real product images
    try:
        await page.wait_for_function(
            "document.querySelectorAll('.itemlist .item img').length > 0",
            timeout=20000,
        )
        log.info("CSSBuy: product images appeared — data loaded")
    except Exception:
        log.warning("CSSBuy: timed out waiting for products to load on '%s'", keyword)

    await asyncio.sleep(1)

    # Scroll to trigger more lazy-loaded items
    for _ in range(3):
        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await asyncio.sleep(0.8)

    log.info("CSSBuy search landed on: %s", page.url)

    products = await _parse_html(page, keyword)

    if not products:
        debug_dir = Path(__file__).parent
        try:
            await page.screenshot(path=str(debug_dir / "cssbuy_search_debug.png"), full_page=True)
            html = await page.content()
            (debug_dir / "cssbuy_search_debug.html").write_text(html[:50000], encoding="utf-8")
            log.warning("CSSBuy: 0 products for '%s'. Debug screenshot + HTML saved.", keyword)
        except Exception as e:
            log.warning("CSSBuy: 0 products for '%s', debug save failed: %s", keyword, e)

    return products[:max_results]


# ── Unused XHR helpers kept for reference ─────────────────────────────────────

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
    """Parse product cards from /productlist page.

    Verified card structure (from live site inspection):
      .itemlist .item
        img.taobaoicon  — platform icon, skip
        img             — product image
        p               — title
        span            — price as "¥CNY($USD)"
    """
    products = []
    cards = await page.query_selector_all(".itemlist .item")
    log.info("CSSBuy HTML: found %d cards", len(cards))

    for card in cards:
        try:
            imgs   = await card.query_selector_all("img")
            title_el = await card.query_selector("p")
            price_el = await card.query_selector("span")

            # Second img is the product image (first is the platform icon)
            product_img = imgs[1] if len(imgs) >= 2 else (imgs[0] if imgs else None)
            img_src = await product_img.get_attribute("src") if product_img else ""
            if not img_src and product_img:
                img_src = await product_img.get_attribute("data-src") or ""

            title = (await title_el.inner_text()).strip() if title_el else ""
            price_txt = (await price_el.inner_text()).strip() if price_el else ""

            # Price format: "¥10.98($1.61)" — extract CNY value
            cny_match = re.search(r"[¥￥]([\d.]+)", price_txt)
            price_cny = float(cny_match.group(1)) if cny_match else 0.0
            if not price_cny:
                continue

            if img_src and img_src.startswith("//"):
                img_src = "https:" + img_src

            # Use image filename as stable product ID
            img_id = re.search(r"/([^/]+)\.\w+$", img_src or "")
            source_id = "cssbuy_" + (img_id.group(1) if img_id else hashlib.md5(f"{title}{price_cny}".encode()).hexdigest()[:12])

            products.append({
                "source": "cssbuy",
                "source_id": source_id,
                "title": title,
                "title_translated": title,
                "price_cny": price_cny,
                "orders": 0,
                "rating": 4.5,
                "images": [img_src] if img_src else [],
                "url": f"{BASE_URL}/productlist?keyWork={quote(keyword)}",
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
