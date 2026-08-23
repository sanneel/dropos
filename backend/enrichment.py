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
import time
from typing import Optional

import httpx

from config.runtime import get_config
from collage import create_collage

log = logging.getLogger(__name__)

_AI_SEMAPHORE: Optional[asyncio.Semaphore] = None
# When Gemini returns 429 we back off for a while instead of giving up for the
# whole process lifetime (the old behaviour silently downgraded every later
# batch to text-only Groq or the mock scorer until a redeploy).
_GEMINI_COOLDOWN_SECONDS = 600
_GEMINI_RETRY_AFTER: float = 0.0


def gemini_available(settings: dict) -> bool:
    """True when a Gemini key is configured and we are not in a 429 cooldown."""
    if not get_config("GEMINI_KEY", settings.get("gemini_key", "")):
        return False
    return time.time() >= _GEMINI_RETRY_AFTER


def _gemini_backoff(reason: str) -> None:
    global _GEMINI_RETRY_AFTER
    _GEMINI_RETRY_AFTER = time.time() + _GEMINI_COOLDOWN_SECONDS
    log.warning("Gemini %s — pausing Gemini calls for %ds", reason, _GEMINI_COOLDOWN_SECONDS)


def ai_configured(settings: dict) -> bool:
    """True when at least one real AI provider key exists (Gemini or Groq)."""
    return bool(get_config("GEMINI_KEY", settings.get("gemini_key", ""))
                or get_config("GROQ_KEY", settings.get("groq_key", "")))


def _get_semaphore() -> asyncio.Semaphore:
    global _AI_SEMAPHORE
    if _AI_SEMAPHORE is None:
        _AI_SEMAPHORE = asyncio.Semaphore(2)
    return _AI_SEMAPHORE


# ── Prompts ────────────────────────────────────────────────────────────────────

_DEFAULT_STORE_NAME   = "Tskvili"
_DEFAULT_AUDIENCE     = "Gen-Z couples in Georgia (ages 16–26); products are bought by one person for their partner"
_DEFAULT_PRICE_MIN    = 40
_DEFAULT_PRICE_MAX    = 119
_DEFAULT_EXAMPLES     = ("matching jewelry sets, projection necklaces, long-distance touch lamps, "
                         "open-when letter kits, star projectors, romantic neon signs, coquette accessories")

_GEMINI_SYSTEM_TEMPLATE = """
You are a product curator for {store_name}, a romantic gift store. Audience: {audience}. Price range is ₾{price_min}–₾{price_max}.
{niche_line}The single most important question: would a 20-year-old girl see this on TikTok and immediately send it to her boyfriend saying "omg we need this"? If yes → approve. If it needs explaining why it's romantic → reject.
APPROVE products that are:
- Cute, aesthetic, or emotionally triggering with a clear romantic angle
- Matching jewelry sets (necklaces, bracelets, rings) — any material, not just silver
- Projection necklaces, moon/star/sun pendants
- Long-distance touch products (smart bracelets, touch lamps)
- Cute plushies with a romantic angle (sold as a gift for partner)
- Open-when letter kits, reasons-I-love-you jars, love note sets
- Star projectors, galaxy lamps — if well-photographed with romantic framing
- Neon signs with romantic text
- Coquette aesthetic accessories (bows, pearls, heart charms)
- Anything that looks good in a TikTok or Instagram Reels post
- Clean or moody product photography — both dark romance and soft pastel work
Examples of products that sell well here: {examples}.
REJECT products that are:
- Over ₾{price_max} sell price
- Generic gift boxes with no clear hero product
- Wedding/engagement rings (too serious, wrong demographic)
- Gold rings that look like wedding bands
- His/hers mugs, matching hoodies, basic text items — oversaturated
- Children's toys with no romantic angle
- Industrial, home appliance, kitchen, office products
- Anything where you have to stretch to explain the romantic connection
CHINESE TEXT / WATERMARKS: if the product itself is good but the photo has Chinese text, a supplier watermark, factory logo or certificate badge, do NOT reject it — score it normally and set has_chinese_text=true with a short chinese_text_note describing where the text is. The image will be cleaned before posting.
SCORING:
cute_appeal (0–10) × 0.30 — Is this instantly cute or beautiful? Would someone screenshot it?
romantic_trigger (0–10) × 0.25 — Does it create a "thinking of you" or "we need this" feeling?
visual_score (0–10) × 0.20 — Can this image be posted to Instagram right now as-is (ignoring removable text)?
trend_fit (0–10) × 0.15 — Does this feel current — TikTok, coquette, soft girl, dark romance, or viral?
giftability (0–10) × 0.10 — Is this clearly something you'd buy for a romantic partner?
composite = (cute_appeal×0.30) + (romantic_trigger×0.25) + (visual_score×0.20) + (trend_fit×0.15) + (giftability×0.10)
VERDICTS:
top_priority:     composite ≥ 8.0 AND romantic_trigger ≥ 7
strong_candidate: composite ≥ 7.0
pending_review:   composite ≥ 6.0
auto_reject:      composite < 6.0 OR any hard reject triggered
Return ONLY valid JSON:
{{
  "cute_appeal": int,
  "romantic_trigger": int,
  "visual_score": int,
  "trend_fit": int,
  "giftability": int,
  "composite": float,
  "verdict": "top_priority|strong_candidate|pending_review|auto_reject",
  "product_tier": "cute_romantic|matching_jewelry|emotional_gift|aesthetic_decor|auto_reject",
  "rejection_reason": "string or null",
  "viral_angle": "one sentence or null",
  "emotional_hook": "one sentence or null",
  "has_chinese_text": true|false,
  "chinese_text_note": "string or null",
  "product_name": "Georgian 3-5 words if verdict is not auto_reject else empty string",
  "caption": "Georgian 2-3 sentences for Instagram if verdict is not auto_reject else empty string",
  "hashtags": ["up to 12 hashtags without # sign"],
  "confidence": float
}}
"""


def _num(value, fallback):
    try:
        f = float(value)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return fallback


def build_gemini_system(settings: dict | None = None) -> str:
    """Render the curator prompt from store settings (falls back to Tskvili defaults)."""
    settings = settings or {}
    niche = str(settings.get("niche") or "").strip()
    niche_line = f"Store focus: {niche}.\n" if niche else ""
    return _GEMINI_SYSTEM_TEMPLATE.format(
        store_name=str(settings.get("store_name") or _DEFAULT_STORE_NAME).strip() or _DEFAULT_STORE_NAME,
        audience=str(settings.get("target_audience") or _DEFAULT_AUDIENCE).strip() or _DEFAULT_AUDIENCE,
        price_min=_num(settings.get("sell_price_min"), _DEFAULT_PRICE_MIN),
        price_max=_num(settings.get("sell_price_max"), _DEFAULT_PRICE_MAX),
        examples=str(settings.get("example_products") or _DEFAULT_EXAMPLES).strip() or _DEFAULT_EXAMPLES,
        niche_line=niche_line,
    ).strip()


# Kept for backwards compatibility with callers/tests that import the constant.
_GEMINI_SYSTEM = build_gemini_system({})

_GROQ_SYSTEM = """
You are an elite product curator for CUTE COUPLE GIFTS — a premium Gen-Z and Millennial couple gift brand on Instagram. You should reject the majority of what you see.
NOTE: TEXT-ONLY analysis — no image access. Cap visual_score at 6 unless the title or description clearly confirms aesthetic quality.

THE BRAND:
- Aesthetic: dark romance, minimalist silver, soft pink, Y2K, cottagecore
- Audience: couples aged 16–30, buying gifts for each other
- NOT: generic, childish, grandma gifts, home decor, hobby items, fashion accessories without a clear couple angle

HARD REJECT — verdict="auto_reject" immediately if ANY applies:
- Plush toys, stuffed animals, cartoon characters (Stitch, Sanrio, Barbie, Disney, Pokémon)
- Generic gift sets with no specific couple identity (random mugs, notebooks, pens, cosmetics)
- Items marketed to mothers, teachers, children, elderly, or professionals
- Industrial, automotive, agricultural, or B2B products
- Luxury brand dupes or counterfeits
- Food, supplements, or consumables

SCORING (each 0–10):
couple_angle (0.30): Made for couples or easily gifted between partners? 10=exclusively for couples, 0=no couple application
emotional_trigger (0.25): Creates feelings of love, nostalgia, longing, excitement? 10=deep emotional product, 0=emotionally dead
visual_score (0.20): Instagram-worthy? TEXT-ONLY: cap at 6 unless title confirms premium aesthetic
trend_alignment (0.15): Fits Gen-Z couple trends now? 10=Y2K/dark romance/coquette/kawaii, 0=dated
demographic_fit (0.10): For 16–30 year old couples? 10=unmistakably, 0=wrong demographic

composite = (couple_angle×0.30) + (emotional_trigger×0.25) + (visual_score×0.20) + (trend_alignment×0.15) + (demographic_fit×0.10)

VERDICT: top_priority (≥8.0 AND emotional_trigger≥8) | strong_candidate (≥7.0 AND emotional_trigger≥6) | pending_review (≥6.0) | auto_reject (<6.0)
store_match = true ONLY IF top_priority or strong_candidate

Return ONLY JSON (no markdown):
{
  "couple_angle": 0-10, "emotional_trigger": 0-10, "visual_score": 0-10,
  "trend_alignment": 0-10, "demographic_fit": 0-10, "composite": float,
  "verdict": "top_priority|strong_candidate|pending_review|auto_reject",
  "product_tier": "core_couple|viral_adjacent|sentimental|lifestyle|auto_reject",
  "confidence": 0.0-1.0, "store_match": true|false,
  "viral_angle": "one sentence or null", "emotional_hook": "one sentence or null",
  "rejection_reason": "string or null",
  "product_name": "Georgian 3-5 words if store_match=true else empty string",
  "caption": "Georgian 2-3 sentences if store_match=true else empty string",
  "hashtags": []
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


def _build_system_text(context_snippet: str | None, settings: dict | None = None) -> str:
    """
    Return the system prompt text for a Gemini call, rendered from settings.

    When context_snippet is a non-empty string (decision-memory flag ON with
    enough history) it is appended as a clearly delimited addendum.  The base
    curation rules and scoring weights are never modified.
    """
    base = build_gemini_system(settings)
    if not context_snippet:
        return base
    return f"{base}\n{context_snippet}"


# ── Shared normalization ───────────────────────────────────────────────────────

def _pick(*keys, src: dict, default: float = 0.0) -> float:
    """Return first non-zero value found among keys in src, else default."""
    for k in keys:
        v = src.get(k)
        if v is not None:
            try:
                f = float(v)
                if f != 0:
                    return f
            except (TypeError, ValueError):
                pass
    return default


def _normalize_enrichment(result: dict, product: dict, provider: str) -> dict:
    """
    Coerce an AI response into the canonical enrichment schema.

    Handles any field names Gemini might return — uses alias lists so a
    hallucinated field name (cute_appeal, romantic_trigger, trend_fit, etc.)
    still resolves to the correct dimension rather than silently returning 0.

    Shapes handled:
    - New flat schema: couple_angle / emotional_trigger / visual_score /
      trend_alignment / demographic_fit + composite
    - Mid-generation schema: composite_score + scores sub-object
    - Legacy schema: niche_fit + visual_appeal + trend_score
    """
    # Detect new flat schema: any recognised dimension key present as a top-level field
    _NEW_KEYS = {
        "couple_angle", "couple_score", "couple_appeal", "cute_appeal", "romantic_score",
        "emotional_trigger", "romantic_trigger", "emotion_score", "emotional_score",
        "visual_score", "visual_appeal", "image_score", "visual",
        "trend_alignment", "trend_fit", "trend_score",
        "demographic_fit", "audience_fit", "giftability", "demographic_score",
    }
    new_schema = bool(_NEW_KEYS & result.keys()) or (
        "composite" in result and "composite_score" not in result
    )

    if new_schema:
        # ── New flat schema — try every alias Gemini might use ─────────────────
        couple    = _pick("couple_angle","couple_score","couple_appeal","cute_appeal",
                          "romantic_score", src=result)
        emotional = _pick("emotional_trigger","romantic_trigger","emotion_score",
                          "emotional_score","emotional","romantic", src=result)
        visual    = _pick("visual_score","visual_appeal","image_score","visual",
                          src=result)
        trend     = _pick("trend_alignment","trend_fit","trend_score","trend",
                          src=result)
        demo      = _pick("demographic_fit","audience_fit","giftability",
                          "demographic_score","demographic","audience", src=result)
        composite = _pick("composite","composite_score","total_score","score",
                          src=result)

        # Always recompute composite from dimensions — guards against Gemini
        # returning a composite that doesn't match its own sub-scores
        if couple + emotional + visual + trend + demo > 0:
            composite = round(couple*0.30 + emotional*0.25 + visual*0.20
                              + trend*0.15 + demo*0.10, 2)

        result["composite_score"] = composite
        result["scores"] = {
            "couple_angle":      round(couple, 1),
            "emotional_trigger": round(emotional, 1),
            "visual_score":      round(visual, 1),
            "trend_alignment":   round(trend, 1),
            "demographic_fit":   round(demo, 1),
        }

        if composite == 0:
            log.warning(
                "normalize: all dimensions zero for provider=%s product=%s — "
                "Gemini may have returned unexpected field names. Raw keys: %s",
                provider,
                (product.get("title_translated") or product.get("title", "?"))[:40],
                list(result.keys()),
            )

    else:
        # ── Legacy / mid-generation schema ────────────────────────────────────
        if "composite_score" not in result:
            niche_l  = float(result.get("niche_fit", 0))
            visual_l = float(result.get("visual_appeal", 0))
            trend_l  = float(result.get("trend_score", 0))
            result["composite_score"] = round(niche_l*0.50 + visual_l*0.30 + trend_l*0.20, 2)
        composite = float(result["composite_score"])

        if "scores" not in result:
            niche_l  = float(result.get("niche_fit", 0))
            visual_l = float(result.get("visual_appeal", 0))
            trend_l  = float(result.get("trend_score", 0))
            fallback = round(composite * 0.9, 1) if composite else 0.0
            result["scores"] = {
                "emotional_trigger": round(niche_l, 1) if niche_l else fallback,
                "viral_potential":   round(trend_l, 1) if trend_l else fallback,
                "giftability":       round(niche_l * 0.9, 1) if niche_l else fallback,
                "aesthetic_fit":     round(visual_l, 1) if visual_l else fallback,
                "impulse_score":     round(trend_l * 0.9, 1) if trend_l else fallback,
                "audience_fit":      round(niche_l * 0.85, 1) if niche_l else fallback,
            }
        emotional = float(result["scores"].get("emotional_trigger", 0))

    composite = float(result.get("composite_score", 0))
    if new_schema:
        emotional = _pick("emotional_trigger","romantic_trigger","emotion_score",
                          "emotional_score", src=result)

    # ── Derive verdict ─────────────────────────────────────────────────────────
    if "verdict" not in result:
        if composite >= 8.0 and emotional >= 8:
            verdict = "top_priority"
        elif composite >= 7.0 and emotional >= 6:
            verdict = "strong_candidate"
        elif composite >= 6.0:
            verdict = "pending_review"
        else:
            verdict = "auto_reject"
        result["verdict"] = verdict

    # ── Derive store_match ─────────────────────────────────────────────────────
    if "store_match" not in result:
        result["store_match"] = result["verdict"] in ("top_priority", "strong_candidate")

    # ── Fill optional fields ───────────────────────────────────────────────────
    result.setdefault("product_tier", "auto_reject" if not result["store_match"] else "core_couple")
    result.setdefault("confidence", 0.70)
    result.setdefault("viral_angle", "")
    result.setdefault("emotional_hook", "")
    result.setdefault("content_hooks", [])
    result.setdefault("rejection_reason", "" if result["store_match"] else "Score below threshold")
    result.setdefault("product_name", _clean_name(product) if result["store_match"] else "")
    result.setdefault("caption", "")
    result["hashtags"] = result.get("hashtags") or _get_tags(product)
    result["audience"] = result.get("audience") or infer_audience(product)
    result["has_chinese_text"] = bool(result.get("has_chinese_text", False))
    result["chinese_text_note"] = str(result.get("chinese_text_note") or "")
    result["ai_provider"] = provider

    # Backfill legacy top-level fields so database.py write paths never store zeros.
    result.setdefault("score", composite)
    if new_schema:
        result.setdefault("niche_fit",     float(result.get("emotional_trigger", 0)))
        result.setdefault("visual_appeal", float(result.get("visual_score", 0)))
        result.setdefault("trend_score",   float(result.get("trend_alignment", 0)))
    else:
        result.setdefault("niche_fit",     result["scores"].get("emotional_trigger", 0))
        result.setdefault("visual_appeal", result["scores"].get("aesthetic_fit", 0))
        result.setdefault("trend_score",   result["scores"].get("viral_potential", 0))

    return result


# ── Mock enrichment ────────────────────────────────────────────────────────────

def mock_enrich(product: dict) -> dict:
    """
    Rule-based stand-in used when no AI provider is available.

    It is deliberately *not* a judge: it derives a flat score from the raw rule
    score + margin and always returns verdict=pending_review / store_match=True
    so the product lands in the human review queue instead of being rejected by
    a coin flip.  ai_provider="mock" lets the worker tell the two cases apart.
    """
    raw_score    = float(product.get("raw_score", 50) or 50)
    margin       = float(product.get("margin_pct", 0) or 0)
    margin_bonus = min(15, max(0, (margin - 60) / 4))
    adjusted     = min(100, raw_score + margin_bonus)
    base         = round(max(1.0, min(10.0, adjusted / 10)), 1)

    couple = emotional = visual = trend = demo = base
    composite = round(couple*0.30 + emotional*0.25 + visual*0.20 + trend*0.15 + demo*0.10, 1)

    return {
        "couple_angle":      couple,
        "emotional_trigger": emotional,
        "visual_score":      visual,
        "trend_alignment":   trend,
        "demographic_fit":   demo,
        "product_tier":      "unscored",
        "composite_score":   composite,
        "score":             composite,
        "scores": {
            "couple_angle":      couple,
            "emotional_trigger": emotional,
            "visual_score":      visual,
            "trend_alignment":   trend,
            "demographic_fit":   demo,
        },
        "confidence":        0.0,
        "verdict":           "pending_review",
        "store_match":       True,
        "viral_angle":       "",
        "emotional_hook":    "",
        "content_hooks":     [],
        "product_name":      _clean_name(product),
        "caption":           random.choice(_CAPTION_TEMPLATES),
        "hashtags":          _get_tags(product),
        "audience":          infer_audience(product),
        "has_chinese_text":  False,
        "chinese_text_note": "",
        "rejection_reason":  "",
        "ai_provider":       "mock",
        "niche_fit":         emotional,
        "visual_appeal":     visual,
        "trend_score":       trend,
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
_GEMINI_MODEL_ALIASES: dict[str, str] = {
    # Map retired/legacy model names to their current replacements.
    # "gemini-2.5-flash-lite": "gemini-2.5-flash",  # example entry
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


async def gemini_enrich(product: dict, settings: dict, context_snippet: str | None = None) -> Optional[dict]:
    api_key = get_config("GEMINI_KEY", settings.get("gemini_key", ""))
    if not api_key or not gemini_available(settings):
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
        "system_instruction": {"parts": [{"text": _build_system_text(context_snippet, settings)}]},
        "contents": [{"parts": parts}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "max_output_tokens": 900,
            "temperature": 0.4,
        },
    }

    # ── Retry loop: 3 attempts with exponential back-off on transient errors ──
    _RETRYABLE = {429, 500, 502, 503, 504}
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    _GEMINI_URL.format(model=model),
                    headers={"x-goog-api-key": api_key, "content-type": "application/json"},
                    json=payload,
                )

            # Quota / rate limit — back off for a while, fall back to Groq meanwhile
            if resp.status_code == 429:
                _gemini_backoff("429 rate limit / quota")
                return None

            # Transient server error: wait then retry
            if resp.status_code in _RETRYABLE:
                wait = 3 * (attempt + 1)  # 3s, 6s, 9s
                log.warning("Gemini API %d on attempt %d — retrying in %ds", resp.status_code, attempt + 1, wait)
                await asyncio.sleep(wait)
                continue

            if resp.status_code != 200:
                log.warning("Gemini API %d: %s", resp.status_code, resp.text[:300])
                return None

            body = resp.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"```json|```", "", text).strip()
            result = json.loads(text)

            result = _normalize_enrichment(result, product, "gemini")
            log.info(
                "Gemini '%s' → composite=%.1f verdict=%s emotional=%s match=%s img=%s",
                title[:35],
                result.get("composite_score", 0),
                result.get("verdict", "?"),
                result.get("scores", {}).get("emotional_trigger", "?"),
                result.get("store_match"),
                "yes" if img_data else "no",
            )
            return result

        except json.JSONDecodeError as exc:
            log.warning("Gemini JSON parse error: %s", exc)
            return None
        except Exception as exc:
            wait = 3 * (attempt + 1)
            log.warning("Gemini enrichment error (attempt %d/%d, retry in %ds): %s", attempt + 1, 3, wait, exc)
            if attempt == 2:
                return None
            await asyncio.sleep(wait)

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

    desc = (product.get("description") or "")[:300]
    user_content = (
        f"Title: {title}\n"
        f"Description: {desc}\n"
        f"Category: {product.get('keyword') or product.get('category', '?')}\n"
        f"Sell price: ₾{product.get('sell_price_eur','?')}\n"
        f"Orders: {product.get('orders', 0)} | Rating: {product.get('rating', 0)}/5\n\n"
        "NOTE: No image available. Cap visual_score at 6 unless title confirms premium aesthetic.\n"
        "Respond with ONLY a JSON object — no markdown, no explanation."
    )

    _RETRYABLE = {429, 500, 502, 503, 504}

    for attempt in range(3):
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

            # Transient errors: retry with back-off
            if resp.status_code in _RETRYABLE:
                wait = 3 * (attempt + 1)
                log.warning("Groq API %d on attempt %d — retrying in %ds", resp.status_code, attempt + 1, wait)
                await asyncio.sleep(wait)
                continue

            if resp.status_code != 200:
                log.warning("Groq API %d: %s", resp.status_code, resp.text[:300])
                return None

            text = resp.json()["choices"][0]["message"]["content"]
            text = re.sub(r"```json|```", "", text).strip()
            result = json.loads(text)

            result = _normalize_enrichment(result, product, "groq")
            log.info(
                "Groq (text-only) '%s' → composite=%.1f verdict=%s match=%s",
                title[:35],
                result.get("composite_score", 0),
                result.get("verdict", "?"),
                result.get("store_match"),
            )
            return result

        except json.JSONDecodeError as exc:
            log.warning("Groq JSON parse error: %s", exc)
            return None
        except Exception as exc:
            wait = 3 * (attempt + 1)
            log.warning("Groq enrichment error (attempt %d/%d, retry in %ds): %s", attempt + 1, 3, wait, exc)
            if attempt == 2:
                return None
            await asyncio.sleep(wait)

    return None


# ── Public entry point ─────────────────────────────────────────────────────────

async def ai_enrich(product: dict, settings: dict, context_snippet: str | None = None) -> Optional[dict]:
    """
    Enrich a product with AI scoring.

    Chain:
      1. Gemini (image + text) — best quality, uses actual product photos
      2. Groq (text-only)      — free fallback when Gemini is unavailable
      3. Mock (rule-based)     — always works, zero cost

    context_snippet is injected into the Gemini system prompt when the
    ai_context_injection feature flag is ON and enough decision history exists.
    Pass None (the default) to preserve the pre-Phase-2 baseline behavior.

    Gemini MUST be configured (Settings → gemini_key) for real image analysis.
    Groq is only for metadata-based fallback scoring.
    """
    async with _get_semaphore():
        # 1. Gemini — primary scorer, analyzes actual product images
        result = await gemini_enrich(product, settings, context_snippet)
        if result:
            return result

        # 2. Groq — text-only fallback (free, no image analysis)
        result = await groq_enrich(product, settings)
        if result:
            return result

        # 3. Mock — last resort, always available
        return mock_enrich(product)

async def _enrich_individually(products: list[dict], settings: dict, context_snippet: str | None) -> list[dict]:
    """Per-product fallback: Gemini (if available) → Groq → mock."""
    return [await ai_enrich(p, settings, context_snippet) for p in products]


async def ai_enrich_batch(products: list[dict], settings: dict, context_snippet: str | None = None) -> list[dict]:
    """
    Groups products into a collage and sends to Gemini for batch scoring.
    Saves 80%+ on Vision tokens.

    Fallback chain when the batch call cannot be made or fails:
      Gemini (per product) → Groq text-only (per product) → mock (review queue).
    Every result carries ai_provider so the worker knows how much to trust it.
    """
    if not products:
        return []

    if not gemini_available(settings):
        # No Gemini key or cooling down after a 429 — go straight to per-product chain
        return await _enrich_individually(products, settings, context_snippet)
    api_key = get_config("GEMINI_KEY", settings.get("gemini_key", ""))

    # 1. Create collage
    image_urls = [(p.get("images") or [""])[0] for p in products]
    collage_bytes = await create_collage(image_urls)

    if not collage_bytes:
        log.warning("Failed to create collage for batch — scoring products individually")
        return await _enrich_individually(products, settings, context_snippet)

    # 2. Prepare Gemini Payload
    model = _gemini_model(settings)
    b64_collage = base64.b64encode(collage_bytes).decode()

    products_text = "\n".join([
        f"Product {i + 1}: {(p.get('title_translated') or p.get('title') or '')[:80]} "
        f"(sell price: ₾{p.get('sell_price_eur', '?')}, orders: {p.get('orders', 0)}, keyword: {p.get('keyword', '')})"
        for i, p in enumerate(products)
    ])

    batch_system = (
        _build_system_text(context_snippet, settings)
        + """

BATCH MODE:
You are evaluating multiple products from one collage (numbered left-to-right,
top-to-bottom). Return exactly one JSON object with a "results" array. The array
must contain one object for each listed product, in the same order, using
product_index values 1 through N. Each object uses exactly the same fields as the
single-product schema above, plus "product_index".

Required shape:
{
  "results": [
    {
      "product_index": 1,
      "cute_appeal": 0-10,
      "romantic_trigger": 0-10,
      "visual_score": 0-10,
      "trend_fit": 0-10,
      "giftability": 0-10,
      "composite": 0-10,
      "verdict": "top_priority|strong_candidate|pending_review|auto_reject",
      "product_tier": "cute_romantic|matching_jewelry|emotional_gift|aesthetic_decor|auto_reject",
      "confidence": 0.0-1.0,
      "viral_angle": "one sentence or null",
      "emotional_hook": "one sentence or null",
      "rejection_reason": "string or null",
      "has_chinese_text": true|false,
      "chinese_text_note": "string or null",
      "product_name": "Georgian 3-5 words if verdict is not auto_reject else empty string",
      "caption": "Georgian 2-3 sentences if verdict is not auto_reject else empty string",
      "hashtags": []
    }
  ]
}

Do not return a single product object. Do not omit product_index.
"""
    )

    payload = {
        "system_instruction": {"parts": [{"text": batch_system}]},
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": "image/jpeg", "data": b64_collage}},
                {"text": f"Evaluate exactly {len(products)} products:\n{products_text}"}
            ]
        }],
        "generationConfig": {
            "response_mime_type": "application/json",
            "max_output_tokens": 4000,
            "temperature": 0.3,
        },
    }

    _RETRYABLE = {500, 502, 503, 504}
    parsed = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    _GEMINI_URL.format(model=model),
                    headers={"x-goog-api-key": api_key, "content-type": "application/json"},
                    json=payload,
                )
            if resp.status_code == 429:
                _gemini_backoff("429 rate limit / quota (batch)")
                return await _enrich_individually(products, settings, context_snippet)
            if resp.status_code in _RETRYABLE and attempt == 0:
                log.warning("Batch Gemini %d — retrying once", resp.status_code)
                await asyncio.sleep(4)
                continue
            if resp.status_code != 200:
                log.warning("Batch Gemini error %d: %s", resp.status_code, resp.text[:200])
                return await _enrich_individually(products, settings, context_snippet)

            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"```json|```", "", text).strip()
            parsed = json.loads(text)
            break
        except Exception as e:
            log.error("Batch Vision AI failed (attempt %d): %s", attempt + 1, e)
            if attempt == 0:
                await asyncio.sleep(3)
                continue
            return await _enrich_individually(products, settings, context_snippet)

    if parsed is None:
        return await _enrich_individually(products, settings, context_snippet)

    results_list = parsed.get("results") if isinstance(parsed, dict) else None
    if not isinstance(results_list, list):
        if len(products) == 1 and isinstance(parsed, dict):
            results_list = [{**parsed, "product_index": 1}]
        else:
            log.warning(
                "Batch Gemini returned unexpected JSON shape; falling back to individual enrichment. Keys: %s",
                list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__,
            )
            return await _enrich_individually(products, settings, context_snippet)

    enriched_results = []
    for i, p in enumerate(products):
        res = next(
            (
                r for r in results_list
                if isinstance(r, dict) and str(r.get("product_index")) == str(i + 1)
            ),
            None,
        )
        if res is None:
            log.warning(
                "Batch Gemini omitted product_index=%d; falling back to individual enrichment for that product",
                i + 1,
            )
            enriched_results.append(await ai_enrich(p, settings, context_snippet))
            continue
        enriched_results.append(_normalize_enrichment(res, p, "gemini-batch"))

    return enriched_results
