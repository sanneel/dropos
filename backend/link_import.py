"""
Add a product by link.

The merchant pastes a product page address (or the whole text a shopping app
shares) and gets a filled product: photos, name, cost. Several readers run and
the best answer for each field wins:

  1. site adapter  — Amazon, AliExpress page data, Shopify product feed
  2. JSON-LD       — schema.org Product, used by most modern shops
  3. meta tags     — Open Graph / product:price
  4. page reading  — headline, the largest price on screen, large photos

Sites that answer a server with a captcha or a refusal (AliExpress, Temu,
Trendyol, Etsy, eBay…) are reported as "blocked". Nothing here tries to get
around those checks. For them there is the "Add to DropOS" browser button: it
runs in the merchant's own browser on the page they are already looking at and
sends a snapshot here (see clip_source / import_from_snapshot).

Only httpx and the standard library are used.
"""

import asyncio
import hashlib
import html as html_lib
import ipaddress
import json
import logging
import re
from typing import Awaitable, Callable, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx

log = logging.getLogger(__name__)


# ══ Text and number helpers ══════════════════════════════════════════════════

_CODES = ("USD EUR GBP GEL TRY RUB CNY JPY PLN UAH AMD AZN AED CAD AUD CHF SEK NOK DKK CZK HUF RON "
          "BGN ILS KZT INR KRW SAR QAR BRL MXN HKD SGD").split()
_ALIAS = {"RMB": "CNY", "TL": "TRY"}
_CODE_RE = re.compile(r"(?:^|[^A-Za-z])(" + "|".join(_CODES) + r"|RMB|TL)(?![A-Za-z])", re.I)
# Longer symbols first so "US$" wins over "$".
_SYMBOLS = [
    ("US$", "USD"), ("US $", "USD"), ("CA$", "CAD"), ("C$", "CAD"), ("AU$", "AUD"), ("A$", "AUD"),
    ("HK$", "HKD"), ("R$", "BRL"), ("₾", "GEL"), ("ლარი", "GEL"), ("€", "EUR"), ("£", "GBP"),
    ("₺", "TRY"), ("₽", "RUB"), ("руб", "RUB"), ("￥", "CNY"), ("¥", "CNY"), ("元", "CNY"),
    ("zł", "PLN"), ("₴", "UAH"), ("֏", "AMD"), ("₼", "AZN"), ("₪", "ILS"), ("₸", "KZT"),
    ("₹", "INR"), ("₩", "KRW"), ("$", "USD"),
]
# Currencies whose sites usually write 1.299 for one thousand two hundred ninety-nine.
_DOT_THOUSANDS = {"EUR", "TRY", "RUB", "PLN", "UAH", "BRL", "DKK", "NOK", "SEK", "CZK", "HUF", "RON", "KZT"}
_NUMBER_RE = re.compile(r"\d{1,3}(?:[   ']\d{3})+(?:[.,]\d+)?|\d[\d.,]*\d|\d")
_TLD_CURRENCY = {"ge": "GEL", "tr": "TRY", "ru": "RUB", "cn": "CNY", "uk": "GBP", "de": "EUR", "fr": "EUR",
                 "it": "EUR", "es": "EUR", "nl": "EUR", "pl": "PLN", "ua": "UAH", "am": "AMD", "az": "AZN",
                 "jp": "JPY", "ae": "AED"}


def normalize_currency(value) -> Optional[str]:
    code = str(value or "").strip().upper()
    code = _ALIAS.get(code, code)
    return code if code in _CODES else None


def parse_number(raw, currency: Optional[str] = None) -> Optional[float]:
    """'1,234.56', '1.234,56', '12,34', '1 234,56' -> float."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = re.sub(r"[\s  ']", "", str(raw if raw is not None else ""))
    s = re.sub(r"[^\d.,]", "", s).strip(".,")
    if not re.search(r"\d", s):
        return None
    has_dot, has_comma = "." in s, "," in s
    decimal = None
    if has_dot and has_comma:
        decimal = "." if s.rfind(".") > s.rfind(",") else ","
    elif has_comma:
        groups = s.split(",")
        decimal = "," if len(groups) == 2 and len(groups[1]) != 3 else None
    elif has_dot:
        groups = s.split(".")
        if len(groups) > 2 or (len(groups[1]) == 3 and currency in _DOT_THOUSANDS):
            decimal = None
        else:
            decimal = "."
    if decimal:
        i = s.rfind(decimal)
        clean = re.sub(r"[.,]", "", s[:i]) + "." + s[i + 1:]
    else:
        clean = re.sub(r"[.,]", "", s)
    try:
        return float(clean)
    except ValueError:
        return None


def parse_money(text, fallback_currency: Optional[str] = None) -> Optional[dict]:
    """'US $12.34', '1.299,90 TL', '$1.20 - $3.40' -> {amount, currency, max?}"""
    if text is None:
        return None
    s = re.sub(r"\s+", " ", html_lib.unescape(str(text))).strip()
    if not s or len(s) > 80:
        return None
    currency = None
    code = _CODE_RE.search(s)
    if code:
        upper = code.group(1).upper()
        currency = _ALIAS.get(upper, upper)
    else:
        currency = next((cur for symbol, cur in _SYMBOLS if symbol in s), None)
    currency = currency or fallback_currency
    numbers = list(_NUMBER_RE.finditer(s))
    if not numbers:
        return None
    amount = parse_number(numbers[0].group(0), currency)
    if amount is None or amount <= 0:
        return None
    out = {"amount": amount, "currency": currency}
    if len(numbers) > 1:
        between = s[numbers[0].end():numbers[1].start()]
        if re.search(r"[-–—~]|\bto\b", between):
            top = parse_number(numbers[1].group(0), currency)
            if top is not None and top > amount:
                out["max"] = top
    return out


def strip_tags(markup) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|template)\b.*?</\1\s*>", " ", str(markup or ""))
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", text)
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"[ \t\r\f\v ]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def clean_text(value, limit: int = 2000) -> str:
    text = strip_tags(value)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


_SITE_LABELS = [
    (r"(^|\.)aliexpress\.(com|us|ru)$", "AliExpress"), (r"(^|\.)temu\.com$", "Temu"),
    (r"(^|\.)trendyol\.com$", "Trendyol"), (r"(^|\.)amazon\.[a-z.]+$", "Amazon"),
    (r"(^|\.)ebay\.[a-z.]+$", "eBay"), (r"(^|\.)etsy\.com$", "Etsy"),
    (r"(^|\.)alibaba\.com$", "Alibaba"), (r"(^|\.)shein\.[a-z.]+$", "SHEIN"),
    (r"(^|\.)taobao\.com$", "Taobao"), (r"(^|\.)1688\.com$", "1688"),
]


def site_label(hostname: str) -> str:
    host = re.sub(r"^www\.", "", str(hostname or "").lower())
    return next((label for pattern, label in _SITE_LABELS if re.search(pattern, host)), host)


def currency_from_host(hostname: str) -> Optional[str]:
    return _TLD_CURRENCY.get(str(hostname or "").lower().rsplit(".", 1)[-1])


def clean_title(value, site_name: Optional[str], hostname: str) -> str:
    """Tidies a page title: drops the shop's own name from either end."""
    s = re.sub(r"\s+", " ", clean_text(value, 400)).strip()
    if not s:
        return ""
    host = re.sub(r"^www\.", "", str(hostname or "").lower())
    generic = {"shop", "store", "www", "online", "market", "home"}
    brands = {b.lower().strip() for b in (site_name, site_label(host), host, host.split(".")[0]) if b and len(b) > 2}
    brands -= generic

    def is_brand(part: str) -> bool:
        p = f" {part.lower().strip()} "
        if len(p) > 42:
            return False
        for b in brands:
            i = p.find(b)
            if i > -1 and not p[i - 1].isalnum() and not p[i + len(b)].isalnum():
                return True
        return False

    for _ in range(3):
        tail = re.match(r"^(.*\S)\s+[|–—\-:]\s+(\S.*)$", s)
        if tail and len(tail.group(1)) >= 8 and is_brand(tail.group(2)):
            s = tail.group(1)
            continue
        head = re.match(r"^(\S[^|–—:]{1,40}?)\s*[|–—:]\s+(\S.*)$", s)
        if head and len(head.group(2)) >= 8 and is_brand(head.group(1)):
            s = head.group(2)
            continue
        break
    return s if len(s) <= 200 else s[:199].rstrip() + "…"


_JUNK_IMAGE = re.compile(r"sprite|logo|icon|favicon|placeholder|blank\.|spacer|avatar|badge|flag|loading|pixel|1x1|"
                         r"transparent|\.svg(\?|$)|\.gif(\?|$)", re.I)


def normalize_image(src, base: str) -> Optional[str]:
    """Absolute https address of the largest version of a product photo, or None."""
    raw = html_lib.unescape(str(src or "")).strip()
    if not raw or re.match(r"(?i)(data|blob|javascript):", raw):
        return None
    try:
        parts = urlsplit(urljoin(base, raw))
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    host, path, query = parts.hostname or "", parts.path, parts.query
    if re.search(r"alicdn\.com$|aliexpress-media\.com$", host):
        path = re.sub(r"(?i)(\.(?:jpe?g|png|webp))_.+$", r"\1", path)        # foo.jpg_220x220.jpg_.webp
    elif re.search(r"cdn\.shopify\.com$", host) or "/cdn/shop/" in path:
        path = re.sub(r"(?i)_(?:\d+x\d*|\d*x\d+|pico|icon|thumb|small|compact|medium|large|grande)"
                      r"(?:_crop_[a-z]+)?(?:@\dx)?(?=\.(?:jpe?g|png|webp)$)", "", path)
        query = urlencode([(k, v) for k, v in parse_qsl(query, keep_blank_values=True)
                           if k not in ("width", "height", "crop")])
    elif re.search(r"media-amazon\.com$|ssl-images-amazon\.com$", host):
        path = re.sub(r"(?i)\._[A-Za-z0-9_,%-]+_(?=\.(?:jpe?g|png|webp)$)", "", path)  # image._AC_SX342_.jpg
    elif re.search(r"ebayimg\.com$", host):
        path = re.sub(r"(?i)s-l\d+(?=\.(?:jpe?g|png|webp)$)", "s-l1600", path)
    elif re.search(r"dsmcdn\.com$", host):
        path = re.sub(r"/mnresize/\d+/\d+/", "/", path)
    return urlunsplit(("https", parts.netloc, path, query, ""))


def unique_images(urls, base: str, limit: int = 10) -> list:
    seen, out = set(), []
    for src in urls or []:
        url = normalize_image(src, base)
        if not url:
            continue
        key = url.split("?", 1)[0].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(url)
        if len(out) >= limit:
            break
    return out


# ══ HTML reading ═════════════════════════════════════════════════════════════

_ATTR_RE = re.compile(r"""([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?""")


def _attrs(source: str) -> dict:
    out = {}
    for m in _ATTR_RE.finditer(source or ""):
        key = m.group(1).lower()
        if key not in out:
            value = m.group(2) if m.group(2) is not None else m.group(3) if m.group(3) is not None else m.group(4) or ""
            out[key] = html_lib.unescape(value)
    return out


def _tags(page: str, name: str, limit: int = 600) -> list:
    out = []
    for m in re.finditer(rf"<{name}\b([^>]*)>", page, re.I):
        out.append(_attrs(m.group(1)))
        if len(out) >= limit:
            break
    return out


def _first(page: str, pattern: str, flags=0) -> Optional[str]:
    m = re.search(pattern, page, flags)
    return m.group(1) if m else None


def _json_loose(text):
    """json.loads that survives the sloppy JSON often found in JSON-LD blocks."""
    t = re.sub(r"^<!--|-->$", "", str(text or "").strip()).strip()
    if not t:
        return None
    for candidate in (t, re.sub(r",\s*([}\]])", r"\1", re.sub(r"[\x00-\x1f]+", " ", t))):
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


def _unquote_json(body: str) -> str:
    try:
        return json.loads(f'"{body}"')
    except ValueError:
        return body


class _Meta:
    def __init__(self, page: str):
        self.map = {}
        for a in _tags(page, "meta", 800):
            key = str(a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            value = (a.get("content") or "").strip()
            if key and value:
                self.map.setdefault(key, []).append(value)

    def first(self, *keys):
        return next((self.map[k][0] for k in keys if self.map.get(k)), None)

    def all(self, *keys):
        return [v for k in keys for v in self.map.get(k, [])]


def _from_meta(meta: _Meta) -> dict:
    currency = normalize_currency(meta.first("product:price:currency", "og:price:currency", "pricecurrency"))
    price_raw = meta.first("product:price:amount", "og:price:amount", "product:sale_price:amount", "price")
    if not price_raw and re.search("price", meta.first("twitter:label1") or "", re.I):
        price_raw = meta.first("twitter:data1")
    price = parse_money(f"{price_raw} {currency or ''}", currency) if price_raw else None
    og_type = meta.first("og:type") or ""
    return {
        "name": "meta",
        "title": meta.first("og:title", "twitter:title"),
        "description": meta.first("og:description", "description", "twitter:description"),
        "images": meta.all("og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src"),
        "price": price,
        "brand": meta.first("product:brand", "og:brand"),
        # A price in the meta tags, or an explicit product type, marks a product
        # page. "product.group" is how shops label a category page.
        "structured": bool(price) or bool(re.match(r"(?i)^(og:)?product(\.item)?$", og_type)),
        "listing": "product.group" in og_type.lower(),
    }


def _types(node) -> list:
    raw = node.get("@type") if isinstance(node, dict) else None
    values = raw if isinstance(raw, list) else [raw] if raw else []
    return [re.sub(r"^https?://schema\.org/", "", str(v).lower()) for v in values]


def _walk(node, depth: int = 0):
    if not node or depth > 6:
        return
    if isinstance(node, list):
        for item in node:
            yield from _walk(item, depth + 1)
        return
    if not isinstance(node, dict):
        return
    yield node
    for key in ("@graph", "mainEntity", "mainEntityOfPage"):
        if node.get(key):
            yield from _walk(node[key], depth + 1)


def _image_list(value) -> list:
    out = []

    def visit(v):
        if not v:
            return
        if isinstance(v, list):
            for item in v:
                visit(item)
        elif isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            visit(v.get("contentUrl") or v.get("url") or v.get("@id"))

    visit(value)
    return out


def _offer_price(offers) -> Optional[dict]:
    found = []

    def visit(o):
        if not o:
            return
        if isinstance(o, list):
            for item in o:
                visit(item)
            return
        if not isinstance(o, dict):
            return
        specs = o.get("priceSpecification") or []
        specs = [s for s in (specs if isinstance(specs, list) else [specs]) if isinstance(s, dict)]
        currency = normalize_currency(o.get("priceCurrency") or next((s.get("priceCurrency") for s in specs if s.get("priceCurrency")), None))
        if "aggregateoffer" in _types(o):
            low = parse_number(o.get("lowPrice", o.get("price")), currency)
            high = parse_number(o.get("highPrice"), currency)
            if low and low > 0:
                found.append({"amount": low, "max": high if high and high > low else None, "currency": currency})
            else:
                visit(o.get("offers"))
            return
        amount = parse_number(o.get("price"), currency)
        if amount is None:
            for spec in specs:
                amount = parse_number(spec.get("price", spec.get("minPrice")), currency)
                if amount is not None:
                    break
        if amount and amount > 0:
            found.append({"amount": amount, "max": None, "currency": currency})

    visit(offers)
    if not found:
        return None
    low = min(found, key=lambda f: f["amount"])
    high = max((f["max"] or f["amount"]) for f in found)
    return {"amount": low["amount"],
            "currency": low["currency"] or next((f["currency"] for f in found if f["currency"]), None),
            "max": high if high > low["amount"] else None}


def _from_jsonld(page: str) -> Optional[dict]:
    product = group = None
    for m in re.finditer(r"(?is)<script\b([^>]*)>(.*?)</script\s*>", page):
        if "ld+json" not in (_attrs(m.group(1)).get("type") or "").lower():
            continue
        for node in _walk(_json_loose(m.group(2))):
            types = _types(node)
            if not product and "product" in types and node.get("name"):
                product = node
            if not group and "productgroup" in types and node.get("name"):
                group = node
        if product:
            break
    if not product and group:
        variants = group.get("hasVariant") or []
        variants = [v for v in (variants if isinstance(variants, list) else [variants]) if isinstance(v, dict)]
        first = variants[0] if variants else {}
        product = {**first, "name": group["name"],
                   "description": group.get("description") or first.get("description"),
                   "brand": group.get("brand") or first.get("brand"),
                   "image": group.get("image") if _image_list(group.get("image")) else first.get("image"),
                   "offers": [v.get("offers") for v in variants if v.get("offers")],
                   "aggregateRating": group.get("aggregateRating") or first.get("aggregateRating")}
    if not product:
        return None
    rating = product.get("aggregateRating") if isinstance(product.get("aggregateRating"), dict) else {}
    brand = product.get("brand")
    return {
        "name": "jsonld",
        "title": str(product["name"]),
        "description": product.get("description") if isinstance(product.get("description"), str) else None,
        "images": _image_list(product.get("image")),
        "price": _offer_price(product.get("offers")),
        "brand": brand if isinstance(brand, str) else (brand or {}).get("name") if isinstance(brand, dict) else None,
        "rating": parse_number(rating.get("ratingValue")),
        "structured": True,
    }


def _aliexpress(page: str) -> Optional[dict]:
    out = {"name": "aliexpress", "images": []}
    images = _first(page, r'"imagePathList"\s*:\s*(\[[^\]]*\])')
    if images:
        out["images"] = [x for x in (_json_loose(images) or []) if isinstance(x, str)]
    subject = _first(page, r'"subject"\s*:\s*"((?:[^"\\]|\\.)*)"')
    if subject:
        out["title"] = _unquote_json(subject)
    formatted = (_first(page, r'"formatedActivityPrice"\s*:\s*"((?:[^"\\]|\\.)*)"')
                 or _first(page, r'"formatedPrice"\s*:\s*"((?:[^"\\]|\\.)*)"'))
    if formatted:
        out["price"] = parse_money(_unquote_json(formatted))
    if not out.get("price"):
        data = _json_loose(_first(page, r'"(?:minActivityAmount|minAmount)"\s*:\s*(\{[^}]*\})') or "")
        if isinstance(data, dict) and parse_number(data.get("value")):
            out["price"] = {"amount": parse_number(data["value"]), "currency": normalize_currency(data.get("currency"))}
    out["rating"] = parse_number(_first(page, r'"evarageStar"\s*:\s*"?([\d.]+)'))
    out["structured"] = bool(out.get("title") and (out["images"] or out.get("price")))
    return out if out.get("title") or out["images"] or out.get("price") else None


def _amazon(page: str) -> Optional[dict]:
    out = {"name": "amazon", "images": []}
    title = _first(page, r"""(?is)<span[^>]+id=["']productTitle["'][^>]*>(.*?)</span>""")
    if title:
        out["title"] = strip_tags(title)
    hi_res = re.findall(r'"hiRes"\s*:\s*"(https:[^"]+)"', page)
    out["images"] = hi_res or re.findall(r'"large"\s*:\s*"(https:[^"]+)"', page)
    if not out["images"]:
        landing = re.search(r"""(?i)<img[^>]+id=["']landingImage["'][^>]*>""", page)
        if landing:
            a = _attrs(landing.group(0))
            if a.get("data-old-hires") or a.get("src"):
                out["images"] = [a.get("data-old-hires") or a.get("src")]
    core_at = re.search(r"""(?i)id=["']corePrice""", page)
    core = page[core_at.start():] if core_at else page
    offscreen = _first(core, r"""(?i)class=["'][^"']*a-offscreen[^"']*["'][^>]*>([^<]+)<""")
    if offscreen:
        out["price"] = parse_money(offscreen)
    out["rating"] = parse_number(_first(page, r"([\d.]+) out of 5 stars"))
    out["structured"] = bool(out.get("title") and out["images"])
    return out if out.get("title") or out["images"] else None


async def _shopify(page: str, url: str, fetcher) -> Optional[dict]:
    parts = urlsplit(url)
    handle = _first(parts.path, r"/products/([^/?#]+)")
    if not handle or not fetcher or not re.search(
            r"cdn\.shopify\.com|/cdn/shop/|Shopify\.(theme|shop|currency)|shopify-digital-wallet", page, re.I):
        return None
    try:
        data = _json_loose(await fetcher(f"{parts.scheme}://{parts.netloc}/products/{handle}.js"))
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("title"):
        return None
    currency = normalize_currency(_first(page, r'Shopify\.currency\s*=\s*\{[^}]*"active"\s*:\s*"([A-Z]{3})"')
                                  or _first(page, r'"currency"\s*:\s*"([A-Z]{3})"'))
    cents = parse_number(data.get("price_min", data.get("price"))) or 0
    top = parse_number(data.get("price_max")) or 0
    images = [x for x in (data.get("images") or []) if isinstance(x, str)]
    if isinstance(data.get("featured_image"), str):
        images.append(data["featured_image"])
    return {
        "name": "shopify",
        "title": data["title"],
        "description": data.get("description"),
        "images": images,
        "price": {"amount": cents / 100, "currency": currency, "max": top / 100 if top > cents else None} if cents > 0 else None,
        "brand": data.get("vendor"),
        "structured": True,
    }


_OLD_PRICE = re.compile(r"old|was|strike|compare|original|regular|list-?price|before|crossed|\bdel\b|rrp|msrp|saving|"
                        r"discount-?(amount|percent)", re.I)
_PRICE_ELEMENT = re.compile(r"""(?is)<([a-z][a-z0-9]*)\b([^>]*\b(?:class|id|data-testid|itemprop)\s*=\s*["'][^"']*price[^"']*["'][^>]*)>(.{0,400}?)</\1>""")


def _price_from_elements(page: str, fallback_currency: Optional[str]) -> tuple:
    candidates = []
    for m in _PRICE_ELEMENT.finditer(page):
        if len(candidates) >= 40:
            break
        a = _attrs(m.group(2))
        if _OLD_PRICE.search(f"{a.get('class', '')} {a.get('id', '')} {a.get('data-testid', '')}"):
            continue
        text = re.sub(r"\s+", " ", strip_tags(m.group(3)))
        if not text or len(text) > 40:
            continue
        money = parse_money(a.get("content") or text, fallback_currency)
        if money:
            candidates.append((int(parse_number(a.get("data-fs")) or 0), money))
    if not candidates:
        return None, 0
    # The page's main price is normally the largest one on screen.
    best = max(candidates, key=lambda c: c[0])
    return best[1], len({c[1]["amount"] for c in candidates})


def _largest_from_srcset(srcset: Optional[str]) -> Optional[str]:
    best, best_width = None, -1.0
    for part in (srcset or "").split(","):
        bits = part.strip().split()
        if not bits:
            continue
        width = parse_number(bits[1]) if len(bits) > 1 else 0
        if (width or 0) > best_width:
            best, best_width = bits[0], width or 0
    return best


def _images_from_tags(page: str, trusted: bool) -> list:
    found = []
    for a in _tags(page, "img", 600):
        src = (a.get("data-zoom-image") or a.get("data-large_image") or a.get("data-large-image") or a.get("data-src")
               or a.get("data-original") or a.get("data-lazy-src")
               or _largest_from_srcset(a.get("srcset") or a.get("data-srcset")) or a.get("src"))
        if not src:
            continue
        width, height = int(parse_number(a.get("width")) or 0), int(parse_number(a.get("height")) or 0)
        if not trusted:
            if _JUNK_IMAGE.search(src) or (width and width < 200) or (height and height < 200):
                continue
        found.append((width * height, src))
    return [src for _, src in sorted(found, key=lambda f: -f[0])]


def _from_page(page: str, url: str, snapshot: bool) -> dict:
    h1 = _first(page, r"(?is)<h1\b[^>]*>(.*?)</h1>")
    title_tag = _first(page, r"(?is)<title\b[^>]*>(.*?)</title>")
    price, distinct = _price_from_elements(page, currency_from_host(urlsplit(url).hostname or ""))
    return {
        "name": "page",
        "title": (strip_tags(h1) if h1 else "") or (strip_tags(title_tag) if title_tag else "") or None,
        "images": _images_from_tags(page, snapshot),
        "price": price,
        # Many different prices on one page means a category or search page.
        "listing": distinct > 4,
    }


async def extract_product(page: str, page_url: str, fetcher=None, snapshot: bool = False) -> Optional[dict]:
    """Page HTML (or the browser button's snapshot) -> product dict, or None when
    the page holds no recognisable single product."""
    parts = urlsplit(page_url)
    host = (parts.hostname or "").lower()
    meta = _Meta(page)
    sources = []
    if re.search(r"(^|\.)aliexpress\.(com|us|ru)$", host):
        sources.append(_aliexpress(page))
    elif re.search(r"(^|\.)amazon\.[a-z.]+$", host):
        sources.append(_amazon(page))
    sources.append(await _shopify(page, page_url, fetcher))
    sources.append(_from_jsonld(page))
    sources.append(_from_meta(meta))
    sources.append(_from_page(page, page_url, snapshot))
    sources = [s for s in sources if s]
    used = []

    def pick(field, valid=lambda v: v not in (None, "")):
        for s in sources:
            if valid(s.get(field)):
                if s["name"] not in used:
                    used.append(s["name"])
                return s[field]
        return None

    title = clean_title(pick("title", lambda v: isinstance(v, str) and len(v.strip()) > 1),
                        meta.first("og:site_name"), host)
    price = pick("price", lambda p: bool(p) and p.get("amount", 0) > 0)
    if price and not price.get("currency"):
        other = next((s["price"]["currency"] for s in sources if s.get("price") and s["price"].get("currency")), None)
        price = {**price, "currency": other or currency_from_host(host)}

    structured_images = [img for s in sources if s["name"] != "page" for img in (s.get("images") or [])]
    page_images = next((s.get("images") or [] for s in sources if s["name"] == "page"), [])
    images = unique_images(structured_images, page_url)
    if snapshot or len(images) < 2:
        images = unique_images(structured_images + page_images[: 12 if snapshot else 6], page_url)
    if structured_images:
        used.extend(s["name"] for s in sources if s["name"] != "page" and s.get("images") and s["name"] not in used)
    elif images and "page" not in used:
        used.append("page")

    if not title or (not images and not price):
        return None
    # Without structured product data, a page read by link must look like a
    # single product: one headline, one price, a photo. The browser button is
    # trusted more, because the merchant pressed it on the product itself.
    structured = any(s.get("structured") for s in sources)
    if not structured and not snapshot:
        if not price or not images or any(s.get("listing") for s in sources):
            return None

    missing = []
    if not price:
        missing.append("price")
    elif not price.get("currency"):
        missing.append("currency")
    if not images:
        missing.append("images")
    return {
        "title": title,
        "description": clean_text(pick("description", lambda v: isinstance(v, str) and v.strip()) or "", 2000),
        "images": images,
        "cost": {"amount": price["amount"], "currency": price.get("currency"), "max": price.get("max")} if price else None,
        "brand": pick("brand"),
        "rating": pick("rating", lambda v: isinstance(v, (int, float)) and v > 0),
        "site": site_label(host),
        "source_url": page_url,
        "method": "+".join(used),
        "missing": missing,
    }


_BLOCK_SIGNS = re.compile(r"captcha|are you a (robot|human)|robot check|access denied|unusual traffic|"
                          r"verify (that )?you are (a )?human|px-captcha|cf-chl|just a moment|punish|slide to verify|"
                          r"request blocked|pardon our interruption|bot detection", re.I)


def looks_blocked(status: int, page: str) -> bool:
    """True when a page that yielded no product looks like an anti-bot wall."""
    return status in (401, 403, 407, 429, 503) or bool(_BLOCK_SIGNS.search(page[:60000]))


# ══ Fetching ═════════════════════════════════════════════════════════════════

class FetchError(Exception):
    """code: 'unsafe' | 'timeout' | 'network' | 'too_many_redirects'"""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/142.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ka;q=0.8",
}


async def _check_url(url: str, allow_private: bool) -> str:
    """The address comes from a user, so every hop is checked: web links only,
    and never this server's own network (localhost, private ranges, metadata)."""
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise FetchError("unsafe", "Not a valid address")
    if parts.scheme not in ("http", "https") or not host:
        raise FetchError("unsafe", "Only web links are allowed")
    if parts.username or parts.password:
        raise FetchError("unsafe", "Links with a login are not allowed")
    if allow_private:
        return url
    if port not in (None, 80, 443):
        raise FetchError("unsafe", "Links with a custom port are not allowed")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        if "." not in host or re.search(r"\.(localhost|local|internal|lan|home|corp)$", host):
            raise FetchError("unsafe", "Private addresses are not allowed")
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None)
        except OSError:
            raise FetchError("network", "The site could not be found")
        addresses = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    if not addresses or not all(a.is_global for a in addresses):
        raise FetchError("unsafe", "Private addresses are not allowed")
    return url


def _decode(body: bytes, content_type: str) -> str:
    charset = _first(content_type or "", r"""(?i)charset\s*=\s*["']?([\w-]+)""")
    if not charset:
        charset = _first(body[:4096].decode("latin-1"), r"""(?i)<meta[^>]+charset\s*=\s*["']?([\w-]+)""")
    try:
        return body.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


async def fetch_page(url: str, *, timeout: float = 15, max_bytes: int = 5_000_000, max_redirects: int = 6,
                     allow_private: bool = False, accept: Optional[str] = None,
                     transport: Optional[httpx.AsyncBaseTransport] = None) -> dict:
    """GET a public web page. Returns {status, final_url, html}."""
    headers = dict(_HEADERS)
    if accept:
        headers["Accept"] = accept
    current = await _check_url(url, allow_private)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, transport=transport) as client:
            for _ in range(max_redirects + 1):
                async with client.stream("GET", current, headers=headers) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                        current = await _check_url(urljoin(current, resp.headers["location"]), allow_private)
                        continue
                    chunks, size = [], 0
                    async for chunk in resp.aiter_bytes():
                        chunks.append(chunk)
                        size += len(chunk)
                        if size >= max_bytes:
                            break
                    page = _decode(b"".join(chunks)[:max_bytes], resp.headers.get("content-type", ""))
                    status = resp.status_code
                refresh = None
                if len(page) < 20000:
                    tag = re.search(r"""(?i)<meta[^>]+http-equiv\s*=\s*["']?refresh["']?[^>]*>""", page)
                    refresh = _first(tag.group(0), r"""(?i)content\s*=\s*["']?\s*\d+\s*;\s*url\s*=\s*['"]?([^'">\s]+)""") if tag else None
                if refresh:
                    current = await _check_url(urljoin(current, html_lib.unescape(refresh)), allow_private)
                    continue
                return {"status": status, "final_url": current, "html": page}
    except httpx.TimeoutException:
        raise FetchError("timeout", "The page took too long")
    except httpx.HTTPError as exc:
        raise FetchError("network", str(exc) or type(exc).__name__)
    raise FetchError("too_many_redirects", "The link redirects too many times")


# ══ Pasted text → product ════════════════════════════════════════════════════

def extract_url(text) -> Optional[str]:
    """Finds the link inside whatever was pasted or shared."""
    s = str(text or "")
    m = re.search(r"""https?://[^\s<>"'`]+""", s, re.I)
    raw = m.group(0) if m else None
    if not raw:
        bare = re.search(r"""(?:^|\s)((?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>"'`]*)?)""", s, re.I)
        raw = f"https://{bare.group(1)}" if bare else None
    if not raw:
        return None
    raw = re.sub(r"""[)\].,;!?»”"']+$""", "", raw)
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    return raw if parts.hostname and "." in parts.hostname else None


_LEAD_IN = re.compile(r"^(i just found this on|look what i found on|check out this|check this out|found this on|"
                      r"shared from|i found this amazing item on)\b[^:|]*[:|]?\s*", re.I)


def parse_share_text(text) -> dict:
    """Shopping apps share text like 'I just found this on AliExpress: US $4.56 |
    Ceramic vase … https://…'. Returns the name and price found in it."""
    body = re.sub(r"https?://\S+", " ", str(text or ""), flags=re.I).strip()
    if not body:
        return {"title": None, "price": None}
    price, titles = None, []
    for part in re.split(r"[|\n]+", body):
        part = _LEAD_IN.sub("", part.strip()).strip()
        if not part:
            continue
        money = parse_money(part) if len(part) <= 24 else None
        if money and money.get("currency") and not price:
            price = money
        else:
            titles.append(part)
    if not price:
        inline = re.search(r"(?:US ?\$|[$€£₾₺₽])\s?\d[\d.,]*|\d[\d.,]*\s?(?:₾|ლარი|USD|EUR|GEL|TL)", body, re.I)
        price = parse_money(inline.group(0)) if inline else None
    title = max(titles, key=len) if titles else ""
    return {"title": title[:200] if len(title) >= 8 else None,
            "price": {"amount": price["amount"], "currency": price["currency"], "max": None}
            if price and price.get("currency") else None}


async def import_from_text(text, *, allow_private: bool = False, transport=None) -> dict:
    """Pasted text -> {'ok': True, 'product': {...}} or
    {'ok': False, 'reason': 'no_url'|'unsafe'|'fetch_failed'|'blocked'|'not_product', 'url'?, 'shared'?}"""
    url = extract_url(text)
    if not url:
        return {"ok": False, "reason": "no_url"}
    shared = parse_share_text(text)
    options = {"allow_private": allow_private, "transport": transport}
    try:
        page = await fetch_page(url, **options)
    except FetchError as exc:
        return {"ok": False, "reason": "unsafe" if exc.code == "unsafe" else "fetch_failed", "url": url, "shared": shared}

    async def fetcher(target: str) -> str:
        return (await fetch_page(target, timeout=8, accept="application/json,*/*;q=0.8", **options))["html"]

    # Error pages are never read as products, whatever they contain.
    product = await extract_product(page["html"], page["final_url"], fetcher) if page["status"] < 400 else None
    if not product:
        reason = ("blocked" if looks_blocked(page["status"], page["html"])
                  else "fetch_failed" if page["status"] >= 500 else "not_product")
        return {"ok": False, "reason": reason, "url": page["final_url"], "shared": shared,
                "site": site_label(urlsplit(page["final_url"]).hostname or "")}
    if not product["cost"] and shared["price"]:
        product["cost"] = shared["price"]
        product["missing"] = [m for m in product["missing"] if m != "price"]
    return {"ok": True, "product": product}


async def import_from_snapshot(page: str, page_url: str, *, allow_private: bool = False, transport=None) -> Optional[dict]:
    """Product from the snapshot sent by the 'Add to DropOS' browser button."""
    async def fetcher(target: str) -> str:
        return (await fetch_page(target, timeout=8, accept="application/json,*/*;q=0.8",
                                 allow_private=allow_private, transport=transport))["html"]
    return await extract_product(page, page_url, fetcher, snapshot=True)


# ══ Into the DropOS pipeline ═════════════════════════════════════════════════

def source_id_for(url: str) -> str:
    """Stable id for a product page, so pasting the same link twice adds it once."""
    parts = urlsplit(url)
    tracking = re.compile(r"^(utm_|spm|scm|aff_|gclid|fbclid|ref_?$|srsltid|pvid|algo_)", re.I)
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not tracking.match(k)))
    host = re.sub(r"^www\.", "", (parts.hostname or "").lower())
    canonical = urlunsplit(("https", host, parts.path.rstrip("/"), query, ""))
    return "link_" + hashlib.sha1(canonical.encode()).hexdigest()[:20]


def to_dropos_product(product: dict, settings: dict, rates: dict, brand_id=None) -> dict:
    """Shapes an imported product like a scraped one, so the rest of DropOS
    (AI caption, review queue, posting) treats it the same way."""
    from filter_engine import pretty_price   # deferred: keeps this module importable on its own
    import fx

    def number(key: str, default: float) -> float:
        # A setting can be present but empty (None) when it was never saved.
        try:
            return float(settings.get(key) or default)
        except (TypeError, ValueError):
            return default

    cost = product.get("cost") or {}
    exchange_rate = number("exchange_rate", 0.353)                      # CNY -> GEL, the store's own setting
    if cost.get("currency") == "CNY":
        cost_gel = round(float(cost["amount"]) * exchange_rate, 2)
    else:
        cost_gel = fx.to_gel(cost.get("amount"), cost.get("currency"), rates) or 0.0
    title = product.get("title") or ""
    if cost_gel > 0:
        is_tech = any(word in title.lower() for word in ("camera", "ccd", "electronics"))
        markup = (number("sell_markup_low", 3.5) if cost_gel < 10
                  else number("sell_markup_high", 2.2) if is_tech
                  else number("sell_markup_mid", 2.8))
        sell = pretty_price(cost_gel * markup)
        margin = round((sell - cost_gel) / sell * 100, 1) if sell else 0.0
    else:
        sell, margin = 0.0, 0.0
    return {
        "source": "link",
        "source_platform": product.get("site") or "link",
        "source_id": source_id_for(product.get("source_url") or title),
        "title": title,
        "title_translated": title,
        "product_name": "",
        "price_cny": round(cost_gel / exchange_rate, 2) if exchange_rate > 0 else 0.0,
        "cost_eur": cost_gel,              # legacy column name; the value is ₾
        "sell_price_eur": sell,
        "margin_pct": margin,
        "orders": 0,
        "rating": float(product.get("rating") or 0),
        "images": (product.get("images") or [])[:10],
        "url": product.get("source_url") or "",
        "category": "",
        "keyword": "link import",
        "description": (product.get("description") or "")[:1500],
        "merchant": product.get("site") or "",
        "brand_id": brand_id,
        "stage": "SCRAPED",
    }


# ══ The browser button ═══════════════════════════════════════════════════════
# This JavaScript is what the bookmark runs. It is self-contained ES5: it reads
# the page the merchant has open (meta tags, JSON-LD, headline, visible prices,
# large photos) and posts that snapshot to DropOS in a new tab.

CLIP_SOURCE = r"""function clip(BASE, TOKEN) {
  var d = document;
  var all = function (selector) {
    try { return [].slice.call(d.querySelectorAll(selector)); } catch (e) { return []; }
  };
  var esc = function (value) {
    return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  };
  var html = '<title>' + esc(d.title) + '</title>';
  all('meta').slice(0, 300).forEach(function (m) { html += m.outerHTML; });
  all('script[type="application/ld+json"]').forEach(function (s) {
    html += '<script type="application/ld+json">' + s.textContent.replace(/<\//g, '<\\/') + '<' + '/script>';
  });
  var h1 = all('h1')[0];
  if (h1) html += '<h1>' + esc(h1.innerText) + '</h1>';
  all('[class*="price" i],[id*="price" i],[data-testid*="price" i],[itemprop="price"]')
    .filter(function (n) {
      var text = (n.innerText || '').trim();
      return text && text.length < 41 && /\d/.test(text) && n.offsetParent;
    })
    .slice(0, 16)
    .forEach(function (n) {
      var style = getComputedStyle(n);
      var name = typeof n.className === 'string' ? n.className : '';
      var struck = String(style.textDecorationLine || style.textDecoration).indexOf('line-through') > -1;
      html += '<span class="price ' + esc(name) + (struck ? ' strike' : '') + '" data-fs="' + (parseInt(style.fontSize, 10) || 0) + '">' + esc(n.innerText.trim()) + '</span>';
    });
  all('img')
    .map(function (i) { return { src: i.currentSrc || i.src, w: i.naturalWidth, h: i.naturalHeight }; })
    .filter(function (i) { return i.src && i.src.indexOf('http') === 0 && i.w >= 300 && i.h >= 300; })
    .sort(function (a, b) { return b.w * b.h - a.w * a.h; })
    .slice(0, 12)
    .forEach(function (i) { html += '<img src="' + esc(i.src) + '" width="' + i.w + '" height="' + i.h + '">'; });
  var form = d.createElement('form');
  form.method = 'POST';
  form.action = BASE + '/api/import/clip';
  form.target = '_blank';
  form.acceptCharset = 'UTF-8';
  [['token', TOKEN], ['url', location.href], ['html', html.slice(0, 400000)]].forEach(function (pair) {
    var input = d.createElement('input');
    input.type = 'hidden';
    input.name = pair[0];
    input.value = pair[1];
    form.appendChild(input);
  });
  d.body.appendChild(form);
  form.submit();
  form.remove();
}"""


def bookmarklet_href(base_url: str, token: str) -> str:
    """The javascript: link for this installation. Dragging it to the bookmarks bar installs the button."""
    from urllib.parse import quote
    code = f"({CLIP_SOURCE})({json.dumps(base_url)},{json.dumps(token)})"
    return "javascript:" + quote(code, safe="")
