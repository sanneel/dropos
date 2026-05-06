"""
Image processing pipeline: download → compress → upload to Supabase Storage.

Supabase Storage is the primary backend (configured via SUPABASE_URL +
SUPABASE_SERVICE_ROLE_KEY).  If those env vars are absent the module falls
back to returning the original source URL so the rest of the pipeline keeps
working even in a bare local dev environment.

Memory-safety: PIL.Image is always opened inside a `with` block so it is
closed — and its pixel buffer freed — whether the call succeeds or raises.
"""

import asyncio
import os
import logging
from io import BytesIO

import httpx
from PIL import Image

log = logging.getLogger(__name__)

# ── Supabase client (initialised lazily so import never crashes) ────────────────
_supabase_client = None

def _get_supabase():
    """Return a cached Supabase client, or None if env vars are missing."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    if not url or not key:
        return None

    try:
        from supabase import create_client
        _supabase_client = create_client(url, key)
        log.info("Supabase client initialised (url=%s…)", url[:30])
    except Exception as exc:
        log.error("Failed to initialise Supabase client: %s", exc)
        _supabase_client = None

    return _supabase_client


# ── Compression (CPU-bound, run in a thread-pool) ───────────────────────────────

def _compress(data: bytes) -> bytes:
    """
    Decode raw bytes and re-encode as an optimised JPEG.
    The `with` block guarantees the Image object is always closed.
    """
    with Image.open(BytesIO(data)) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        return buf.getvalue()


# ── Supabase upload (blocking SDK → thread-pool) ────────────────────────────────

_BUCKET = "product-images"

def _upload_to_supabase(img_bytes: bytes, source_id: str) -> str:
    """
    Upload compressed JPEG bytes to Supabase Storage.
    Returns the public URL of the uploaded file.
    Raises on failure so the caller can fall back to the original URL.
    """
    client = _get_supabase()
    if client is None:
        raise RuntimeError("Supabase client not available (check env vars)")

    filename = f"{source_id}.jpg"
    path = f"products/{filename}"

    # upsert=True means re-uploading the same source_id simply overwrites the
    # previous file instead of raising a "already exists" error.
    client.storage.from_(_BUCKET).upload(
        path=path,
        file=img_bytes,
        file_options={"content-type": "image/jpeg", "upsert": "true"},
    )

    public_url = client.storage.from_(_BUCKET).get_public_url(path)
    return public_url


# ── Public entry point ──────────────────────────────────────────────────────────

async def upload_product_image(image_bytes: bytes, source_id: str) -> str | None:
    """
    Compress *image_bytes* and upload to Supabase Storage.
    Returns the public URL on success, or None on failure.
    """
    try:
        compressed = await asyncio.to_thread(_compress, image_bytes)
        url = await asyncio.to_thread(_upload_to_supabase, compressed, source_id)
        log.info("Supabase upload OK  source_id=%s  url=…%s", source_id, url[-40:])
        return url
    except Exception as exc:
        log.error("Supabase upload FAILED  source_id=%s  error=%s", source_id, exc)
        return None


async def process_image(image_url: str, source_id: str = "") -> str:
    """
    Download *image_url*, compress it, and upload to Supabase Storage.

    Falls back to the original URL if:
      • Supabase env vars are missing
      • The download fails
      • The upload fails

    This ensures the pipeline always has *some* image URL and can continue.
    """
    # Fast-path: if Supabase is not configured, skip silently
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        log.debug("Supabase not configured — skipping image upload for %s", image_url[:60])
        return image_url

    # 1. Download
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(
                image_url,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.1688.com/"},
            )
            resp.raise_for_status()
            img_data = resp.content
    except Exception as exc:
        log.error("Image download FAILED  url=%s  error=%s", image_url[:80], exc)
        return image_url  # Graceful fallback

    # 2. Compress + Upload
    # Use source_id for the filename so repeated ingestion of the same product
    # overwrites the existing file rather than creating duplicates.
    effective_id = source_id or image_url[-32:].replace("/", "_")
    public_url = await upload_product_image(img_data, effective_id)

    if public_url:
        return public_url

    # 3. Fallback: keep original URL so the post can still go live
    log.warning("Falling back to original URL for source_id=%s", source_id)
    return image_url
