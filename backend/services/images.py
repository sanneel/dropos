"""
Image processing pipeline: download → compress → upload to S3.

Resource-safety notes:
  • PIL.Image is opened inside a `with` block so it is always closed,
    even when mode conversion or save raises an exception.
  • aiohttp.ClientSession is opened per-request (one-shot pattern) to
    avoid sharing a session across threads/event loops. This is safe
    because each call is already isolated inside asyncio.to_thread.
    If a long-running shared session is preferred in the future, inject
    it via dependency injection rather than a module-level global.
"""

import asyncio
import boto3
import os
import uuid
import logging
from io import BytesIO
from PIL import Image

import httpx

log = logging.getLogger(__name__)


def _compress(data: bytes) -> bytes:
    """
    Convert raw bytes to an optimised JPEG.
    The `with` block guarantees the Image is closed and its memory released
    whether the conversion succeeds or raises.
    """
    with Image.open(BytesIO(data)) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        out = BytesIO()
        img.save(out, format="JPEG", quality=85, optimize=True)
        return out.getvalue()


def _upload_to_s3(img_bytes: bytes, bucket: str, key: str) -> str:
    """Upload bytes to S3 and return the public URL."""
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=img_bytes,
        ContentType="image/jpeg",
    )
    region = boto3.session.Session().region_name or "us-east-1"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


async def process_image(image_url: str) -> str:
    """
    Asynchronously downloads an image from a scraped URL, compresses it to an
    optimised JPEG (quality 85), and uploads it to an S3 bucket.

    Returns the new S3 URL on success, or the original URL as a safe fallback.
    """
    bucket_name = os.getenv("AWS_S3_BUCKET") or os.getenv("S3_BUCKET_NAME")
    if not bucket_name:
        log.warning("AWS_S3_BUCKET not set — returning original image URL.")
        return image_url

    try:
        # 1. Download — use httpx (already a project dependency; no extra import)
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(
                image_url,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.1688.com/"},
            )
            resp.raise_for_status()
            img_data = resp.content

        # 2. Compress (CPU-bound — run in thread-pool to avoid blocking the loop)
        compressed_data = await asyncio.to_thread(_compress, img_data)

        # 3. Upload to S3 (blocking boto3 call → thread-pool)
        key = f"products/{uuid.uuid4().hex}.jpg"
        s3_url = await asyncio.to_thread(_upload_to_s3, compressed_data, bucket_name, key)

        log.info("Uploaded %s → %s (%dKB)", image_url[:60], s3_url[-40:], len(compressed_data) // 1024)
        return s3_url

    except Exception as e:
        log.error("Failed to process image %s: %s", image_url[:80], e, exc_info=True)
        return image_url  # Graceful fallback: keep original URL
