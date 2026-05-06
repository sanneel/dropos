"""
AI enrichment layer — DropOS.

Pipeline (in priority order):
  1. Gemini 2.5 Flash-Lite  (gemini_key set) — image + text analysis  ★ PRIMARY
  2. Groq Llama 3.3 70B     (groq_key set)   — text-only fallback, 14 400 RPD free
  3. Mock rule-based         (no keys)        — deterministic, always free

NOTE: Groq is TEXT-ONLY — it cannot see product images.
      Always configure a Gemini key for real image-based scoring.
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

_AI_SEMAPHORE: Optional[asyncio.Semaphore] = None
_GEMINI_QUOTA_EXHAUSTED = False


def _get_semaphore() -> asyncio.Semaphore:
    global _AI_SEMAPHORE
    if _AI_SEMAPHORE is None:
        _AI_SEMAPHORE = asyncio.Semaphore(2)
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
- rejection_reason: If store_match is false, provide a blunt, professional critique of why it failed.
- has_chinese_text: true/false — does the product image contain visible Chinese text?
- chinese_text_note: brief note if Chinese text found, else empty string.

Respond ONLY with a single JSON object.
"""

_GROQ_SYSTEM = """
You are an Elite Product Curator for "წყვილი" (Couple), a high-end luxury couple gift boutique.

NOTE: You are doing TEXT-ONLY analysis (no image). Score conservatively.

BRAND: Black & Gold aesthetic, Gen-Z luxury, couple gifts only. Products must be Instagram-worthy.

SCORING (1-10):
- niche_fit: Fit for couple gift shop
- visual_appeal: Expected visual quality based on product type/category (text only, be conservative)
- trend_score: Current trend alignment
- competition_score: Uniqueness

SCORE: (niche_fit * 0.50) + (visual_appeal * 0.30) + (trend_score * 0.20)
store_match = true ONLY IF score >= 8.0 AND niche_fit >= 7.5

OUTPUT: JSON only. Fields: score, niche_fit, visual_appeal, trend_score, competition_score, store_match, product_name (Georgian, 3-5 words), caption (Georgian, 2-3 sentences), rejection_reason (if rejected).
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
    return template


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


# ── Gemini 2.5 Flash-Lite (image + text) ──────────────────────────────────────

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_GEMINI_MODEL_ALIASES = {
    "gemini-2.5-flash": "gemini-2.5-flash",
    "gemini-2.5-flash": "gemini-2.5-flash",
}


def _gemini_model(settings: dict) -> str:
    configured = get_config("GEMINI_MODEL", settings.get("gemini_model", "gemini-2.5-flash"))
    model = str(configured or "gemini-2.5-flash").strip()
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
        log.debug("Gemini: text-only (no image available) for '%s'", title[:40])

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
                _GEMINI_QUOTA_EXHAUSTED = True
                log.warning("Gemini 429 quota exhausted — falling back to Groq (text-only)")
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
            result["has_chinese_text"] = bool(result.get("has_chinese_text", False))
            result["chinese_text_note"] = str(result.get("chinese_text_note") or "")
            result["hashtags"] = result.get("hashtags") or _get_tags(product)
            result["ai_provider"] = "gemini"

            log.info(
                "Gemini '%s' → score=%.1f niche=%.1f visual=%.1f match=%s img=%s",
                title[:35],
                result.get("score", 0),
                result.get("niche_fit", 0),
                result.get("visual_appeal", 0),
                result.get("store_match"),
                "yes" if img_data else "no",
            )
            return result

        except json.JSONDecodeError as exc:
            log.warning("Gemini JSON parse error: %s", exc)
            return None
        except Exception as exc:
            log.warning("Gemini enrichment error (attempt %d): %s", attempt + 1, exc)
            if attempt == 2:
                return None

    return None


# ── Groq Llama 3.3 70B (TEXT-ONLY fallback) ───────────────────────────────────
# Groq cannot process images. It is used as a free text-only fallback when
# Gemini is unavailable (no key, quota exhausted, or network error).

_GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL = "llama-3.3-70b-versatile"


async def groq_enrich(product: dict, settings: dict) -> Optional[dict]:
    """Text-only scoring via Groq. No image analysis."""
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
        "NOTE: No image available. Score conservatively on visual_appeal.\n"
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
                        {"role": "system", "content": _GROQ_SYSTEM},
                        {"role": "user",   "content": user_content},
                    ],
                    "max_tokens": 600,
                    "temperature": 0.4,
                    "response_format": {"type": "json_object"},
                },
            )

        if resp.status_code == 429:
            log.warning("Groq 429 rate limit — falling back to mock")
            return None

        if resp.status_code != 200:
            log.warning("Groq API %d: %s", resp.status_code, resp.text[:300])
            return None

        text = resp.json()["choices"][0]["message"]["content"]
        text = re.sub(r"```json|```", "", text).strip()
        result = json.loads(text)

        if "store_match" not in result:
            result["store_match"] = float(result.get("niche_fit", 0)) >= 7.5
        if "audience" not in result:
            result["audience"] = infer_audience(product)
        result["has_chinese_text"] = False   # Groq cannot detect Chinese text in images
        result["chinese_text_note"] = ""
        result["hashtags"] = result.get("hashtags") or _get_tags(product)
        result["ai_provider"] = "groq"

        log.info(
            "Groq (text-only) '%s' → score=%.1f niche=%.1f match=%s",
            title[:35],
            result.get("score", 0),
            result.get("niche_fit", 0),
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
    """
    Enrich a product with AI scoring.

    Chain:
      1. Gemini (image + text) — best quality, uses actual product photos
      2. Groq (text-only)      — free fallback when Gemini is unavailable
      3. Mock (rule-based)     — always works, zero cost

    Gemini MUST be configured (Settings → gemini_key) for real image analysis.
    Groq is only for metadata-based fallback scoring.
    """
    async with _get_semaphore():
        # 1. Gemini — primary scorer, analyzes actual product images
        result = await gemini_enrich(product, settings)
        if result:
            return result

        # 2. Groq — text-only fallback (free, no image analysis)
        result = await groq_enrich(product, settings)
        if result:
            return result

        # 3. Mock — last resort, always available
        return mock_enrich(product)
