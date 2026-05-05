"""
Image editing utilities for DropOS.

Currently supports:
  - remove_text(): Remove Chinese (or any) text overlays from product images
    using the Clipdrop remove-text API (https://clipdrop.co/apis/docs/remove-text)

Setup:
  1. Get a free API key at https://clipdrop.co/apis
  2. Add it to Settings → clipdrop_key
  3. Use the "Remove Text" button on any product in the approval queue

Pricing:
  - Free tier: 100 credits (images) per month
  - Pay-as-you-go: ~$0.02 per image after that
  - One-time clean of your best products is essentially free
"""

import logging
from typing import Optional

import httpx

log = logging.getLogger(__name__)

CLIPDROP_REMOVE_TEXT_URL = "https://clipdrop-api.co/remove-text/v1"

_CONTENT_TYPE_TO_EXT = {
    "image/jpeg": "jpg",
    "image/jpg":  "jpg",
    "image/png":  "png",
    "image/webp": "webp",
    "image/gif":  "gif",
}


async def _download_image(url: str) -> Optional[tuple[bytes, str]]:
    """Download image from a URL.

    Returns:
        (bytes, content_type) tuple, or None on failure.
    """
    if not url or not url.startswith(("http://", "https://")):
        log.warning("Invalid image URL: %s", url[:80])
        return None
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://www.1688.com/",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                },
            )
        if resp.status_code != 200:
            log.warning("Image download failed: HTTP %d for %s", resp.status_code, url[:80])
            return None
        ct = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if not ct.startswith("image/"):
            ct = "image/jpeg"
        return resp.content, ct
    except Exception as exc:
        log.warning("Image download error for %s: %s", url[:80], exc)
        return None


async def remove_text(image_url: str, api_key: str) -> Optional[bytes]:
    """Remove text overlays from an image using Clipdrop's remove-text API.

    Useful for cleaning Chinese text/watermarks from 1688 / Taobao product photos
    before posting to Instagram.

    Args:
        image_url: Public URL of the source image.
        api_key:   Clipdrop API key (from https://clipdrop.co/apis).

    Returns:
        Cleaned JPEG/PNG image bytes, or None on any failure.
    """
    if not api_key or not api_key.strip():
        log.warning("Clipdrop: api_key not configured — add clipdrop_key in Settings")
        return None

    img_data = await _download_image(image_url)
    if not img_data:
        return None

    image_bytes, content_type = img_data
    ext = _CONTENT_TYPE_TO_EXT.get(content_type, "jpg")

    log.info(
        "Clipdrop: sending %s image (%d KB) for text removal",
        content_type, len(image_bytes) // 1024,
    )

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                CLIPDROP_REMOVE_TEXT_URL,
                headers={"x-api-key": api_key.strip()},
                files={"image_file": (f"product.{ext}", image_bytes, content_type)},
            )

        if resp.status_code == 200:
            out_bytes = resp.content
            log.info(
                "Clipdrop: text removed ✓  input=%dKB → output=%dKB",
                len(image_bytes) // 1024,
                len(out_bytes) // 1024,
            )
            return out_bytes

        # Friendly error messages for common failures
        if resp.status_code == 401:
            log.warning("Clipdrop: invalid API key (401) — check clipdrop_key in Settings")
        elif resp.status_code == 402:
            log.warning(
                "Clipdrop: quota exhausted (402) — "
                "add more credits at https://clipdrop.co/apis"
            )
        elif resp.status_code == 413:
            log.warning("Clipdrop: image too large (413) — must be under 16 MB")
        else:
            log.warning("Clipdrop: API error %d — %s", resp.status_code, resp.text[:200])

        return None

    except httpx.TimeoutException:
        log.warning("Clipdrop: request timed out — image may be too large or server busy")
        return None
    except Exception as exc:
        log.warning("Clipdrop: unexpected error — %s", exc)
        return None
