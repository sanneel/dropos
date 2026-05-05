"""
AI enrichment layer — cost-optimised for high-volume dropshipping.

Priority chain (cheapest first):
  1. Groq Llama 3.3 70B   (14,400 RPD completely free) — text-only, runs first
  2. Gemini 2.5 Flash-Lite (1,500 RPD free tier)       — vision-aware, only for high-scoring products
  3. Mock rule-based       (always free)                — last resort

Why this order:
  - Groq is free with a very generous daily limit — use it for bulk scoring
  - Gemini's image analysis adds value only when raw_score ≥ 55 (genuinely promising product)
    so we reserve its free-tier quota for those cases
  - Anthropic removed: Groq is free and equivalent for text-only scoring
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
_GEMINI_QUOTA_EXHAUSTED = False

# Minimum raw_score required before we spend Gemini quota on a product.
# Products below this score are scored by Groq only (free).
_GEMINI_SCORE_THRESHOLD = 55


def _get_semaphore() -> asyncio.Semaphore:
    global _AI_SEMAPHORE
    if _AI_SEMAPHORE is None:
        _AI_SEMAPHORE = asyncio.Semaphore(3)
    return _AI_SEMAPHORE


# ── Prompts ────────────────────────────────────────────────────────────────────

_GEMINI_SYSTEM = """
You are an Elite Product Curator for "წყვილი" (Couple), a high-end, luxury-aesthetic boutique. Your goal is to reject 90% of products and only select the "1% of winners" that are guaranteed to go viral.

CURATION PHILOSOPHY:
We are NOT a general gift shop. We are a curated brand. Every product must look like it costs $100 even if we sell it for $30. If a product looks "cheap," "plastic," "common," or "boring," REJECT IT IMMEDIATELY.

STRICT SELECTION CRITERIA:
1. THE "WOW" FACTOR: If the user doesn't say "OMG I need this" in the first 0.5 seconds, it is a fail.
2. GEN-Z TREND ALIGNMENT: Must fit Y2K, Minimalist Luxury, or "Clean Girl/Boy" aesthetics.
3. DARK AESTHETIC COMPATIBILITY: Since our brand is Black & Gold, the product must look stunning in low-light or high-contrast photography.
4. NO "MOM" VIBES: Strictly NO vases, NO generic home decor, NO kitchenware, NO family-oriented gifts.

REJECTION AUTO-TRIGGERS (REJECT IF):
- The product photo has a messy or distracting background.
- The item is found in every local mall (e.g., basic teddy bears, generic jewelry).
- It looks like a utility rather than a luxury/emotional gift.
- There is any visible Chinese text (this is a hard fail for "luxury" feel).

ULTRA-STRICT SCORING (1-10):
- niche_fit: Only 9+ if it is a perfect "Couple Goal" item.
- visual_appeal: Only 9+ if it looks high-end/professional.
- trend_score: Only 9+ if it is currently exploding on TikTok/Reels.
- competition_score: 10 = extremely rare/unique; 1 = sold everywhere.

CRITICAL SCORE CALCULATION:
Score = (niche_fit * 0.50) + (visual_appeal * 0.30) + (trend_score * 0.20)

STRICT STORE MATCH RULE:
- store_match = TRUE ONLY IF: (Score >= 8.5) AND (niche_fit >= 8) AND (competition_score > 5).
- There is NO "generosity" here. If you are unsure, the answer is FALSE.

OUTPUT REQUIREMENTS:
- product_name: 3-5 words in Georgian. Must sound premium and alluring.
- caption: 2-3 sentences in Georgian. Focus on exclusivity and the "perfect surprise."
- rejection_reason: If store_match is false, provide a blunt, professional critique of why it failed (e.g., "Too generic," "Poor visual quality," "Doesn't fit brand age demographic").

Respond ONLY with a single JSON object.
"""

_TEXT_SYSTEM = """
You are an Elite Product Curator for "წყვილი" (Couple), a premium couple gift boutique targeting Gen-Z in Georgia (Tbilisi). 

CURATION PHILOSOPHY: We sell luxury couple gifts. Reject cheap, generic, or off-brand products hard.

SCORING (1-10):
- niche_fit: How well does this fit a romantic couple gift shop? (9+ only for perfect items)
- visual_appeal: Does it look premium? (9+ only for professional, high-end appearance)
- trend_score: Is this trending on TikTok/Reels right now? (9+ only for viral potential)
- competition_score: How unique is it? (10=extremely rare, 1=sold everywhere)

Score = (niche_fit * 0.50) + (visual_appeal * 0.30) + (trend_score * 0.20)
store_match = TRUE only if Score >= 8.0 AND niche_fit >= 7.5

OUTPUT (JSON only, no markdown):
{
  "score": float,
  "niche_fit": float,
  "visual_appeal": float,
  "trend_score": float,
  "competition_score": float,
  "store_match": bool,
  "product_name": "3-5 word Georgian name",
  "caption": "2-3 sentence Georgian caption",
  "rejection_reason": "Why it failed (if store_match=false)"
}
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
    ) if "{niche}" in template else template


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
        "has_chinese_text":  False,
        "chinese_text_note": "",
        "rejection_reason":  "" if store_match else "Score below threshold for niche",
        "ai_provider":       "mock",
    }


_CAPTION_TEMPLATES = [
    "პატარა საჩუქარია, მაგრამ ძალიან თბილი ემოცია აქვს. გაუკეთე სიურპრიზი ადამიანს, ვინც ყველაზე მეტად გიყვარს.",
    "ზოგი ნივთი უბრალოდ ამბობს: შენზე ვფიქრობდი. იდეალური პატარა საჩუქარია საყვარელი ადამიანისთვის.",
    "მონიშნე ის ადამიანი, ვისაც ეს აუცილებლად გაუხარდება. ასეთი დეტალები სიყვარულს კიდევ უფრო ტკბილს ხდის.",
    "საჩუქარი, რომელიც ყოველდღიურ დღეს პატარა დღესასწაულად აქცევს. იდეალურია წყვილებისთვის და გულწრფელი სიურპრიზისთვის.",
    "როცა გინდა უთხრა მიყვარხარ, მაგრამ უფრო საყვარლად. ეს ნივთი ზუსტად ამისთვისაა.",
]


# ── Gemini 2.5 Flash-Lite ──────────────────────────────────────────────────────

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_GEMINI_MODEL_ALIASES = {
    "gemini-2.0-flash": "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite": "gemini-2.5-flash-lite",
}


def _gemini_model(settings: dict) -> str:
    configured = get_config("GEMINI_MODEL", settings.get("gemini_model", "gemini-2.5-flash-lite"))
    model = str(configured or "gemini-2.5-flash-lite").strip()
    replacement = _GEMINI_MODEL_ALIASES.get(model)
    if replacement:
        log.warning("Gemini model %s is deprecated; using %s", model, replacement)
        return replacement
    return model


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
    global _GEMINI_QUOTA_EXHAUSTED
    api_key = get_config("GEMINI_KEY", settings.get("gemini_key", ""))
    if not api_key:
        return None
    if _GEMINI_QUOTA_EXHAUSTED:
        return None

    model = _gemini_model(settings)
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
        "system_instruction": {"parts": [{"text": _GEMINI_SYSTEM}]},
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
                print(f"[GEMINI 429] key=...{api_key[-6:]} body={resp.text[:300]}", flush=True)
                _GEMINI_QUOTA_EXHAUSTED = True
                log.warning("Gemini 429 quota/rate limit — disabling Gemini for this process and falling back")
                return None

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
            if "hashtags" not in result:
                result["hashtags"] = _get_tags(product)
            result["has_chinese_text"] = bool(result.get("has_chinese_text", False))
            result["chinese_text_note"] = str(result.get("chinese_text_note") or "")
            result["ai_provider"] = "gemini"

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

    log.warning("Gemini: gave up after retries for '%s'", title[:40])
    return None


# ── Groq Llama 3.3 70B (text-only, completely free at 14,400 RPD) ─────────────

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
                        {"role": "system", "content": _TEXT_SYSTEM},
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
        if "hashtags" not in result:
            result["hashtags"] = _get_tags(product)
        result["has_chinese_text"] = False
        result["chinese_text_note"] = ""
        result["ai_provider"] = "groq"

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
    """Cost-optimised AI enrichment.

    Chain:
      1. Groq  (free, 14,400 RPD) — always runs first, covers bulk volume
      2. Gemini (vision, free tier 1,500 RPD) — only for high raw_score (≥55)
         where seeing the actual product image adds meaningful value
      3. Mock  (free, rule-based) — last resort, no keys configured

    Anthropic removed: Groq is free, has a generous quota, and produces
    equivalent text-only scoring results.
    """
    async with _get_semaphore():
        raw_score = float(product.get("raw_score", 0))

        # ── Step 1: Groq (free) — primary scorer ──────────────────────────────
        result = await groq_enrich(product, settings)
        if result:
            return result

        # ── Step 2: Gemini (vision) — only when Groq unavailable + product promising
        if raw_score >= _GEMINI_SCORE_THRESHOLD:
            result = await gemini_enrich(product, settings)
            if result:
                return result

        # ── Step 3: Mock fallback ──────────────────────────────────────────────
        return mock_enrich(product)
