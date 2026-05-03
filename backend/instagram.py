"""
Instagram posting via the official Meta Graph API.

Flow per post:
  1. POST /{ig_user_id}/media   → create media container (image_url + caption)
  2. POST /{ig_user_id}/media_publish → publish the container

Requirements:
  - Instagram Business or Creator account
  - Facebook Page linked to that account
  - Developer App with instagram_content_publish + instagram_basic permissions
  - Long-lived Page Access Token (never expires if refreshed; ~60 days otherwise)
  - Publicly reachable image URL (CDN images from 1688/CSSBuy work fine)

Falls back to mock mode when token/user_id are not configured.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_GRAPH = "https://graph.facebook.com/v21.0"
_BETWEEN_POSTS_DELAY = 30  # seconds between posts in a batch


@dataclass
class PostResult:
    product_id: int
    status: str          # "posted" | "error" | "mock"
    post_url: Optional[str] = None
    error: Optional[str] = None


# ── Core API calls ─────────────────────────────────────────────────────────────

async def _create_container(
    client: httpx.AsyncClient,
    ig_user_id: str,
    token: str,
    image_url: str,
    caption: str,
) -> str:
    """Step 1: create a media container. Returns creation_id."""
    resp = await client.post(
        f"{_GRAPH}/{ig_user_id}/media",
        params={
            "image_url":    image_url,
            "caption":      caption,
            "access_token": token,
        },
    )
    body = resp.json()
    if "error" in body:
        raise RuntimeError(body["error"].get("message", str(body["error"])))
    return body["id"]


async def _publish_container(
    client: httpx.AsyncClient,
    ig_user_id: str,
    token: str,
    creation_id: str,
) -> str:
    """Step 2: publish the container. Returns the media ID."""
    resp = await client.post(
        f"{_GRAPH}/{ig_user_id}/media_publish",
        params={
            "creation_id":  creation_id,
            "access_token": token,
        },
    )
    body = resp.json()
    if "error" in body:
        raise RuntimeError(body["error"].get("message", str(body["error"])))
    return body["id"]


async def _get_post_shortcode(
    client: httpx.AsyncClient,
    media_id: str,
    token: str,
) -> str:
    """Fetch the shortcode so we can build the post URL."""
    resp = await client.get(
        f"{_GRAPH}/{media_id}",
        params={"fields": "shortcode", "access_token": token},
    )
    body = resp.json()
    return body.get("shortcode", media_id)


# ── Public API ─────────────────────────────────────────────────────────────────

async def post_product(product: dict, settings: dict) -> PostResult:
    pid       = product.get("id", 0)
    token     = str(settings.get("instagram_access_token") or "").strip()
    user_id   = str(settings.get("instagram_user_id")      or "").strip()

    caption_text = (product.get("caption") or "").strip()
    hashtags     = product.get("hashtags") or []
    hashtag_str  = " ".join(f"#{t}" for t in hashtags if t)
    full_caption = f"{caption_text}\n\n{hashtag_str}".strip()

    image_url = (product.get("images") or [""])[0]

    if not token or not user_id:
        log.info("Instagram: no API credentials — simulating post for product %s", pid)
        return PostResult(product_id=pid, status="mock",
                          post_url=f"https://instagram.com/p/mock_{pid}")

    if not image_url:
        return PostResult(product_id=pid, status="error",
                          error="Product has no image URL")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            log.info("Instagram: creating media container for product %s", pid)
            creation_id = await _create_container(
                client, user_id, token, image_url, full_caption
            )

            log.info("Instagram: publishing container %s", creation_id)
            media_id = await _publish_container(client, user_id, token, creation_id)

            shortcode = await _get_post_shortcode(client, media_id, token)
            post_url  = f"https://www.instagram.com/p/{shortcode}/"

        log.info(
            "Instagram posted: product=%s name=%r → %s",
            pid, product.get("product_name", "?")[:40], post_url,
        )
        return PostResult(product_id=pid, status="posted", post_url=post_url)

    except Exception as exc:
        log.error("Instagram post failed for product %s: %s", pid, exc)
        return PostResult(product_id=pid, status="error", error=str(exc))


async def reply_to_comment(comment_id: str, message: str, settings: dict) -> bool:
    """Reply to an Instagram comment via Graph API. Returns True on success."""
    token = str(settings.get("instagram_access_token") or "").strip()
    if not token:
        log.warning("Instagram: no access token — cannot reply to comment")
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_GRAPH}/{comment_id}/replies",
                params={"message": message, "access_token": token},
            )
        body = resp.json()
        if "error" in body:
            log.error("Comment reply failed: %s", body["error"].get("message", body))
            return False
        log.info("Replied to comment %s", comment_id)
        return True
    except Exception as exc:
        log.error("Comment reply exception: %s", exc)
        return False


async def reply_to_dm(sender_id: str, message: str, settings: dict) -> bool:
    """Send a DM reply via the Instagram Messaging API."""
    token   = str(settings.get("instagram_access_token") or "").strip()
    user_id = str(settings.get("instagram_user_id")      or "").strip()
    if not token or not user_id:
        log.warning("Instagram: no credentials — cannot send DM")
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_GRAPH}/{user_id}/messages",
                params={"access_token": token},
                json={
                    "recipient": {"id": sender_id},
                    "message":   {"text": message},
                },
            )
        body = resp.json()
        if "error" in body:
            log.error("DM reply failed: %s", body["error"].get("message", body))
            return False
        log.info("Sent DM to %s", sender_id)
        return True
    except Exception as exc:
        log.error("DM reply exception: %s", exc)
        return False


def match_reply_rule(text: str, rules: list) -> Optional[str]:
    """
    Match comment text against keyword rules.
    Returns the reply string for the first matching rule, or None.
    A rule with empty keywords list acts as a catch-all default.
    """
    text_lower = text.lower()
    default_reply: Optional[str] = None

    for rule in rules:
        keywords = rule.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",")]
        reply = rule.get("reply", "").strip()
        if not reply:
            continue
        if not keywords:
            default_reply = reply  # catch-all, keep checking for specific match
            continue
        if any(kw.strip().lower() in text_lower for kw in keywords if kw.strip()):
            return reply

    return default_reply


async def post_batch(products: list, settings: dict) -> list[PostResult]:
    """Post products sequentially with a delay to stay under rate limits."""
    results: list[PostResult] = []
    for i, product in enumerate(products):
        result = await post_product(product, settings)
        results.append(result)
        if i < len(products) - 1:
            log.info("Instagram: waiting %ds before next post…", _BETWEEN_POSTS_DELAY)
            await asyncio.sleep(_BETWEEN_POSTS_DELAY)
    return results
