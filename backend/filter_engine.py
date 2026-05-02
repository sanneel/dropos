import hashlib
import logging

log = logging.getLogger(__name__)

_SPAM_FRAGMENTS = [
    "oem", "bulk order", "custom logo", "1000pcs",
    "minimum order", "custom print", "private label",
]


def basic_filter(products: list, settings: dict) -> list:
    out = []
    seen_titles: dict = {}   # title_hash → product index in out (for dedup upgrade)
    for p in products:
        if not p.get("title") or not p.get("price_cny"):
            continue

        platform = p.get("source_platform", "")

        # 1688: require at least 1 confirmed sale; rating data is unavailable so skip that check
        if platform == "1688":
            orders = int(p.get("orders") or 0)
            if orders <= 0:
                continue

        title_lower = (p.get("title_translated") or p.get("title", "")).lower()
        if any(frag in title_lower for frag in _SPAM_FRAGMENTS):
            continue
        if not p.get("images"):
            continue

        title_hash = hashlib.md5(title_lower[:40].encode()).hexdigest()
        if title_hash in seen_titles:
            # Keep whichever has more orders; if tied, keep lower price
            idx = seen_titles[title_hash]
            existing = out[idx]
            if (p.get("orders", 0) > existing.get("orders", 0) or
                    (p.get("orders", 0) == existing.get("orders", 0) and
                     p.get("price_cny", 999) < existing.get("price_cny", 999))):
                out[idx] = p
            continue

        seen_titles[title_hash] = len(out)
        out.append(p)

    # Sort 1688 by sold count descending so best sellers surface first
    out.sort(key=lambda p: p.get("orders", 0) if p.get("source_platform") == "1688" else 0, reverse=True)
    return out


def profit_filter(product: dict, settings: dict) -> bool:
    """Calculates cost/sell/margin and mutates product in-place. Returns True if margin passes."""
    price_cny = float(product.get("price_cny", 0))
    exchange_rate = float(settings.get("exchange_rate", 0.13))
    shipping_cny = 15.0

    cost_eur = (price_cny + shipping_cny) * exchange_rate

    if cost_eur < 5:
        markup = settings.get("sell_markup_low", 3.5)
    elif cost_eur < 15:
        markup = settings.get("sell_markup_mid", 2.8)
    else:
        markup = settings.get("sell_markup_high", 2.2)

    sell_price = cost_eur * markup
    margin = ((sell_price - cost_eur) / sell_price) * 100

    product["cost_eur"] = round(cost_eur, 2)
    product["sell_price_eur"] = round(sell_price, 2)
    product["margin_pct"] = round(margin, 1)

    return margin >= settings.get("min_margin", 60.0)


def dedup(products: list) -> list:
    """Deduplicates by first image URL hash."""
    seen: set = set()
    out = []
    for p in products:
        img = (p.get("images") or [""])[0]
        key = hashlib.md5(img.encode()).hexdigest() if img else None
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(p)
    return out
