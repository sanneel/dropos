"""
Rule-based product scorer (0-100).
Runs before AI enrichment to pre-filter obvious low-quality products and save API tokens.
HIGH (>=80) -> sent to AI enrichment
MEDIUM (50-79) -> sent to AI enrichment with lower priority
LOW (<50) -> dropped before AI
"""

from typing import Literal

ScoreLabel = Literal["LOW", "MEDIUM", "HIGH"]

# Categories that are a great fit for the couple gift shop
_GOOD_CATEGORIES = {
    "Jewelry", "Accessories", "Stationery", "Home Fragrance",
    "Phone Accessories", "Phone Cases", "Bags", "Watches",
}

# Categories clearly not a fit — penalize hard so they rarely reach AI
_BAD_CATEGORIES = {
    "Kitchen", "Baby", "Tools", "Automotive", "Sportswear",
    "Outdoor", "Pet Supplies", "Office", "Industrial", "Food",
}

# Title signals that suggest premium materials — reward these
_PREMIUM_SIGNALS = [
    "925 silver", "sterling silver", "18k", "14k gold", "gold plated",
    "gold-plated", "personalized", "personalised", "custom engraved",
    "engraved", "stainless steel", "zircon", "crystal", "gemstone",
    "titanium", "moissanite", "cubic zirconia",
]

# Title signals that suggest low-quality materials — penalize these
_CHEAP_SIGNALS = [
    "plastic bracelet", "rubber bracelet", "silicone bracelet",
    "acrylic jewelry", "acrylic jewellery", "resin bracelet",
    "resin necklace", "resin ring", "pvc keychain", "foam",
]


def compute_score(product: dict) -> int:
    points = 0

    # Demand: orders (0-40)
    # Taobao/CSSBuy does not expose sold count reliably. Treat unknown demand as
    # neutral so Taobao products are judged by rating, price, photos, and title.
    orders = int(product.get("orders", 0))
    source = product.get("source_platform", "")

    if source == "taobao":
        points += 20
    elif orders == 0:
        points += 10
    elif orders >= 10_000:
        points += 40
    elif orders >= 5_000:
        points += 32
    elif orders >= 2_000:
        points += 24
    elif orders >= 500:
        points += 16
    elif orders >= 100:
        points += 10
    elif orders >= 50:
        points += 6
    elif orders >= 20:
        points += 3

    # Quality: rating (0-20)
    rating = float(product.get("rating", 0))
    if rating >= 4.9:
        points += 20
    elif rating >= 4.7:
        points += 15
    elif rating >= 4.5:
        points += 10
    elif rating >= 4.0:
        points += 5

    # Price sweet spot 10-60 CNY (0-20)
    price = float(product.get("price_cny", 0))
    if 10 <= price <= 60:
        points += 20
    elif 5 <= price < 10:
        points += 12
    elif 60 < price <= 150:
        points += 10
    elif price > 0:
        points += 4

    # Images (0-10)
    imgs = len(product.get("images", []))
    if imgs >= 5:
        points += 10
    elif imgs >= 3:
        points += 7
    elif imgs >= 1:
        points += 3

    # Title richness (0-10)
    title = product.get("title_translated") or product.get("title", "")
    title_lower = title.lower()
    if len(title) >= 25:
        points += 10
    elif len(title) >= 12:
        points += 6
    elif len(title) >= 5:
        points += 2

    # ── Category fit bonus/penalty (-20 to +15) ────────────────────────────────
    # Rewards products in niche-relevant categories and penalises off-niche ones
    # before they waste AI tokens.
    category = product.get("category", "")
    if category in _GOOD_CATEGORIES:
        points += 15
    elif category in _BAD_CATEGORIES:
        points -= 20

    # ── Material quality signals (-15 to +10) ──────────────────────────────────
    # Cheap-material indicators flag products that would hurt premium brand image.
    # Premium-material indicators suggest the product genuinely looks high-end.
    if any(sig in title_lower for sig in _CHEAP_SIGNALS):
        points -= 15
    elif any(sig in title_lower for sig in _PREMIUM_SIGNALS):
        points += 10

    return min(100, max(0, points))


def get_label(score: int) -> ScoreLabel:
    if score >= 80:
        return "HIGH"
    if score >= 50:
        return "MEDIUM"
    return "LOW"


def score_product(product: dict) -> dict:
    """Adds raw_score and score_label to product dict in-place and returns it."""
    s = compute_score(product)
    product["raw_score"] = s
    product["score_label"] = get_label(s)
    return product
