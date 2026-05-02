"""
AI enrichment layer.

Priority:
  1. Gemini 2.0 Flash  (gemini_key set) — cheapest, analyses real product images
  2. Claude Haiku 4.5  (anthropic_key set) — text-only scoring
  3. Mock rule-based   (no keys)           — deterministic, free
"""

import base64
import json
import logging
import random
import re
from typing import Optional

import httpx

log = logging.getLogger(__name__)

# ── Prompts ────────────────────────────────────────────────────────────────────

_GEMINI_SYSTEM = """\
You are a product analyst for an Instagram dropship store. Niche: "{niche}".
A product image is included — use it to assess visual quality and aesthetics.

Score each field from 1 to 10:
- niche_fit: how well the product fits the store niche
- visual_appeal: photo quality and aesthetic appeal (judge from the image)
- trend_score: how viral or trending this type of product is right now
- competition_score: 10 means very low competition (blue ocean), 1 means saturated market
- score: overall weighted average of the four scores above

Also provide:
- product_name: 3-5 word English name, no brand
- caption: 2-3 sentence aspirational Instagram caption
- hashtags: list of exactly 15 hashtag strings (no # symbol)
- audience: one of male, female, unisex, kids
- rejection_reason: short reason if score is below 7, otherwise empty string

Respond with a single JSON object and nothing else.\
"""

_ANTHROPIC_SYSTEM = """\
You are a product analyst for an Instagram dropship store. Niche: "{niche}".

Score each field from 1 to 10:
- niche_fit: how well the product fits the store niche
- visual_appeal: estimated photo aesthetic appeal
- trend_score: how viral or trending this type of product is right now
- competition_score: 10 means very low competition (blue ocean), 1 means saturated
- score: overall weighted average

Also provide:
- product_name: 3-5 word English name, no brand
- caption: 2-3 sentence aspirational Instagram caption
- hashtags: list of exactly 15 hashtag strings (no # symbol)
- audience: one of male, female, unisex, kids
- rejection_reason: short reason if score is below 7, otherwise empty string

Respond with a single JSON object and nothing else.\
"""


# ── Audience inference ─────────────────────────────────────────────────────────

_MALE_WORDS   = {"men","male","boy","beard","shaving","suit","tie","cufflink","wallet"}
_FEMALE_WORDS = {"women","female","girl","makeup","lipstick","handbag","purse","dress",
                 "skirt","blush","mascara","foundation"}
_KIDS_WORDS   = {"baby","kid","child","children","toy","toddler","infant","nursery"}


def infer_audience(product: dict) -> str:
    title = (product.get("title_translated") or product.get("title", "")).lower()
    if any(w in title for w in _KIDS_WORDS):   return "kids"
    if any(w in title for w in _FEMALE_WORDS): return "female"
    if any(w in title for w in _MALE_WORDS):   return "male"
    return "unisex"


# ── Tag generation ─────────────────────────────────────────────────────────────

_CATEGORY_TAGS: dict = {
    "Electronics":       ["tech","gadget","wireless","smart","innovation"],
    "Home Decor":        ["aesthetic","cozy","homedecor","interior","vibes"],
    "Home":              ["home","cozy","homelife","aesthetic","lifestyle"],
    "Stationery":        ["stationery","journaling","studygram","bujo","planner"],
    "Bags":              ["bag","fashion","ootd","accessories","style"],
    "Home Fragrance":    ["candle","scent","wellness","selfcare","cozy"],
    "Travel":            ["travel","wanderlust","packing","adventure","nomad"],
    "Phone Accessories": ["phonecase","tech","gadget","accessories","style"],
    "Phone Cases":       ["phonecase","aesthetic","accessories","protection","case"],
    "Accessories":       ["accessories","style","fashion","ootd","trending"],
}
_UNIVERSAL_TAGS = ["musthave","shopnow","findoftheday","instashop","trending",
                   "viral","gift","aesthetic"]

_CAPTION_TEMPLATES = [
    "Elevate your everyday with this stunning piece. Designed for those who appreciate the finer details in life. ✨",
    "The aesthetic upgrade your space has been waiting for. Minimal design, maximum impact. 🖤",
    "Where style meets function. This is the piece your feed (and your life) needs right now. 💫",
    "Obsessed doesn't even cover it. Limited stock — grab yours now. ☁️",
    "Built for the aesthetic-conscious. Crafted for those who refuse to compromise on style. 🌿",
    "The secret to a perfectly curated home? It's this. Shop before it sells out. ✨",
    "That 'where did you get that?' piece. Effortlessly chic, endlessly versatile. 🔥",
]


def _get_tags(product: dict) -> list:
    category = product.get("category", "")
    base = _CATEGORY_TAGS.get(category, ["aesthetic","lifestyle","trending"])
    return list(dict.fromkeys(base + _UNIVERSAL_TAGS))[:15]


def _clean_name(product: dict) -> str:
    title = product.get("title_translated") or product.get("title", "Product")
    return " ".join(title.split()[:5])


# ── Mock enrichment ────────────────────────────────────────────────────────────

def mock_enrich(product: dict) -> dict:
    raw_score    = product.get("raw_score", 50)
    margin       = float(product.get("margin_pct", 0))
    margin_bonus = min(15, max(0, (margin - 60) / 4))
    adjusted     = min(100, raw_score + margin_bonus)
    base         = adjusted / 10
    ai_score     = round(min(10.0, max(1.0, base + random.uniform(0.1, 0.5))), 1)

    return {
        "score":             ai_score,
        "niche_fit":         round(min(10.0, ai_score * random.uniform(0.85, 1.05)), 1),
        "visual_appeal":     round(min(10.0, ai_score * random.uniform(0.80, 1.10)), 1),
        "trend_score":       round(min(10.0, ai_score * random.uniform(0.75, 1.15)), 1),
        "competition_score": round(random.uniform(5.0, 8.5), 1),
        "product_name":      _clean_name(product),
        "caption":           random.choice(_CAPTION_TEMPLATES),
        "hashtags":          _get_tags(product),
        "audience":          infer_audience(product),
        "rejection_reason":  "" if ai_score >= 7.0 else "Score below threshold for niche",
    }


# ── Gemini 2.0 Flash (cheapest, with image analysis) ──────────────────────────

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


async def _fetch_image_b64(url: str) -> Optional[tuple]:
    """Download image → (base64_str, mime_type) or None."""
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(url, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                mime = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                if not mime.startswith("image/"):
                    mime = "image/jpeg"
                return base64.b64encode(r.content).decode(), mime
    except Exception as exc:
        log.debug("Image fetch failed %s: %s", url, exc)
    return None


async def gemini_enrich(product: dict, settings: dict) -> Optional[dict]:
    api_key = settings.get("gemini_key", "")
    if not api_key:
        return None

    niche  = settings.get("niche", "aesthetic lifestyle products")
    title  = product.get("title_translated") or product.get("title", "Unknown")
    img_url = (product.get("images") or [""])[0]

    text_part = {
        "text": (
            f"Title: {title}\n"
            f"Category: {product.get('category', '?')}\n"
            f"Cost: ₾{product.get('cost_eur','?')} → Sell: ₾{product.get('sell_price_eur','?')} "
            f"({product.get('margin_pct','?')}% margin)\n"
            f"Sold: {product.get('orders', 0)} | Platform: {product.get('source_platform','?')}"
        )
    }

    parts = [text_part]
    img_data = await _fetch_image_b64(img_url)
    if img_data:
        b64, mime = img_data
        parts = [{"inline_data": {"mime_type": mime, "data": b64}}, text_part]
        log.debug("Gemini: image included for '%s'", title[:40])
    else:
        log.debug("Gemini: text-only (no image) for '%s'", title[:40])

    payload = {
        "system_instruction": {"parts": [{"text": _GEMINI_SYSTEM.format(niche=niche)}]},
        "contents": [{"parts": parts}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "max_output_tokens": 500,
            "temperature": 0.4,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _GEMINI_URL,
                headers={"x-goog-api-key": api_key, "content-type": "application/json"},
                json=payload,
            )
        if resp.status_code != 200:
            log.warning("Gemini API %d: %s", resp.status_code, resp.text[:300])
            return None

        body = resp.json()
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"```json|```", "", text).strip()
        result = json.loads(text)
        if "audience" not in result:
            result["audience"] = infer_audience(product)
        log.info("Gemini '%s' → score=%.1f visual=%.1f",
                 title[:35], result.get("score", 0), result.get("visual_appeal", 0))
        return result

    except json.JSONDecodeError as exc:
        log.warning("Gemini JSON parse error: %s", exc)
    except Exception as exc:
        log.warning("Gemini enrichment error: %s", exc)
    return None


# ── Claude Haiku 4.5 (text-only fallback) ─────────────────────────────────────

async def anthropic_enrich(product: dict, settings: dict) -> Optional[dict]:
    api_key = settings.get("anthropic_key", "")
    if not api_key:
        return None

    niche  = settings.get("niche", "aesthetic lifestyle products")
    title  = product.get("title_translated") or product.get("title", "Unknown")

    user_content = (
        f"Title: {title}\n"
        f"Category: {product.get('category', '?')}\n"
        f"Cost: ₾{product.get('cost_eur','?')} → Sell: ₾{product.get('sell_price_eur','?')} "
        f"({product.get('margin_pct','?')}% margin)\n"
        f"Sold: {product.get('orders', 0)} | Rating: {product.get('rating', 0)}/5"
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
                    "max_tokens": 500,
                    "system": [{
                        "type": "text",
                        "text": _ANTHROPIC_SYSTEM.format(niche=niche),
                        "cache_control": {"type": "ephemeral"},
                    }],
                    "messages": [{"role": "user", "content": user_content}],
                },
            )
        if resp.status_code != 200:
            log.warning("Anthropic API %d — falling back to mock", resp.status_code)
            return None

        text = resp.json()["content"][0]["text"]
        text = re.sub(r"```json|```", "", text).strip()
        result = json.loads(text)
        if "audience" not in result:
            result["audience"] = infer_audience(product)
        return result

    except json.JSONDecodeError as exc:
        log.warning("Anthropic JSON parse error: %s", exc)
    except Exception as exc:
        log.warning("Anthropic enrichment error: %s", exc)
    return None


# ── Public entry point ─────────────────────────────────────────────────────────

async def ai_enrich(product: dict, settings: dict) -> Optional[dict]:
    """Gemini → Anthropic → mock, whichever key is available."""
    result = await gemini_enrich(product, settings)
    if result:
        return result
    result = await anthropic_enrich(product, settings)
    if result:
        return result
    return mock_enrich(product)
