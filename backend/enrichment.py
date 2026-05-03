"""
AI enrichment layer.

Priority:
  1. Gemini 2.0 Flash  (gemini_key set)    — image analysis, 15 RPM free
  2. Groq Llama 3.3    (groq_key set)      — 14,400 RPD free, text-only
  3. Claude Haiku 4.5  (anthropic_key set) — text-only scoring
  4. Mock rule-based   (no keys)           — deterministic, free
"""

import asyncio
import base64
import json
import logging
import random
import re
from typing import Optional

import httpx

from config.runtime import get_config

log = logging.getLogger(__name__)

# Limits concurrent AI calls globally — prevents two simultaneous jobs from
# both hammering the API and hitting rate limits faster.
_AI_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    global _AI_SEMAPHORE
    if _AI_SEMAPHORE is None:
        _AI_SEMAPHORE = asyncio.Semaphore(2)
    return _AI_SEMAPHORE


# ── Prompts ────────────────────────────────────────────────────────────────────

_GEMINI_SYSTEM = """
You are an expert product buyer for a profitable Instagram dropshipping store focused on couples, relationships, love gifts, cute aesthetic products, and emotional impulse purchases.

STORE PROFILE:
- Niche: couple gifts, romantic gifts, cute gifts, relationship products
- Audience: ages 16-35
- Buyers: people shopping for boyfriend, girlfriend, wife, husband, crush, anniversary, valentines, surprise gifts
- Style: cute, emotional, aesthetic, cozy, viral, heartwarming, TikTok-worthy
- Sell price range: affordable impulse buys and premium gifts
- Goal: products people instantly want to send to their partner

IMPORTANT:
This is NOT only a romantic flower/candle store.

We ALSO sell:
- cute gifts
- plushies
- aesthetic room decor
- matching accessories
- playful couple items
- novelty relationship gifts
- cozy products
- heart-shaped products
- emotional surprise gifts
- useful products with romantic/cute appeal
- viral TikTok relationship products
- products that make people say:
  "This is so cute, my partner would love this."

DO NOT reject products only because they are:
- playful
- cute
- decorative
- funny
- soft
- aesthetic
- novelty
- not directly romantic

ONLY reject if product is:
- generic boring household item
- industrial/tool item
- bulk/business item
- unrelated ugly random item
- clothing unless clearly gift-worthy
- unsafe or low quality junk

SCORING (1-10):

- niche_fit:
Does it fit a couple / cute / gift / relationship store?

- visual_appeal:
Would people stop scrolling and click?

- trend_score:
Would this trend on TikTok / Reels / gift pages?

- competition_score:
10 = low competition
1 = saturated everywhere

FINAL SCORE:
score =
niche_fit * 0.40 +
visual_appeal * 0.30 +
trend_score * 0.20 +
competition_score * 0.10

STORE MATCH RULE:
true if niche_fit >= 6 OR score >= 6.5

If product is cute, emotional, aesthetic, giftable, cozy, or likely to be bought casually for a partner:
BE GENEROUS.

Respond with a single JSON object containing these exact keys:
score, niche_fit, visual_appeal, trend_score, competition_score (all numbers 1-10),
store_match (boolean), product_name (string, 3-5 words), caption (string, 2-3 sentences),
hashtags (array of 15 strings without # symbol), audience (one of: male female unisex kids),
rejection_reason (string, empty if store_match is true).
"""     

_ANTHROPIC_SYSTEM = """\
You are a product buyer for an Instagram dropship store focused on couples and relationships.

STORE PROFILE:
- Niche: {niche}
- Target audience: {target_audience}
- Store style: romantic, heartfelt, gift-worthy — anniversary gifts, Valentine's Day, "just because" presents
- Sell price range: ₾{price_min}–₾{price_max}
- Examples of products we sell: {example_products}
- What we NEVER sell: generic household items with no romantic angle, industrial/bulk items, clothing, anything that could not plausibly be a gift between partners

A product MUST pass this test: "Would someone buy this for their boyfriend, girlfriend, husband, or wife?" If no, it does not belong in our store.

Based on the product title and details, decide: does this product belong in our store?

Score each field from 1 to 10:
- niche_fit: does this work as a couple gift or romantic item? Be strict — a generic mug is 3, couple matching mugs is 9
- visual_appeal: estimated gift-worthy and Instagram/TikTok appeal
- trend_score: how trending is this type of couple/gift product right now
- competition_score: 10 = blue ocean, 1 = saturated
- score: weighted average (niche_fit 40% + visual_appeal 30% + trend_score 20% + competition_score 10%)

Also provide:
- store_match: true if niche_fit >= 7 AND product works as a couple gift, false otherwise
- product_name: 3-5 word English name, no brand
- caption: 2-3 sentence romantic Instagram caption as if tagging your partner
- hashtags: exactly 15 hashtag strings (no # symbol) — couple, gift, and relationship tags
- audience: one of male, female, unisex, kids
- rejection_reason: if store_match is false, explain specifically why it does not work as a couple gift. Otherwise empty string.

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
    "Jewelry":           ["couplejewelry","matchingjewelry","giftforher","giftforhim","romanticgift"],
    "Accessories":       ["couplegift","relationshipgoals","giftideas","anniversary","lovegift"],
    "Home Decor":        ["couplegoals","romanticdecor","lovehomedecor","couplenesting","giftforhome"],
    "Home":              ["couplelife","hometogetherr","couplenesting","giftforhome","newcouple"],
    "Stationery":        ["lovenotes","couplejournal","romanticgift","giftforpartner","anniversarygift"],
    "Bags":              ["giftforher","coupleaccessories","romanticgift","lovegift","giftideas"],
    "Home Fragrance":    ["romanceathome","couplecandle","selfcaretogether","coupletime","romanticevening"],
    "Phone Accessories": ["couplematch","matchingphonecase","coupleaesthetic","relationshipgoals","giftforhim"],
    "Phone Cases":       ["matchingcases","couplematch","coupleaesthetic","giftforboyfriend","giftforgirlfriend"],
    "Electronics":       ["giftforhim","giftforboyfriend","coupletech","romanticgift","anniversarygift"],
}
_UNIVERSAL_TAGS = ["couplegoals","relationshipgoals","giftforhim","giftforher",
                   "anniversarygift","valentinesday","couplelife","lovegift"]


def _get_tags(product: dict) -> list:
    category = product.get("category", "")
    base = _CATEGORY_TAGS.get(category, ["aesthetic","lifestyle","trending"])
    return list(dict.fromkeys(base + _UNIVERSAL_TAGS))[:15]


def _clean_name(product: dict) -> str:
    title = product.get("title_translated") or product.get("title", "Product")
    return " ".join(title.split()[:5])


def _build_system_prompt(template: str, settings: dict) -> str:
    return template.format(
        niche=get_config("NICHE", settings.get("niche", "couple gifts & romantic products")).replace("{","").replace("}",""),
        target_audience=get_config("TARGET_AUDIENCE", settings.get("target_audience", "couples, people buying gifts for partners, ages 18-35")).replace("{","").replace("}",""),
        price_min=get_config("SELL_PRICE_MIN", settings.get("sell_price_min", 15)),
        price_max=get_config("SELL_PRICE_MAX", settings.get("sell_price_max", 80)),
        example_products=get_config("EXAMPLE_PRODUCTS", settings.get(
            "example_products",
            "matching couple bracelets, personalised photo frames, couple card games, romantic candle sets, love letter boxes, matching phone cases"
        )).replace("{","").replace("}",""),
    )


# ── Mock enrichment ────────────────────────────────────────────────────────────

def mock_enrich(product: dict) -> dict:
    raw_score    = product.get("raw_score", 50)
    margin       = float(product.get("margin_pct", 0))
    margin_bonus = min(15, max(0, (margin - 60) / 4))
    adjusted     = min(100, raw_score + margin_bonus)
    base         = adjusted / 10
    ai_score     = round(min(10.0, max(1.0, base + random.uniform(0.1, 0.5))), 1)
    store_match  = ai_score >= 6.2

    return {
        "score":             ai_score,
        "niche_fit":         round(min(10.0, ai_score * random.uniform(0.85, 1.05)), 1),
        "visual_appeal":     round(min(10.0, ai_score * random.uniform(0.80, 1.10)), 1),
        "trend_score":       round(min(10.0, ai_score * random.uniform(0.75, 1.15)), 1),
        "competition_score": round(random.uniform(5.0, 8.5), 1),
        "store_match":       store_match,
        "product_name":      _clean_name(product),
        "caption":           random.choice(_CAPTION_TEMPLATES),
        "hashtags":          _get_tags(product),
        "audience":          infer_audience(product),
        "rejection_reason":  "" if store_match else "Score below threshold for niche",
    }


_CAPTION_TEMPLATES = [
    "Because they deserve to feel loved every single day. The perfect gift for the person who has your whole heart. ❤️",
    "Some people come into your life and make everything better. Get them something that says exactly that. 🥹",
    "Tag the one who makes every day worth it. This one's for them. 💌",
    "It's the little things that mean the most. Surprise your person with something they'll never forget. 🎁",
    "For the one who deserves the world — start here. Because love is worth celebrating every day. 💍",
    "The gift that says 'I was thinking of you' without saying a word. Perfect for your favourite person. 🌹",
    "Love isn't just a feeling, it's the little moments you create together. Make this one count. ✨",
]


# ── Gemini 2.5 Flash-Lite ──────────────────────────────────────────────────────

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


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
    api_key = get_config("GEMINI_KEY", settings.get("gemini_key", ""))
    if not api_key:
        return None

    model = get_config("GEMINI_MODEL", settings.get("gemini_model", "gemini-2.0-flash"))
    title   = product.get("title_translated") or product.get("title", "Unknown")
    img_url = (product.get("images") or [""])[0]

    text_part = {
        "text": (
            f"Title: {title}\n"
            f"Category: {product.get('category', '?')}\n"
            f"Cost: ₾{product.get('cost_eur','?')} → Sell: ₾{product.get('sell_price_eur','?')} "
            f"({product.get('margin_pct','?')}% margin)\n"
            f"Sold: {product.get('orders', 0)} | Platform: {product.get('source_platform','?')}\n"
            f"Keyword searched: {product.get('keyword', '?')}"
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
        "system_instruction": {"parts": [{"text": _build_system_prompt(_GEMINI_SYSTEM, settings)}]},
        "contents": [{"parts": parts}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "max_output_tokens": 600,
            "temperature": 0.4,
        },
    }

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    _GEMINI_URL.format(model=model),
                    headers={"x-goog-api-key": api_key, "content-type": "application/json"},
                    json=payload,
                )

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 0))
                wait = retry_after if retry_after > 0 else 60
                print(f"[GEMINI 429] key=...{api_key[-6:]} body={resp.text[:300]}", flush=True)
                log.warning("Gemini 429 rate limit — waiting %ds (attempt %d/3)", wait, attempt + 1)
                await asyncio.sleep(wait)
                continue

            if resp.status_code != 200:
                log.warning("Gemini API %d: %s", resp.status_code, resp.text[:300])
                return None

            body = resp.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"```json|```", "", text).strip()
            result = json.loads(text)

            if "store_match" not in result:
                result["store_match"] = float(result.get("niche_fit", 0)) >= 6.0
            if "audience" not in result:
                result["audience"] = infer_audience(product)

            log.info(
                "Gemini '%s' → score=%.1f niche=%.1f visual=%.1f match=%s",
                title[:35],
                result.get("score", 0),
                result.get("niche_fit", 0),
                result.get("visual_appeal", 0),
                result.get("store_match"),
            )
            return result

        except json.JSONDecodeError as exc:
            log.warning("Gemini JSON parse error: %s", exc)
            return None
        except Exception as exc:
            log.warning("Gemini enrichment error: %s", exc)
            return None

    log.warning("Gemini: gave up after 3 rate-limit retries for '%s'", title[:40])
    return None


# ── Claude Haiku 4.5 (text-only fallback) ─────────────────────────────────────

async def anthropic_enrich(product: dict, settings: dict) -> Optional[dict]:
    api_key = get_config("ANTHROPIC_KEY", settings.get("anthropic_key", ""))
    if not api_key:
        return None

    title = product.get("title_translated") or product.get("title", "Unknown")

    user_content = (
        f"Title: {title}\n"
        f"Category: {product.get('category', '?')}\n"
        f"Cost: ₾{product.get('cost_eur','?')} → Sell: ₾{product.get('sell_price_eur','?')} "
        f"({product.get('margin_pct','?')}% margin)\n"
        f"Sold: {product.get('orders', 0)} | Rating: {product.get('rating', 0)}/5\n"
        f"Keyword searched: {product.get('keyword', '?')}"
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
                    "max_tokens": 600,
                    "system": [{
                        "type": "text",
                        "text": _build_system_prompt(_ANTHROPIC_SYSTEM, settings),
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

        if "store_match" not in result:
            result["store_match"] = float(result.get("niche_fit", 0)) >= 7.0
        if "audience" not in result:
            result["audience"] = infer_audience(product)
        return result

    except json.JSONDecodeError as exc:
        log.warning("Anthropic JSON parse error: %s", exc)
    except Exception as exc:
        log.warning("Anthropic enrichment error: %s", exc)
    return None


# ── Groq Llama 3.3 70B (text-only, very generous free tier) ───────────────────

_GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL = "llama-3.3-70b-versatile"


async def groq_enrich(product: dict, settings: dict) -> Optional[dict]:
    api_key = get_config("GROQ_KEY", settings.get("groq_key", ""))
    if not api_key:
        return None

    title = product.get("title_translated") or product.get("title", "Unknown")

    user_content = (
        f"Title: {title}\n"
        f"Category: {product.get('category', '?')}\n"
        f"Cost: ₾{product.get('cost_eur','?')} → Sell: ₾{product.get('sell_price_eur','?')} "
        f"({product.get('margin_pct','?')}% margin)\n"
        f"Sold: {product.get('orders', 0)} | Rating: {product.get('rating', 0)}/5\n"
        f"Keyword searched: {product.get('keyword', '?')}\n\n"
        "Respond with ONLY a JSON object — no markdown, no explanation."
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _GROQ_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": _build_system_prompt(_ANTHROPIC_SYSTEM, settings)},
                        {"role": "user",   "content": user_content},
                    ],
                    "max_tokens": 600,
                    "temperature": 0.4,
                    "response_format": {"type": "json_object"},
                },
            )

        if resp.status_code == 429:
            log.warning("Groq 429 rate limit — skipping to next provider")
            return None

        if resp.status_code != 200:
            log.warning("Groq API %d: %s", resp.status_code, resp.text[:300])
            return None

        text = resp.json()["choices"][0]["message"]["content"]
        text = re.sub(r"```json|```", "", text).strip()
        result = json.loads(text)

        if "store_match" not in result:
            result["store_match"] = float(result.get("niche_fit", 0)) >= 7.0
        if "audience" not in result:
            result["audience"] = infer_audience(product)

        log.info(
            "Groq '%s' → score=%.1f niche=%.1f visual=%.1f match=%s",
            title[:35],
            result.get("score", 0),
            result.get("niche_fit", 0),
            result.get("visual_appeal", 0),
            result.get("store_match"),
        )
        return result

    except json.JSONDecodeError as exc:
        log.warning("Groq JSON parse error: %s", exc)
    except Exception as exc:
        log.warning("Groq enrichment error: %s", exc)
    return None


# ── Public entry point ─────────────────────────────────────────────────────────

async def ai_enrich(product: dict, settings: dict) -> Optional[dict]:
    """Gemini → Groq → Anthropic → mock, whichever key is available."""
    async with _get_semaphore():
        result = await gemini_enrich(product, settings)
        if result:
            return result
        result = await groq_enrich(product, settings)
        if result:
            return result
        result = await anthropic_enrich(product, settings)
        if result:
            return result
        return mock_enrich(product)