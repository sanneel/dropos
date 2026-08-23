"""
Image text removal (Clipdrop) shared by the manual "Clean" button and Autopilot.

clean_product_image() downloads the product's hero image, removes text /
watermarks via Clipdrop, stores the result (Supabase Storage when configured,
else DATA_DIR/cleaned served from /api/products/{id}/cleaned-image), rewrites
the product's image list, and moves it to REVIEWED.
"""

import json
import logging
import os
from typing import Optional

from config.paths import CLEANED_DIR
from database import db
from image_editor import remove_text as clipdrop_remove_text
from models import ProductStage
from services.images import upload_product_image

log = logging.getLogger(__name__)


async def clean_product_image(product: dict, settings: dict) -> dict:
    """
    Returns {"ok": bool, "image_url": str, "public": bool, "error": str|None}.
    Never raises.
    """
    pid = int(product["id"])
    key = str(settings.get("clipdrop_key") or "").strip()
    if not key:
        return {"ok": False, "error": "Clipdrop API key missing", "image_url": "", "public": False}

    images = [img for img in (product.get("images") or []) if img]
    url = images[0] if images else ""
    if not url:
        return {"ok": False, "error": "Product has no image", "image_url": "", "public": False}

    try:
        cleaned = await clipdrop_remove_text(url, key)
    except Exception as exc:
        return {"ok": False, "error": f"Clipdrop error: {exc}", "image_url": "", "public": False}
    if not cleaned:
        return {"ok": False, "error": "Clipdrop returned no image", "image_url": "", "public": False}

    # Keep a local copy so /cleaned-image can serve it
    try:
        with open(os.path.join(str(CLEANED_DIR), f"cleaned_{pid}.jpg"), "wb") as f:
            f.write(cleaned)
    except Exception as exc:
        log.warning("cleaning: could not write local copy for %s: %s", pid, exc)

    supabase_url = await upload_product_image(cleaned, f"cleaned_{pid}")
    original_imgs = [img for img in images if "/api/products/" not in img]

    if supabase_url:
        new_url = supabase_url
        imgs = [new_url] + [img for img in original_imgs if img != url]
    else:
        base = str(settings.get("public_base_url") or "").rstrip("/")
        new_url = f"{base}/api/products/{pid}/cleaned-image" if base else f"/api/products/{pid}/cleaned-image"
        imgs = [new_url, url] + [img for img in original_imgs if img != url]

    await db.update_product_fields(pid, {"images_json": json.dumps(imgs), "has_chinese_text": False, "chinese_text_note": ""})
    await db.set_stage(pid, ProductStage.REVIEWED.value)
    public = bool(supabase_url) or new_url.startswith("http")
    return {"ok": True, "image_url": new_url, "public": public, "error": None}
