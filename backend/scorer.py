"""
Rule-based product scorer (0–100).
Runs before AI enrichment to pre-filter obvious low-quality products and save API tokens.
HIGH (≥80) → sent to AI enrichment
MEDIUM (50–79) → sent to AI enrichment with lower priority
LOW (<50) → dropped before AI
"""

from typing import Literal

ScoreLabel = Literal["LOW", "MEDIUM", "HIGH"]


def compute_score(product: dict) -> int:
    points = 0

    # Demand: orders (0–40); 0 means "unknown/not tracked" — treat as neutral
    orders = int(product.get("orders", 0))
    if orders == 0:       points += 20  # unknown — give neutral credit
    elif orders >= 10_000: points += 40
    elif orders >= 5_000:  points += 32
    elif orders >= 2_000:  points += 22
    elif orders >= 500:    points += 14
    else:                  points += 6

    # Quality: rating (0–20)
    rating = float(product.get("rating", 0))
    if rating >= 4.9:   points += 20
    elif rating >= 4.7: points += 15
    elif rating >= 4.5: points += 10
    elif rating >= 4.0: points += 5

    # Price sweet spot 10–60 CNY (0–20)
    price = float(product.get("price_cny", 0))
    if 10 <= price <= 60:   points += 20
    elif 5 <= price < 10:   points += 12
    elif 60 < price <= 150: points += 10
    elif price > 0:         points += 4

    # Images (0–10)
    imgs = len(product.get("images", []))
    if imgs >= 5:   points += 10
    elif imgs >= 3: points += 7
    elif imgs >= 1: points += 3

    # Title richness (0–10)
    title = product.get("title_translated") or product.get("title", "")
    if len(title) >= 25:   points += 10
    elif len(title) >= 12: points += 6
    elif len(title) >= 5:  points += 2

    return min(100, points)


def get_label(score: int) -> ScoreLabel:
    if score >= 80: return "HIGH"
    if score >= 50: return "MEDIUM"
    return "LOW"


def score_product(product: dict) -> dict:
    """Adds raw_score and score_label to product dict in-place and returns it."""
    s = compute_score(product)
    product["raw_score"] = s
    product["score_label"] = get_label(s)
    return product
