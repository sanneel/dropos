"""
Content AI — the second model next to Gemini.

Gemini stays the *eyes* (vision scoring in enrichment.py). This module is the
*writer*: Instagram captions at posting time, keyword generation, and the
assistant can all run on a stronger text model.

Provider is chosen in Settings (`content_provider`):
    auto    → first configured of: claude → openai → gemini → groq
    claude  → Anthropic Claude (official SDK), model `anthropic_model`
    openai  → OpenAI chat completions, model `openai_model`
    gemini  → Gemini text call, model `gemini_model`
    groq    → Groq Llama, fixed model

Every entry point returns parsed JSON (dict/list) or None — callers always have
a non-AI fallback, so a provider outage degrades quality, never availability.
"""

import asyncio
import json
import logging
import re
from typing import Any, Optional

import httpx

from config.runtime import get_config

log = logging.getLogger(__name__)

DEFAULT_CLAUDE_MODEL = "claude-opus-5"
DEFAULT_OPENAI_MODEL = "gpt-5-mini"
_GROQ_MODEL = "llama-3.3-70b-versatile"

_PROVIDERS = ("claude", "openai", "gemini", "groq")


# ── Key / provider resolution ─────────────────────────────────────────────────

def _key(settings: dict, name: str) -> str:
    env = {"claude": "ANTHROPIC_KEY", "openai": "OPENAI_KEY", "gemini": "GEMINI_KEY", "groq": "GROQ_KEY"}[name]
    field = {"claude": "anthropic_key", "openai": "openai_key", "gemini": "gemini_key", "groq": "groq_key"}[name]
    return str(get_config(env, settings.get(field, "")) or "").strip()


def configured_providers(settings: dict) -> list:
    return [p for p in _PROVIDERS if _key(settings, p)]


def pick_provider(settings: dict) -> Optional[str]:
    pref = str(settings.get("content_provider") or "auto").strip().lower()
    if pref in _PROVIDERS and _key(settings, pref):
        return pref
    for p in _PROVIDERS:  # auto (or preferred provider missing its key)
        if _key(settings, p):
            return p
    return None


def content_ready(settings: dict) -> bool:
    return pick_provider(settings) is not None


def provider_label(settings: dict) -> str:
    p = pick_provider(settings)
    if not p:
        return "none"
    model = {"claude": settings.get("anthropic_model") or DEFAULT_CLAUDE_MODEL,
             "openai": settings.get("openai_model") or DEFAULT_OPENAI_MODEL,
             "gemini": settings.get("gemini_model") or "gemini-2.5-flash-lite",
             "groq": _GROQ_MODEL}[p]
    return f"{p} ({model})"


def _parse_json(text: str) -> Any:
    text = re.sub(r"```json|```", "", str(text or "")).strip()
    return json.loads(text)


_DASH_CHARS = "‐‑‒–—―−"  # ‐ ‑ ‒ – — ― −


def strip_dashes(text: str) -> str:
    """Hard no-dash rule for customer-facing copy: models are told not to use
    dashes, but this guarantees it even when they slip."""
    text = str(text or "")
    # em/en/unicode dashes → comma-space (mid-sentence pause) or nothing at line edges
    text = re.sub(rf"\s*[{_DASH_CHARS}]+\s*", ", ", text)
    # plain hyphen used as punctuation (surrounded by spaces or starting a line)
    text = re.sub(r"(^|\n)\s*-\s+", r"\1", text)
    text = re.sub(r"\s+-\s+", ", ", text)
    # tidy up artifacts: ", ," / trailing ", " before a newline or end
    text = re.sub(r"(,\s*)+,", ",", text)
    text = re.sub(r",\s*(\n|$)", r"\1", text)
    return text.strip()


# ── Claude (official Anthropic SDK) ───────────────────────────────────────────

async def _claude_json(system: str, prompt: str, settings: dict, max_tokens: int) -> Any:
    import anthropic
    api_key = _key(settings, "claude")
    model = str(settings.get("anthropic_model") or DEFAULT_CLAUDE_MODEL).strip()
    client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=2, timeout=60.0)
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system + "\n\nRespond with ONLY valid JSON — no markdown fences, no prose.",
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        try:
            # Server-side refusal fallbacks (recommended default for Opus 5 / Fable 5):
            # on a policy decline the API transparently re-runs on a fallback model.
            response = await client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        except anthropic.BadRequestError:
            # Model/platform without fallback support — plain call
            response = await client.messages.create(**kwargs)
        if response.stop_reason == "refusal":
            log.warning("Claude declined the content request (category=%s)",
                        getattr(getattr(response, "stop_details", None), "category", None))
            return None
        text = next((b.text for b in response.content if b.type == "text"), "")
        return _parse_json(text)
    except anthropic.AuthenticationError:
        log.warning("Claude: invalid API key")
        return None
    except anthropic.RateLimitError:
        log.warning("Claude: rate limited")
        return None
    except anthropic.APIStatusError as exc:
        log.warning("Claude API %s: %s", exc.status_code, getattr(exc, "message", exc))
        return None
    except anthropic.APIConnectionError as exc:
        log.warning("Claude connection error: %s", exc)
        return None
    except (json.JSONDecodeError, StopIteration) as exc:
        log.warning("Claude returned unparseable JSON: %s", exc)
        return None
    finally:
        await client.close()


# ── OpenAI ────────────────────────────────────────────────────────────────────

async def _openai_json(system: str, prompt: str, settings: dict, max_tokens: int) -> Any:
    api_key = _key(settings, "openai")
    model = str(settings.get("openai_model") or DEFAULT_OPENAI_MODEL).strip()
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system + "\nRespond with ONLY valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_completion_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                },
            )
        if resp.status_code != 200:
            log.warning("OpenAI API %d: %s", resp.status_code, resp.text[:200])
            return None
        return _parse_json(resp.json()["choices"][0]["message"]["content"])
    except Exception as exc:
        log.warning("OpenAI content call failed: %s", exc)
        return None


# ── Gemini (text-only, same key as the scorer) ───────────────────────────────

async def _gemini_json(system: str, prompt: str, settings: dict, max_tokens: int) -> Any:
    api_key = _key(settings, "gemini")
    from enrichment import _gemini_model
    model = _gemini_model(settings)
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": api_key, "content-type": "application/json"},
                json={
                    "system_instruction": {"parts": [{"text": system}]},
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"response_mime_type": "application/json", "max_output_tokens": max_tokens, "temperature": 0.7},
                },
            )
        if resp.status_code != 200:
            log.warning("Gemini content call %d: %s", resp.status_code, resp.text[:200])
            return None
        return _parse_json(resp.json()["candidates"][0]["content"]["parts"][0]["text"])
    except Exception as exc:
        log.warning("Gemini content call failed: %s", exc)
        return None


# ── Groq ──────────────────────────────────────────────────────────────────────

async def _groq_json(system: str, prompt: str, settings: dict, max_tokens: int) -> Any:
    api_key = _key(settings, "groq")
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": _GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": system + "\nRespond with ONLY valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                },
            )
        if resp.status_code != 200:
            log.warning("Groq content call %d: %s", resp.status_code, resp.text[:200])
            return None
        return _parse_json(resp.json()["choices"][0]["message"]["content"])
    except Exception as exc:
        log.warning("Groq content call failed: %s", exc)
        return None


_CALLERS = {"claude": _claude_json, "openai": _openai_json, "gemini": _gemini_json, "groq": _groq_json}


# ── Public: provider-routed JSON completion ───────────────────────────────────

async def complete_json(system: str, prompt: str, settings: dict, max_tokens: int = 1500) -> Any:
    """
    Run the prompt on the configured content provider; on failure walk the rest
    of the chain (auto order). Returns parsed JSON or None.
    """
    first = pick_provider(settings)
    if not first:
        return None
    chain = [first] + [p for p in _PROVIDERS if p != first and _key(settings, p)]
    for provider in chain:
        result = await _CALLERS[provider](system, prompt, settings, max_tokens)
        if result is not None:
            if provider != first:
                log.info("content_ai: %s failed, served by %s", first, provider)
            return result
    return None


# ── Caption writing (the "work about content" part) ───────────────────────────

_CAPTION_SYSTEM = """You are the Instagram content writer for {store}, a {niche} shop.
Audience: {audience}. All customer-facing text is GEORGIAN (ka).

Write captions that sell without sounding like ads:
1. HOOK — the first line must stop the scroll: a feeling, a "tag your person"
   moment, or a specific little scene. Never start with the product name or "Buy".
2. DESIRE — 1–2 short sentences. Concrete and specific beats vague ("every time
   they touch the lamp, yours lights up" — not "a wonderful romantic gift").
   Use the customer's own language, not marketing words.
3. CTA — how to order: DM with the word "მინდა", mention the price ₾{price}.
Style: warm, playful, like texting a friend; 2–4 fitting emojis; short lines;
total under 500 characters; NO hashtags inside the caption text.
NEVER use dash characters of any kind — no hyphens, en dashes or em dashes
(-, –, —) anywhere in the caption. Rephrase with a comma, a period or a new
line instead. This is a hard rule.

Return ONLY JSON:
{{"caption": "the Georgian caption with \\n line breaks",
  "hashtags": ["10-14 tags, mixed Georgian and English, WITHOUT the # sign"],
  "hook": "the first line you used"}}"""


async def generate_caption(product: dict, settings: dict, brand: dict | None = None) -> Optional[dict]:
    """Fresh caption + hashtags for one product. Returns dict or None."""
    brand = brand or {}
    system = _CAPTION_SYSTEM.format(
        store=brand.get("name") or settings.get("store_name") or "Tskvili",
        niche=brand.get("niche") or settings.get("niche") or "romantic gift",
        audience=brand.get("target_audience") or settings.get("target_audience") or "Gen-Z couples in Georgia",
        price=product.get("sell_price_eur") or "?",
    )
    prompt = json.dumps({
        "product_name": product.get("product_name") or "",
        "title": product.get("title_translated") or product.get("title") or "",
        "category": product.get("category") or "",
        "price_gel": product.get("sell_price_eur"),
        "ai_notes": {"emotional_hook": product.get("emotional_hook") or "", "viral_angle": product.get("viral_angle") or ""},
        "current_caption": (product.get("caption") or "")[:300],
    }, ensure_ascii=False)
    result = await complete_json(system, prompt, settings, max_tokens=1200)
    if not isinstance(result, dict) or not str(result.get("caption") or "").strip():
        return None
    hashtags = [re.sub(r"^#", "", str(h)).strip() for h in (result.get("hashtags") or []) if str(h).strip()][:15]
    return {"caption": strip_dashes(result["caption"]), "hashtags": hashtags, "hook": strip_dashes(result.get("hook") or "")}


async def maybe_rewrite_caption(db, product: dict, settings: dict) -> dict:
    """
    Called right before posting. When the content model is configured and
    rewriting is on, replace the scoring-time caption with a purpose-written one
    and persist it. Always returns the (possibly updated) product dict.
    """
    if not settings.get("content_rewrite_enabled", True) or not content_ready(settings):
        return product
    try:
        brand = await db.get_brand(product.get("brand_id")) if product.get("brand_id") else None
        result = await generate_caption(product, settings, brand)
        if result:
            product["caption"] = result["caption"]
            if result["hashtags"]:
                product["hashtags"] = result["hashtags"]
            await db.update_product_fields(product["id"], {
                "caption": result["caption"],
                **({"hashtags_json": json.dumps(result["hashtags"])} if result["hashtags"] else {}),
            })
            log.info("content_ai: rewrote caption for product %s via %s", product.get("id"), provider_label(settings))
    except Exception as exc:
        log.warning("content_ai: caption rewrite failed for %s: %s — posting the original", product.get("id"), exc)
    return product


# ── Connection test (Settings → Test buttons) ─────────────────────────────────

async def test_provider(provider: str, key: Optional[str], settings: dict) -> dict:
    import time as _time
    s = dict(settings)
    if key:
        s[{"claude": "anthropic_key", "openai": "openai_key"}.get(provider, f"{provider}_key")] = key
    if provider not in _CALLERS:
        return {"ok": False, "error": f"Unknown provider '{provider}'"}
    if not _key(s, provider):
        return {"ok": False, "error": "No API key configured"}
    start = _time.time()
    result = await _CALLERS[provider]("You are a health check.", 'Return {"ok": true}', s, 200)
    latency = int((_time.time() - start) * 1000)
    model = {"claude": s.get("anthropic_model") or DEFAULT_CLAUDE_MODEL,
             "openai": s.get("openai_model") or DEFAULT_OPENAI_MODEL}.get(provider, provider)
    if isinstance(result, dict):
        return {"ok": True, "model": model, "latency_ms": latency}
    return {"ok": False, "error": "No valid response — check the key and model name", "model": model, "latency_ms": latency}
