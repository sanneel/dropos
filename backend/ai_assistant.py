"""
AI Chat Assistant for DropOS backoffice.

Lets the store owner chat with the AI to:
- Review rejected products and find wrongly-rejected gems
- Get pipeline summaries
- Bulk-reconsider products that match criteria
- Ask questions about the store
"""

import json
import logging
import re
from typing import Optional

import httpx

from config.runtime import get_config

log = logging.getLogger(__name__)

_SYSTEM = """You are the smart backoffice assistant for DropOS — a premium couple gift Instagram shop called "წყვილი" (Couple).

You help the store owner manage their product pipeline efficiently. The shop targets Gen-Z couples (18-35) with luxury-aesthetic couple gifts: matching jewellery, personalised accessories, romantic experiences.

You have access to current store stats and product samples provided in the context.

YOU CAN DO:
1. Scan rejected products and identify any that were wrongly rejected (good products that scored just below threshold or had fixable issues like Chinese text)
2. Summarise pipeline performance and trends
3. Recommend which keywords to add/remove based on results
4. Answer questions about the store and products
5. Suggest products to reconsider (you return their IDs)

WHEN REVIEWING REJECTED PRODUCTS look for:
- score >= 7.0 OR niche_fit >= 7.5 (borderline rejections worth reconsidering)
- Products with "Chinese text" as rejection reason (fixable with Clipdrop)
- Premium categories: Jewelry, Accessories, Phone Cases, Stationery
- Products with high orders (>500) that were rejected — proven demand
- Unique/unusual items that fit couple aesthetic despite borderline score

RESPONSE FORMAT — always respond with this exact JSON structure:
{
  "reply": "Your helpful response in clear English. Be concise and actionable.",
  "action": null,
  "product_ids": [],
  "suggestion": null
}

- "action" can be: null, "reconsider", "show_products"
- "product_ids": list of product IDs to act on (reconsider or highlight)
- "suggestion": optional short one-line suggestion for the user
"""


async def chat(message: str, context: dict, settings: dict) -> dict:
    """Process a user chat message with store context."""

    stats = context.get("stats", {})
    rejected_sample = context.get("rejected_sample", [])
    recent_rejection_reasons = context.get("recent_rejection_reasons", [])
    last_job = context.get("last_job", {})

    # Build a compact context block
    context_block = f"""=== STORE STATS ===
Pending review: {stats.get('pending', 0)}
Approved: {stats.get('approved', 0)}
Posted: {stats.get('posted', 0)}
Rejected: {stats.get('rejected', 0)}

=== LAST SCAN ===
{json.dumps(last_job, ensure_ascii=False) if last_job else 'No scans yet'}

=== TOP REJECTION REASONS (recent) ===
{json.dumps(recent_rejection_reasons, ensure_ascii=False)}

=== REJECTED PRODUCTS SAMPLE (for review) ===
{json.dumps(rejected_sample, ensure_ascii=False)}
"""

    user_msg = f"{context_block}\n\n=== USER MESSAGE ===\n{message}"

    # Try Gemini first (better reasoning)
    result = await _gemini_chat(user_msg, settings)
    if result:
        return result

    # Fallback to Groq (free, text-only)
    result = await _groq_chat(user_msg, settings)
    if result:
        return result

    return {
        "reply": "AI services are unavailable right now. Please check your Gemini or Groq API key in Settings.",
        "action": None,
        "product_ids": [],
        "suggestion": "Configure gemini_key in Settings for best results.",
    }


async def _gemini_chat(message: str, settings: dict) -> Optional[dict]:
    api_key = get_config("GEMINI_KEY", settings.get("gemini_key", ""))
    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent",
                headers={"x-goog-api-key": api_key, "content-type": "application/json"},
                json={
                    "system_instruction": {"parts": [{"text": _SYSTEM}]},
                    "contents": [{"parts": [{"text": message}]}],
                    "generationConfig": {
                        "response_mime_type": "application/json",
                        "max_output_tokens": 1000,
                        "temperature": 0.3,
                    },
                },
            )
        if resp.status_code != 200:
            log.warning("Gemini chat %d: %s", resp.status_code, resp.text[:200])
            return None
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"```json|```", "", text).strip()
        return json.loads(text)
    except Exception as e:
        log.warning("Gemini chat error: %s", e)
        return None


async def _groq_chat(message: str, settings: dict) -> Optional[dict]:
    api_key = get_config("GROQ_KEY", settings.get("groq_key", ""))
    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": message},
                    ],
                    "max_tokens": 1000,
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                },
            )
        if resp.status_code != 200:
            log.warning("Groq chat %d: %s", resp.status_code, resp.text[:200])
            return None
        text = resp.json()["choices"][0]["message"]["content"]
        text = re.sub(r"```json|```", "", text).strip()
        return json.loads(text)
    except Exception as e:
        log.warning("Groq chat error: %s", e)
        return None
