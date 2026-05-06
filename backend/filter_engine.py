import hashlib
import logging
import math

from config.runtime import get_config

log = logging.getLogger(__name__)


def pretty_price(value: float) -> float:
    """Fixes the logic gaps to ensure prices always scale upward."""
    if value <= 0: return 0.0
    if value < 20: return 29.90
    if value < 45: return 44.90
    if value < 65: return 64.90
    # For expensive items, round to the nearest .90
    return round(math.ceil(value) - 0.10, 2)

def profit_filter(product: dict, settings: dict) -> bool:
    price_cny = float(product.get("price_cny", 0))
    exchange_rate = float(get_config("EXCHANGE_RATE", settings.get("exchange_rate", 0.353)))
    
    # 1688 shipping is often cheaper than Taobao per item
    shipping_cny = 10.0 if product.get("source_platform") == "1688" else 15.0
    cost_eur = (price_cny + shipping_cny) * exchange_rate

    # Dynamic Markup based on product type
    is_tech = any(x in product.get("title", "").lower() for x in ["camera", "ccd", "electronics"])
    
    if cost_eur < 10:
        markup = float(get_config("SELL_MARKUP_LOW", settings.get("sell_markup_low", 3.5)))
    elif is_tech:
        markup = float(get_config("SELL_MARKUP_HIGH", settings.get("sell_markup_high", 2.2)))
    else:
        markup = float(get_config("SELL_MARKUP_MID", settings.get("sell_markup_mid", 2.8)))

    sell_price = pretty_price(cost_eur * markup)
    margin = ((sell_price - cost_eur) / sell_price) * 100

    base_min_margin = float(get_config("MIN_MARGIN", settings.get("min_margin", 60.0)))
    min_margin_req = 45.0 if cost_eur > 30 else base_min_margin

    product["cost_eur"] = round(cost_eur, 2)
    product["sell_price_eur"] = round(sell_price, 2)
    product["margin_pct"] = round(margin, 1)

    return margin >= min_margin_req

_SPAM_FRAGMENTS = [
    "oem", "bulk order", "custom logo", "1000pcs",
    "minimum order", "custom print", "private label",
    "wholesale", "factory", "supplier", "reseller",
    "100pcs", "50pcs", "per lot", "lot of",
]

# Material-level signals for products that look cheap and off-brand for a
# premium couple gift shop — caught here before scoring wastes AI tokens.
_CHEAP_MATERIAL_FRAGMENTS = [
    "plastic bracelet", "plastic necklace", "plastic ring",
    "rubber bracelet", "rubber keychain",
    "silicone bracelet", "silicone wristband",
    "acrylic keychain", "acrylic ring", "acrylic necklace",
    "resin bracelet", "resin necklace", "resin ring",
    "eva foam", "pvc keychain",
]

# Products below this CNY price are almost always low quality.
# ~€3–4 cost before shipping — genuinely premium items rarely cost less.
_MIN_PRICE_CNY = 8.0


def basic_filter(products: list, settings: dict) -> list:
    out = []
    seen_titles: dict = {}   # title_hash → product index in out

    for p in products:
        if not p.get("title") or not p.get("price_cny"):
            continue

        platform = p.get("source_platform", "")

        if platform == "1688":
            orders = int(p.get("orders") or 0)
            if orders < 5:
                continue

        title_lower = (p.get("title_translated") or p.get("title", "")).lower()
        if any(frag in title_lower for frag in _SPAM_FRAGMENTS):
            continue

        # Reject products that clearly use cheap materials — won't fit premium brand
        if any(frag in title_lower for frag in _CHEAP_MATERIAL_FRAGMENTS):
            continue

        # Price floor — very cheap items signal poor quality for premium positioning
        price_cny = float(p.get("price_cny", 0))
        if price_cny < _MIN_PRICE_CNY:
            continue

        # For taobao: apply minimum rating filter (1688 has no reliable rating)
        if platform != "1688":
            min_rating = float(get_config("MIN_RATING", settings.get("min_rating", 4.0)))
            rating = float(p.get("rating") or 0)
            if rating > 0 and rating < min_rating:
                continue

        if not p.get("images"):
            continue

        # ── Title dedup (works across all keywords since raw_all is combined) ──
        # Uses first 40 chars — catches same product appearing under multiple keywords
        title_hash = hashlib.md5(title_lower[:40].encode()).hexdigest()
        if title_hash in seen_titles:
            idx = seen_titles[title_hash]
            existing = out[idx]
            # Keep whichever has more orders; if tied keep lower price
            if (p.get("orders", 0) > existing.get("orders", 0) or
                    (p.get("orders", 0) == existing.get("orders", 0) and
                     p.get("price_cny", 999) < existing.get("price_cny", 999))):
                out[idx] = p
            continue

        seen_titles[title_hash] = len(out)
        out.append(p)

    # Sort 1688 by sold count descending so best sellers surface first
    out.sort(
        key=lambda p: p.get("orders", 0) if p.get("source_platform") == "1688" else 0,
        reverse=True,
    )
    return out




def dedup(products: list) -> list:
    """
    Second-pass dedup after profit_filter.
    Checks both image URL and source_id to catch duplicates that slipped
    through title dedup (e.g. same product, different keyword, slightly different title).
    """
    seen_images: set = set()
    seen_ids: set = set()
    out = []

    for p in products:
        # Dedup by source_id first (same product, different keyword run)
        sid = p.get("source_id", "")
        if sid and sid in seen_ids:
            continue
        if sid:
            seen_ids.add(sid)

        # Dedup by first image URL (catches same product from different sources)
        img = (p.get("images") or [""])[0]
        img_key = hashlib.md5(img.encode()).hexdigest() if img else None
        if img_key and img_key in seen_images:
            continue
        if img_key:
            seen_images.add(img_key)

        out.append(p)

    return out
