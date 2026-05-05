"""
AI Chat Assistant for DropOS backoffice.

Lets the store owner chat with the AI to:
- Browse, review and edit products in any stage (pending/approved/posted/rejected)
- Approve / reconsider products
- Get pipeline summaries
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

You help the store owner manage their product pipeline. The shop targets Gen-Z couples (18-35) with luxury-aesthetic couple gifts: matching jewellery, personalised accessories, romantic experiences.

You have access to current store stats and product samples provided in the context.

YOU CAN DO:
1. LIST PRODUCTS — show products from any stage (pending/approved/posted/rejected). Return action="list_products", products=[...].
2. EDIT PRODUCTS — suggest title/price/caption edits. Return action="edit_products", edits=[{id, title, price, caption}].
3. APPROVE PRODUCTS — approve pending products. Return action="approve_products", product_ids=[...].
4. RECONSIDER rejected products — move them back to pending. Return action="reconsider", product_ids=[...].
5. PIPELINE SUMMARY — summarise pipeline performance.
6. KEYWORD ADVICE — recommend keywords to add/remove.

WHEN THE USER ASKS TO SEE PRODUCTS:
- Return action="list_products" and include the relevant products from context in the "products" field.
- For approved products, use the approved_sample from context.
- For pending products, use the pending_sample from context.
- For rejected products, use the rejected_sample from context.

WHEN SUGGESTING EDITS:
- Return action="edit_products" with edits=[{id, title, price}] — only include fields that actually need changing.
- Focus on: making titles more premium/romantic, fixing prices to look luxury (e.g. €39.9 → €39.90), improving captions.

WHEN REVIEWING REJECTED PRODUCTS look for:
- score >= 7.0 OR niche_fit >= 7.5 (borderline rejections worth reconsidering)
- Products with "Chinese text" as rejection reason (fixable with Clipdrop)
- Premium categories: Jewelry, Accessories, Phone Cases, Stationery
- Products with high orders (>500) that were rejected — proven demand

RESPONSE FORMAT — always respond with this exact JSON structure:
{
  "reply": "Your helpful response in clear English. Be concise and actionable.",
  "action": null,
  "product_ids": [],
  "products": [],
  "edits": [],
  "suggestion": null
}

- "action": null | "reconsider" | "show_products" | "list_products" | "edit_products" | "approve_products"
- "product_ids": list of product IDs (for reconsider/approve)
- "products": list of product objects (for list_products)
- "edits": list of {id, title, price, caption} objects (for edit_products) — only include fields to change
- "suggestion": optional short one-line suggestion
"""


async def chat(message: str, context: dict, settings: dict) -> dict:
    """Process a user chat message with store context."""

    stats = context.get("stats", {})
    rejected_sample = context.get("rejected_sample", [])
    approved_sample = context.get("approved_sample", [])
    pending_sample = context.get("pending_sample", [])
    recent_rejection_reasons = context.get("recent_rejection_reasons", [])
    last_job = context.get("last_job", {})

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

=== APPROVED PRODUCTS SAMPLE ===
{json.dumps(approved_sample, ensure_ascii=False)}

=== PENDING PRODUCTS SAMPLE ===
{json.dumps(pending_sample, ensure_ascii=False)}
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
        "products": [],
        "edits": [],
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
                        "max_output_tokens": 1500,
                        "temperature": 0.3,
                    },
                },
            )
        if resp.status_code != 200:
            log.warning("Gemini chat %d: %s", resp.status_code, resp.text[:200])
            return None
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"```json|```", "", text).strip()
        data = json.loads(text)
        # Ensure required keys exist
        data.setdefault("products", [])
        data.setdefault("edits", [])
        data.setdefault("product_ids", [])
        return data
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
                    "max_tokens": 1500,
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                },
            )
        if resp.status_code != 200:
            log.warning("Groq chat %d: %s", resp.status_code, resp.text[:200])
            return None
        text = resp.json()["choices"][0]["message"]["content"]
        text = re.sub(r"```json|```", "", text).strip()
        data = json.loads(text)
        data.setdefault("products", [])
        data.setdefault("edits", [])
        data.setdefault("product_ids", [])
        return data
    except Exception as e:
        log.warning("Groq chat error: %s", e)
        return None
