"""
Instagram posting via the official Meta Graph API.

Flow for single-image post:
  1. POST /{ig_user_id}/media   → create media container (image_url + caption)
  2. POST /{ig_user_id}/media_publish → publish the container

Flow for carousel post (2–10 images):
  1. POST /{ig_user_id}/media (is_carousel_item=true) × N → create item containers
  2. POST /{ig_user_id}/media (media_type=CAROUSEL, children=...) → create album container
  3. POST /{ig_user_id}/media_publish → publish the album

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
from urllib.parse import quote

import httpx

from config.runtime import get_config

log = logging.getLogger(__name__)

_BETWEEN_POSTS_DELAY = 30  # seconds between posts in a batch
_MAX_CAROUSEL_IMAGES = 10  # Instagram hard limit for carousel items


def _graph(settings: dict = None) -> str:
    version = str(get_config("META_GRAPH_VERSION", (settings or {}).get("meta_graph_version", "v23.0")) or "v23.0").strip()
    if not version.startswith("v"):
        version = f"v{version}"
    return f"https://graph.facebook.com/{version}"


def backend_mode(settings: dict) -> str:
    """Which Instagram backend is usable: 'private' | 'graph' | 'none'.
    'auto' prefers direct login (no Meta account needed) when its creds exist."""
    import instagram_private
    pref = str((settings or {}).get("instagram_backend") or "auto").strip().lower()
    graph_ok = bool(_token(settings) and str((settings or {}).get("instagram_user_id") or "").strip())
    private_ok = instagram_private.configured(settings or {})
    if pref == "graph":
        return "graph" if graph_ok else ("private" if private_ok else "none")
    if pref == "private":
        return "private" if private_ok else ("graph" if graph_ok else "none")
    return "private" if private_ok else ("graph" if graph_ok else "none")


def _token(settings: dict) -> str:
    raw = str((settings or {}).get("instagram_access_token") or "")
    return "".join(raw.split())


def _public_base_url(settings: dict) -> str:
    raw = (
        (settings or {}).get("public_base_url")
        or get_config("PUBLIC_BASE_URL", "")
        or get_config("APP_URL", "")
        or get_config("RAILWAY_PUBLIC_DOMAIN", "")
    )
    base = str(raw or "").strip().rstrip("/")
    if base and not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    return base


def _publishable_image_url(image_url: str, settings: dict) -> str:
    """
    Return a URL Meta can download, or "" if there is none.
    - Relative URLs (e.g. /api/products/1/cleaned-image on a PC without a public
      address) can only be published when a public base URL is configured.
    - Absolute URLs are proxied through our server when a public base exists
      (supplier CDNs sometimes block Meta), otherwise used as-is.
    """
    image_url = (image_url or "").strip()
    base = _public_base_url(settings)
    if image_url.startswith("/"):
        return f"{base}{image_url}" if base else ""
    if not image_url.startswith(("http://", "https://")):
        return ""
    if not base:
        return image_url
    # Already hosted on our server — serve directly, no extra proxy layer
    if image_url.startswith(base + "/"):
        return image_url
    # Supabase / other permanent public hosts don't need the proxy
    if ".supabase.co/" in image_url:
        return image_url
    return f"{base}/api/image?url={quote(image_url, safe='')}"


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
    settings: dict,
) -> str:
    """Step 1: create a single-image media container. Returns creation_id."""
    resp = await client.post(
        f"{_graph(settings)}/{ig_user_id}/media",
        params={
            "image_url":    image_url,
            "caption":      caption,
            "access_token": token,
        },
    )
    body = resp.json()
    if "error" in body:
        err = body["error"]
        log.error("Instagram container error: code=%s subcode=%s msg=%s",
                  err.get("code"), err.get("error_subcode"), err.get("message"))
        raise RuntimeError(err.get("message", str(err)))
    return body["id"]


async def _create_carousel_item_container(
    client: httpx.AsyncClient,
    ig_user_id: str,
    token: str,
    image_url: str,
    settings: dict,
) -> Optional[str]:
    """Create a single carousel item container. Returns container_id or None on failure."""
    resp = await client.post(
        f"{_graph(settings)}/{ig_user_id}/media",
        params={
            "image_url":        image_url,
            "is_carousel_item": "true",
            "access_token":     token,
        },
    )
    body = resp.json()
    if "error" in body:
        log.warning(
            "Carousel item creation failed for %s: %s",
            image_url[:60],
            body["error"].get("message", body["error"]),
        )
        return None
    return body.get("id")


async def _create_carousel_album(
    client: httpx.AsyncClient,
    ig_user_id: str,
    token: str,
    children: list,
    caption: str,
    settings: dict,
) -> str:
    """Create a CAROUSEL (album) container referencing child containers. Returns creation_id."""
    resp = await client.post(
        f"{_graph(settings)}/{ig_user_id}/media",
        params={
            "media_type":   "CAROUSEL",
            "children":     ",".join(children),
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
    settings: dict,
) -> str:
    """Step 2: publish the container. Returns the media ID."""
    resp = await client.post(
        f"{_graph(settings)}/{ig_user_id}/media_publish",
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
    settings: dict,
) -> str:
    """Fetch the shortcode so we can build the post URL."""
    resp = await client.get(
        f"{_graph(settings)}/{media_id}",
        params={"fields": "shortcode", "access_token": token},
    )
    body = resp.json()
    return body.get("shortcode", media_id)


async def _wait_until_container_ready(
    client: httpx.AsyncClient,
    creation_id: str,
    token: str,
    settings: dict,
) -> None:
    for _ in range(8):
        resp = await client.get(
            f"{_graph(settings)}/{creation_id}",
            params={"fields": "status_code,status", "access_token": token},
        )
        body = resp.json()
        if "error" in body:
            raise RuntimeError(body["error"].get("message", str(body["error"])))
        status = str(body.get("status_code") or "").upper()
        if status in {"FINISHED", "PUBLISHED"}:
            return
        if status == "ERROR":
            raise RuntimeError(body.get("status") or "Instagram media container failed")
        await asyncio.sleep(3)


# ── Public API ─────────────────────────────────────────────────────────────────

async def post_product(product: dict, settings: dict) -> PostResult:
    pid       = product.get("id", 0)
    token     = _token(settings)
    user_id   = str((settings or {}).get("instagram_user_id") or "").strip()

    caption_text = (product.get("caption") or "").strip()
    hashtags     = product.get("hashtags") or []
    hashtag_str  = " ".join(f"#{t.lstrip('#')}" for t in hashtags if t)
    full_caption = f"{caption_text}\n\n{hashtag_str}".strip()

    # Build publishable image URLs (max carousel limit)
    raw_images   = product.get("images") or []
    image_urls   = [u for u in (_publishable_image_url(img, settings) for img in raw_images if img) if u][:_MAX_CAROUSEL_IMAGES]

    # ── Direct-login backend (no Meta developer account) ──────────────────────
    if backend_mode(settings) == "private":
        import instagram_private
        from config.paths import CLEANED_DIR
        import os as _os
        urls = []
        for img in raw_images:
            img = (img or "").strip()
            if img.startswith(("http://", "https://")):
                urls.append(img)
            elif "/cleaned-image" in img:
                # local cleaned file — the private uploader reads it from disk
                try:
                    _pid = img.split("/products/")[1].split("/")[0]
                    local = _os.path.join(str(CLEANED_DIR), f"cleaned_{_pid}.jpg")
                    if _os.path.exists(local):
                        urls.append("file://" + local)
                except Exception:
                    pass
        if not urls:
            return PostResult(product_id=pid, status="error", error="Product has no usable image")
        res = await instagram_private.post_photos(urls, full_caption, settings)
        if res.get("ok"):
            return PostResult(product_id=pid, status="posted", post_url=res.get("url") or "")
        return PostResult(product_id=pid, status="error", error=res.get("error") or "Direct-login post failed")

    if not token or not user_id:
        log.info("Instagram: no API credentials — simulating post for product %s", pid)
        return PostResult(product_id=pid, status="mock",
                          post_url=f"https://instagram.com/p/mock_{pid}")

    if not image_urls:
        return PostResult(product_id=pid, status="error",
                          error="No publicly reachable image URL — configure Supabase Storage or a public app URL")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if len(image_urls) >= 2:
                # ── Carousel post ──────────────────────────────────────────────
                log.info(
                    "Instagram: creating carousel (%d images) for product %s",
                    len(image_urls), pid,
                )
                children = []
                for img_url in image_urls:
                    cid = await _create_carousel_item_container(
                        client, user_id, token, img_url, settings
                    )
                    if cid:
                        children.append(cid)

                if len(children) < 2:
                    # Not enough valid items — fall back to single image
                    log.warning(
                        "Instagram: too few carousel items succeeded (%d), "
                        "falling back to single image for product %s",
                        len(children), pid,
                    )
                    creation_id = await _create_container(
                        client, user_id, token, image_urls[0], full_caption, settings
                    )
                else:
                    creation_id = await _create_carousel_album(
                        client, user_id, token, children, full_caption, settings
                    )
            else:
                # ── Single image post ──────────────────────────────────────────
                log.info("Instagram: creating media container for product %s", pid)
                creation_id = await _create_container(
                    client, user_id, token, image_urls[0], full_caption, settings
                )

            await _wait_until_container_ready(client, creation_id, token, settings)

            log.info("Instagram: publishing container %s", creation_id)
            media_id = await _publish_container(client, user_id, token, creation_id, settings)

            shortcode = await _get_post_shortcode(client, media_id, token, settings)
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
    token = _token(settings)
    if not token:
        log.warning("Instagram: no access token — cannot reply to comment")
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_graph(settings)}/{comment_id}/replies",
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
    token = _token(settings)
    user_id = str((settings or {}).get("instagram_user_id") or "").strip()
    if not token or not user_id:
        log.warning("Instagram: no credentials — cannot send DM")
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_graph(settings)}/{user_id}/messages",
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
