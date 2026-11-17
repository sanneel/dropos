"""Add by link: reading product pages, refusing unsafe addresses, shaping the result for DropOS."""
import asyncio
import json

import httpx
import pytest

import link_import as li


def run(coro):
    return asyncio.run(coro)


# ── numbers and money ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, currency, expected", [
    ("1,234.56", None, 1234.56), ("1.234,56", None, 1234.56), ("12,34", None, 12.34),
    ("1 234,56", None, 1234.56), ("1,234", None, 1234), ("4.56", None, 4.56),
    ("1.299", "TRY", 1299), ("1.299", "USD", 1.299), ("abc", None, None), (79, None, 79.0),
])
def test_numbers_in_every_common_price_format(raw, currency, expected):
    assert li.parse_number(raw, currency) == expected


def test_money_with_symbols_codes_and_ranges():
    assert li.parse_money("US $12.34") == {"amount": 12.34, "currency": "USD"}
    assert li.parse_money("1.299,90 TL") == {"amount": 1299.9, "currency": "TRY"}
    assert li.parse_money("₾15.03") == {"amount": 15.03, "currency": "GEL"}
    assert li.parse_money("€ 9,99") == {"amount": 9.99, "currency": "EUR"}
    assert li.parse_money("$1.20 - $3.40") == {"amount": 1.2, "currency": "USD", "max": 3.4}
    assert li.parse_money("79", "GEL") == {"amount": 79, "currency": "GEL"}
    assert li.parse_money("free shipping") is None
    assert li.parse_money("0.00 USD") is None


def test_finds_the_link_inside_pasted_or_shared_text():
    assert li.extract_url("look: https://shop.example/p/1?x=2.") == "https://shop.example/p/1?x=2"
    assert li.extract_url("shop.example/vase") == "https://shop.example/vase"
    assert li.extract_url("(https://shop.example/a)") == "https://shop.example/a"
    assert li.extract_url("no link here") is None
    assert li.extract_url("") is None


def test_reads_name_and_price_from_a_shopping_app_share_text():
    shared = li.parse_share_text(
        "I just found this on AliExpress: US $4.56 | Nordic Ceramic Vase Home Decoration Flower Pot https://a.aliexpress.com/_abc")
    assert shared["title"] == "Nordic Ceramic Vase Home Decoration Flower Pot"
    assert shared["price"] == {"amount": 4.56, "currency": "USD", "max": None}
    assert li.parse_share_text("https://shop.example/x") == {"title": None, "price": None}


def test_photo_addresses_become_the_full_size_https_version():
    assert li.normalize_image("//ae01.alicdn.com/kf/Sabc.jpg_220x220.jpg_.webp",
                              "https://www.aliexpress.com/item/1.html") == "https://ae01.alicdn.com/kf/Sabc.jpg"
    assert li.normalize_image("https://cdn.shopify.com/s/files/1/vase_100x100.jpg?v=1&width=200",
                              "https://x.example") == "https://cdn.shopify.com/s/files/1/vase.jpg?v=1"
    assert li.normalize_image("https://m.media-amazon.com/images/I/61abc._AC_SX342_.jpg",
                              "https://www.amazon.com/dp/B0") == "https://m.media-amazon.com/images/I/61abc.jpg"
    assert li.normalize_image("/img/a.png", "http://shop.example/p/1") == "https://shop.example/img/a.png"
    assert li.normalize_image("data:image/png;base64,AAAA", "https://x.example") is None
    assert li.normalize_image("javascript:alert(1)", "https://x.example") is None
    assert li.unique_images(["/a.jpg", "/a.jpg?v=2", "/b.jpg"], "https://x.example") == [
        "https://x.example/a.jpg", "https://x.example/b.jpg"]


def test_titles_lose_the_shop_name_but_keep_their_own_words():
    assert li.clean_title("Ceramic Vase 23cm - AliExpress 15", None, "www.aliexpress.com") == "Ceramic Vase 23cm"
    assert li.clean_title("Blue Vase | My Decor Shop", "My Decor Shop", "mydecor.example") == "Blue Vase"
    assert li.clean_title("Blue Vase - Workshop Edition", None, "shop.example.com") == "Blue Vase - Workshop Edition"
    assert li.clean_title("Tom &amp; Jerry   mug", None, "x.example") == "Tom & Jerry mug"


# ── reading pages ─────────────────────────────────────────────────────────────

JSONLD_PAGE = """<!doctype html><html><head>
<title>Ceramic Vase | Decor Shop</title>
<meta property="og:site_name" content="Decor Shop">
<meta property="og:image" content="https://cdn.decor.example/vase-og.jpg">
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"BreadcrumbList","itemListElement":[]},
  {"@type":"Product","name":"Ceramic Vase, 23 cm","description":"<p>Hand glazed.</p>",
   "image":["https://cdn.decor.example/vase-1.jpg",{"@type":"ImageObject","url":"https://cdn.decor.example/vase-2.jpg"}],
   "brand":{"@type":"Brand","name":"Atelier"},
   "aggregateRating":{"ratingValue":"4.7","reviewCount":"132"},
   "offers":{"@type":"Offer","price":"5.20","priceCurrency":"USD","availability":"https://schema.org/InStock"}}
]}
</script></head><body><h1>Ceramic Vase, 23 cm</h1></body></html>"""


def test_jsonld_product_page():
    p = run(li.extract_product(JSONLD_PAGE, "https://decor.example/p/vase"))
    assert p["title"] == "Ceramic Vase, 23 cm"
    assert p["cost"] == {"amount": 5.2, "currency": "USD", "max": None}
    assert p["images"] == ["https://cdn.decor.example/vase-1.jpg", "https://cdn.decor.example/vase-2.jpg",
                           "https://cdn.decor.example/vase-og.jpg"]
    assert p["description"] == "Hand glazed."
    assert p["brand"] == "Atelier"
    assert p["rating"] == 4.7
    assert p["missing"] == []
    assert "jsonld" in p["method"]


def test_jsonld_with_several_offers_takes_the_lowest_and_reports_the_range():
    page = """<script type="application/ld+json">{"@type":"Product","name":"Linen Pillow Cover","image":"https://x.example/p.jpg",
      "offers":[{"@type":"Offer","price":12,"priceCurrency":"EUR"},{"@type":"Offer","price":"9.5","priceCurrency":"EUR"}]}</script>"""
    assert run(li.extract_product(page, "https://x.example/p"))["cost"] == {"amount": 9.5, "currency": "EUR", "max": 12}


def test_open_graph_page_with_a_price_in_the_meta_tags():
    page = """<head><meta property="og:type" content="product">
      <meta property="og:title" content="Rattan Lamp | Lamps.ge"><meta property="og:site_name" content="Lamps.ge">
      <meta property="og:image" content="/media/lamp.jpg">
      <meta property="product:price:amount" content="149.00"><meta property="product:price:currency" content="GEL"></head>"""
    p = run(li.extract_product(page, "https://lamps.ge/p/rattan"))
    assert p["title"] == "Rattan Lamp"
    assert p["cost"] == {"amount": 149, "currency": "GEL", "max": None}
    assert p["images"] == ["https://lamps.ge/media/lamp.jpg"]


def test_plain_page_without_structured_data():
    page = """<title>A Light in the Attic | Books</title><h1>A Light in the Attic</h1>
      <p class="price_color">£51.77</p><p class="old-price">£60.00</p>
      <img src="../media/cover.jpg" width="400" height="600"><img src="/static/logo.png">"""
    p = run(li.extract_product(page, "https://books.example/catalogue/a/index.html"))
    assert p["title"] == "A Light in the Attic"
    assert p["cost"] == {"amount": 51.77, "currency": "GBP", "max": None}
    assert p["images"] == ["https://books.example/catalogue/media/cover.jpg"]


def test_category_pages_are_not_mistaken_for_a_product():
    prices = "".join(f'<span class="price">${n}.00</span>' for n in (19, 29, 39, 49, 59, 79))
    page = f"""<head><meta property="og:type" content="product.group"><meta property="og:title" content="Bookcases">
      <meta property="og:image" content="https://x.example/cat.jpg"></head><h1>Bookcases</h1>{prices}"""
    assert run(li.extract_product(page, "https://x.example/cat/bookcases")) is None


def test_shopify_shops_get_every_photo_from_the_product_feed():
    page = """<head><link href="https://cdn.shopify.com/s/theme.css"><script>Shopify.currency = {"active":"USD","rate":"1.0"};</script>
      <meta property="og:title" content="Wool Throw"><meta property="og:image" content="https://cdn.shopify.com/s/files/1/throw_600x.jpg"></head>"""
    asked = []

    async def fetcher(url):
        asked.append(url)
        return json.dumps({"title": "Wool Throw", "description": "<p>Soft.</p>", "vendor": "Hearth",
                           "price": 4500, "price_min": 4500, "price_max": 5200, "available": True,
                           "images": ["//cdn.shopify.com/s/files/1/throw.jpg", "//cdn.shopify.com/s/files/1/throw-2.jpg"]})

    p = run(li.extract_product(page, "https://hearth.example/products/wool-throw?variant=1", fetcher))
    assert asked == ["https://hearth.example/products/wool-throw.js"]
    assert p["cost"] == {"amount": 45, "currency": "USD", "max": 52}
    assert p["images"] == ["https://cdn.shopify.com/s/files/1/throw.jpg", "https://cdn.shopify.com/s/files/1/throw-2.jpg"]
    assert p["brand"] == "Hearth"


def test_aliexpress_page_data_embedded_in_scripts():
    page = r"""<title>x</title><script>window.runParams = {"data":{"imageComponent":{"imagePathList":
      ["https://ae01.alicdn.com/kf/A1.jpg_.webp","https://ae01.alicdn.com/kf/A2.jpg"]},
      "productInfoComponent":{"subject":"Nordic Vase \"Luna\" 20cm"},
      "priceComponent":{"formatedActivityPrice":"US $4.56"}}};</script>"""
    p = run(li.extract_product(page, "https://www.aliexpress.com/item/100.html"))
    assert p["title"] == 'Nordic Vase "Luna" 20cm'
    assert p["cost"] == {"amount": 4.56, "currency": "USD", "max": None}
    assert p["images"] == ["https://ae01.alicdn.com/kf/A1.jpg", "https://ae01.alicdn.com/kf/A2.jpg"]
    assert p["site"] == "AliExpress"


def test_browser_button_snapshot_takes_the_biggest_price_and_ignores_struck_out_ones():
    page = """<title>Woven Basket - Some Store</title><h1>Woven Basket</h1>
      <span class="price was strike" data-fs="14">$40.00</span>
      <span class="price current" data-fs="28">$24.00</span>
      <span class="price shipping" data-fs="12">$3.00</span>
      <img src="https://img.store.example/b1.jpg" width="1200" height="1200">
      <img src="https://img.store.example/b2.jpg" width="800" height="800">"""
    p = run(li.import_from_snapshot(page, "https://store.example/item/9"))
    assert p["title"] == "Woven Basket"
    assert p["cost"]["amount"] == 24
    assert len(p["images"]) == 2


def test_captcha_and_error_pages_are_blocked_not_parsed():
    wall = '<script>window._config_ = {"action":"captcha","url":"/punish"}</script>'
    assert run(li.extract_product(wall, "https://www.aliexpress.com/item/1.html")) is None
    assert li.looks_blocked(200, wall) is True
    assert li.looks_blocked(403, "") is True
    assert li.looks_blocked(200, "<h1>Our story</h1>") is False


# ── fetching ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "http://localhost/admin", "http://127.0.0.1/", "http://2130706433/", "http://[::1]/",
    "http://169.254.169.254/latest/meta-data/", "http://10.0.0.5/", "http://192.168.1.1/",
    "http://intranet/", "https://printer.local/", "https://shop.example:8443/",
    "https://user:pass@shop.example/", "file:///etc/passwd", "ftp://shop.example/x",
])
def test_the_fetcher_refuses_anything_that_is_not_a_public_web_address(url):
    with pytest.raises(li.FetchError) as caught:
        run(li.fetch_page(url))
    assert caught.value.code == "unsafe"


def _site(pages):
    def handler(request: httpx.Request) -> httpx.Response:
        page = pages.get(request.url.path)
        if page is None:
            return httpx.Response(404, html="<title>Not found</title>")
        status, body, headers = page
        return httpx.Response(status, content=body.encode(), headers={"content-type": "text/html; charset=utf-8", **headers})
    return httpx.MockTransport(handler)


def test_import_follows_redirects_and_tells_the_outcomes_apart():
    site = _site({
        "/short": (302, "", {"location": "/vase"}),
        "/vase": (200, JSONLD_PAGE, {}),
        "/about": (200, "<title>About us</title><h1>Our story</h1>", {}),
        "/wall": (403, "<title>Access denied</title>", {}),
        "/down": (502, "<title>Bad gateway</title>", {}),
    })
    go = lambda text: run(li.import_from_text(text, allow_private=True, transport=site))

    ok = go("look at this http://shop.test/short")
    assert ok["ok"] and ok["product"]["title"] == "Ceramic Vase, 23 cm"
    assert ok["product"]["source_url"] == "http://shop.test/vase"

    assert go("just words")["reason"] == "no_url"
    assert go("http://shop.test/about")["reason"] == "not_product"
    assert go("http://shop.test/missing")["reason"] == "not_product"
    assert go("http://shop.test/down")["reason"] == "fetch_failed"
    blocked = go("I just found this on AliExpress: US $4.56 | Nordic Ceramic Vase Flower Pot http://shop.test/wall")
    assert blocked["reason"] == "blocked"
    assert blocked["shared"]["title"] == "Nordic Ceramic Vase Flower Pot"
    # Without the test switch the same address is refused outright.
    assert run(li.import_from_text("http://127.0.0.1/vase"))["reason"] == "unsafe"


def test_a_redirect_into_the_private_network_is_refused():
    site = _site({"/go": (302, "", {"location": "http://169.254.169.254/latest/meta-data/"})})

    async def attempt():
        # First hop is allowed through by hand; the redirect target must still be checked.
        original = li._check_url
        seen = []

        async def check(url, allow_private):
            seen.append(url)
            return await original(url, allow_private=(len(seen) == 1))

        li._check_url = check
        try:
            return await li.fetch_page("http://shop.test/go", transport=site)
        finally:
            li._check_url = original

    with pytest.raises(li.FetchError) as caught:
        run(attempt())
    assert caught.value.code == "unsafe"


# ── into DropOS ───────────────────────────────────────────────────────────────

def test_the_same_page_always_gets_the_same_id():
    a = li.source_id_for("https://www.shop.example/p/vase/?utm_source=ig&color=blue")
    b = li.source_id_for("http://shop.example/p/vase?color=blue&fbclid=abc")
    assert a == b and a.startswith("link_")
    assert a != li.source_id_for("https://shop.example/p/vase?color=red")


def test_an_imported_product_is_shaped_and_priced_like_a_scraped_one():
    settings = {"exchange_rate": 0.36, "sell_markup_low": 3.5, "sell_markup_mid": 2.8, "sell_markup_high": 2.2}
    product = {"title": "Ceramic Vase, 23 cm", "description": "Hand glazed.", "site": "decor.example",
               "images": [f"https://cdn.decor.example/{i}.jpg" for i in range(14)],
               "cost": {"amount": 5.2, "currency": "USD", "max": None}, "rating": 4.7,
               "source_url": "https://decor.example/p/vase"}
    row = li.to_dropos_product(product, settings, {"USD": 2.7}, brand_id=3)
    assert row["source"] == "link" and row["stage"] == "SCRAPED" and row["brand_id"] == 3
    assert row["cost_eur"] == 14.04                 # 5.20 USD at 2.70
    assert row["price_cny"] == 39.0                 # the same cost in the store's ¥ terms
    assert row["sell_price_eur"] == 44.9            # 14.04 × 2.8 = 39.3 → snapped like every DropOS price
    assert row["margin_pct"] == 68.7
    assert len(row["images"]) == 10
    assert row["url"] == "https://decor.example/p/vase"

    cheap = li.to_dropos_product({**product, "cost": {"amount": 20, "currency": "CNY"}}, settings, {}, None)
    assert cheap["cost_eur"] == 7.2 and cheap["price_cny"] == 20.0 and cheap["sell_price_eur"] == 44.9

    unknown = li.to_dropos_product({**product, "cost": None}, settings, {"USD": 2.7}, None)
    assert unknown["cost_eur"] == 0 and unknown["sell_price_eur"] == 0


def test_the_browser_button_is_a_self_contained_bookmark():
    href = li.bookmarklet_href("https://dropos.example", "tok_123")
    assert href.startswith("javascript:")
    from urllib.parse import unquote
    code = unquote(href[len("javascript:"):])
    assert code.startswith("(function clip(BASE, TOKEN)")
    assert code.endswith('("https://dropos.example","tok_123")')
    assert "/api/import/clip" in code
