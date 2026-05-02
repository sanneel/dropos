"""
AI enrichment layer.
Calls Anthropic claude-haiku with prompt caching when API key is configured.
Falls back to rule-based mock enrichment — same output schema, no API needed.
"""

import json
import logging
import random
import re
from typing import Optional

import httpx

log = logging.getLogger(__name__)

# ── Audience inference ─────────────────────────────────────────────────────────

_MALE_WORDS = {"men", "male", "boy", "beard", "shaving", "suit", "tie", "cufflink", "wallet"}
_FEMALE_WORDS = {"women", "female", "girl", "makeup", "lipstick", "handbag", "purse", "dress", "skirt", "blush", "mascara", "foundation"}
_KIDS_WORDS = {"baby", "kid", "child", "children", "toy", "toddler", "infant", "nursery"}


def infer_audience(product: dict) -> str:
    title = (product.get("title_translated") or product.get("title", "")).lower()
    if any(w in title for w in _KIDS_WORDS):   return "kids"
    if any(w in title for w in _FEMALE_WORDS): return "female"
    if any(w in title for w in _MALE_WORDS):   return "male"
    return "unisex"


# ── Tag generation ─────────────────────────────────────────────────────────────

_CATEGORY_TAGS: dict = {
    "Electronics":       ["tech", "gadget", "wireless", "smart", "innovation"],
    "Home Decor":        ["aesthetic", "cozy", "homedecor", "interior", "vibes"],
    "Home":              ["home", "cozy", "homelife", "aesthetic", "lifestyle"],
    "Stationery":        ["stationery", "journaling", "studygram", "bujo", "planner"],
    "Bags":              ["bag", "fashion", "ootd", "accessories", "style"],
    "Home Fragrance":    ["candle", "scent", "wellness", "selfcare", "cozy"],
    "Travel":            ["travel", "wanderlust", "packing", "adventure", "nomad"],
    "Phone Accessories": ["phonecase", "tech", "gadget", "accessories", "style"],
    "Phone Cases":       ["phonecase", "aesthetic", "accessories", "protection", "case"],
    "Accessories":       ["accessories", "style", "fashion", "ootd", "trending"],
}

_UNIVERSAL_TAGS = ["musthave", "shopnow", "findoftheday", "instashop", "trending", "viral", "gift", "aesthetic"]

_CAPTION_TEMPLATES = [
    "Elevate your everyday with this stunning piece. Designed for those who appreciate the finer details in life. ✨",
    "The aesthetic upgrade your space has been waiting for. Minimal design, maximum impact — you'll wonder how you lived without it. 🖤",
    "Where style meets function. This is the piece your feed (and your life) needs right now. Shop the link in bio. 💫",
    "Obsessed doesn't even cover it. Once you have it, you can't imagine life without it. Limited stock — grab yours now. ☁️",
    "Built for the aesthetic-conscious. Crafted for those who refuse to compromise on style or quality. 🌿",
    "The secret to a perfectly curated home? It's this. Shop before it sells out — trust us on this one. ✨",
    "That 'where did you get that?' piece. Effortlessly chic, endlessly versatile. New drop — shop now. 🔥",
]


def _get_tags(product: dict) -> list:
    category = product.get("category", "")
    base = _CATEGORY_TAGS.get(category, ["aesthetic", "lifestyle", "trending"])
    combined = list(dict.fromkeys(base + _UNIVERSAL_TAGS))
    return combined[:15]


def _clean_name(product: dict) -> str:
    title = product.get("title_translated") or product.get("title", "Product")
    return " ".join(title.split()[:5])


# ── Mock enrichment ────────────────────────────────────────────────────────────

def mock_enrich(product: dict) -> dict:
    """Rule-based enrichment — no API required, same schema as real AI output."""
    raw_score = product.get("raw_score", 50)
    # Boost score using margin quality — products with good margins are worth showing
    margin = float(product.get("margin_pct", 0))
    margin_bonus = min(15, max(0, (margin - 60) / 4))  # +0-15 pts above 60% margin
    adjusted = min(100, raw_score + margin_bonus)
    base = adjusted / 10
    ai_score = round(min(10.0, max(1.0, base + random.uniform(0.1, 0.5))), 1)

    return {
        "score": ai_score,
        "niche_fit": round(min(10.0, ai_score * random.uniform(0.85, 1.05)), 1),
        "visual_appeal": round(min(10.0, ai_score * random.uniform(0.80, 1.10)), 1),
        "trend_score": round(min(10.0, ai_score * random.uniform(0.75, 1.15)), 1),
        "competition_score": round(random.uniform(5.0, 8.5), 1),
        "product_name": _clean_name(product),
        "caption": random.choice(_CAPTION_TEMPLATES),
        "hashtags": _get_tags(product),
        "audience": infer_audience(product),
        "rejection_reason": "" if ai_score >= 7.0 else "Score below threshold for niche",
    }


# ── Real AI enrichment ─────────────────────────────────────────────────────────

_SYSTEM_PROMPT_TEMPLATE = (
    'You score products for an Instagram dropship store. Niche: "{niche}".\n'
    "Score 1-10 on: niche_fit, visual_appeal, trend_score, competition_score "
    "(10=blue ocean/low competition). overall score = weighted average. "
    "Return ONLY valid JSON, no markdown:\n"
    '{{"score":<1-10>,"niche_fit":<1-10>,"visual_appeal":<1-10>,'
    '"trend_score":<1-10>,"competition_score":<1-10>,'
    '"product_name":"<3-5 word English name, no brand>",'
    '"caption":"<2-3 sentence aspirational Instagram caption>",'
    '"hashtags":["tag1","tag2","tag3","tag4","tag5","tag6","tag7","tag8","tag9","tag10","tag11","tag12","tag13","tag14","tag15"],'
    '"audience":"male|female|unisex|kids",'
    '"rejection_reason":"<only if score < 7, else empty string>"}}'
)


async def ai_enrich(product: dict, settings: dict) -> Optional[dict]:
    """
    Enriches product with AI-generated scores, caption, hashtags, and audience.
    Falls back to mock_enrich when API key is missing or call fails.
    """
    api_key = settings.get("anthropic_key", "")
    if not api_key:
        return mock_enrich(product)

    niche = settings.get("niche", "aesthetic lifestyle products")
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(niche=niche)

    title = product.get("title_translated") or product.get("title", "Unknown")
    user_content = (
        f"Title: {title}\n"
        f"Category: {product.get('category', '?')}\n"
        f"Cost: €{product.get('cost_eur', '?')} → Sell: €{product.get('sell_price_eur', '?')} "
        f"({product.get('margin_pct', '?')}% margin)\n"
        f"Orders: {product.get('orders', 0)} | Rating: {product.get('rating', 0)}/5 | "
        f"Images: {len(product.get('images', []))}"
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "anthropic-beta": "prompt-caching-2024-07-31",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 400,
                    "system": [
                        {
                            "type": "text",
                            "text": system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    "messages": [{"role": "user", "content": user_content}],
                },
            )
        if resp.status_code != 200:
            log.warning("Anthropic API error %d — falling back to mock", resp.status_code)
            return mock_enrich(product)

        text = resp.json()["content"][0]["text"]
        text = re.sub(r"```json|```", "", text).strip()
        result = json.loads(text)

        if "audience" not in result:
            result["audience"] = infer_audience(product)

        return result

    except json.JSONDecodeError as e:
        log.warning("AI JSON parse error: %s — falling back to mock", e)
        return mock_enrich(product)
    except Exception as e:
        log.warning("AI enrichment exception: %s — falling back to mock", e)
        return mock_enrich(product)
