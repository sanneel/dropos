"""
Background workers for the DropOS Operations Engine.

Two independent loops run concurrently via asyncio.create_task():
  • run_worker_loop        — Vision AI curation + Deep Enrichment (SCRAPED → ENRICHED)
  • process_queued_items   — Instagram publishing (QUEUED → LIVE)

"Blast Shield" pattern: the outermost try/except in each loop catches ALL
unexpected exceptions. On failure the loop logs the error and sleeps for
_ERROR_SLEEP seconds before retrying, so a single bad product or a transient
API outage can never permanently kill the background process.
"""

import asyncio
import logging
import json
from .database import db
from .main import ProductStage
from .services.enrichment import enrich_product
from .services.images import process_image
from .services.publisher import publish_to_instagram

log = logging.getLogger(__name__)

# How long to pause after an unexpected crash before retrying
_ERROR_SLEEP = 60
# Batch size for Vision AI collage; must match collage.py COLS*ROWS (2×3 = 6)
_BATCH_SIZE = 6


async def run_worker_loop():
    """
    Continuously processes SCRAPED products in batches of 6.

    Pipeline per batch:
      1. Batch Vision AI via Gemini collage (The Curator)
      2. Deep text enrichment for winners (gpt-4o-mini caption)
      3. Image S3 upload for winners
      4. DB update → ENRICHED  (winners)  / REJECTED  (losers)
    """
    log.info("Started autonomous worker loop (Batch Vision + Deep Enrichment).")

    while True:
        try:
            # ── Poll for SCRAPED products ──────────────────────────────────────
            products = await db.get_products(
                stage=ProductStage.SCRAPED.value,
                limit=_BATCH_SIZE,
                sort="created",
            )

            if not products:
                await asyncio.sleep(10)
                continue

            settings = await db.get_settings()
            log.info("Worker: Running Batch Vision AI for %d products...", len(products))

            # Late import avoids circular-dependency at module load time
            from .enrichment import ai_enrich_batch
            batch_results = await ai_enrich_batch(products, settings)

            for i, p in enumerate(products):
                pid = p["id"]

                # Guard against a truncated response from the AI
                if i >= len(batch_results):
                    log.warning("Worker: Missing AI result for product %d, rejecting.", pid)
                    await db.update_product_fields(pid, {
                        "stage": "REJECTED",
                        "rejection_reason": "Curator: No AI result returned",
                    })
                    continue

                res = batch_results[i]

                if not res.get("store_match"):
                    # ── Curator rejection ──────────────────────────────────────
                    reason = res.get("rejection_reason", "Low visual appeal")
                    await db.update_product_fields(pid, {
                        "stage": "REJECTED",
                        "rejection_reason": f"Curator: {reason}",
                    })
                    log.info("Worker: [REJECT] pid=%d — %s", pid, reason[:80])
                    continue

                # ── Winner: Deep Enrichment + S3 Upload ────────────────────────
                log.info("Worker: [WINNER] Deep Enrichment for pid=%d...", pid)
                title = p.get("title_translated") or p.get("product_name") or p.get("title") or ""
                description = p.get("description_translated") or p.get("description") or ""

                # a. English caption via OpenAI (gpt-4o-mini)
                try:
                    enriched_data = await enrich_product(title, description)
                except Exception as e:
                    log.error("Worker: Text enrichment failed for pid=%d: %s", pid, e)
                    # Graceful degradation — use raw title rather than blocking
                    enriched_data = {"caption": f"{title}\n\n{description}", "hashtags": []}

                # b. Download + compress + upload to S3
                images = p.get("images", [])
                image_url = images[0] if images else p.get("image_url")
                new_image_url = None

                if image_url:
                    try:
                        new_image_url = await process_image(image_url)
                    except Exception as e:
                        log.error("Worker: Image processing failed for pid=%d: %s", pid, e)
                        new_image_url = image_url  # Keep original as fallback

                # c. Persist everything in a single DB update
                updates = {
                    "caption": enriched_data.get("caption", ""),
                    "hashtags_json": json.dumps(enriched_data.get("hashtags", [])),
                    "product_name": res.get("product_name", p.get("product_name", "")),
                    "stage": ProductStage.ENRICHED.value,
                }

                if new_image_url and images:
                    try:
                        images[0] = new_image_url
                        updates["images_json"] = json.dumps(images)
                    except Exception as e:
                        log.warning("Worker: Failed to update images array for pid=%d: %s", pid, e)

                await db.update_product_fields(pid, updates)
                log.info("Worker: pid=%d → ENRICHED.", pid)

            # Brief pause before the next batch — yields to the event loop
            await asyncio.sleep(2)

        except asyncio.CancelledError:
            # Graceful shutdown requested (e.g. app restart)
            log.info("Autonomous worker loop cancelled.")
            break
        except Exception as e:
            # ── Blast Shield ───────────────────────────────────────────────────
            # Any unexpected error (DB timeout, corrupted image, AI outage, etc.)
            # is caught here. We log it, sleep, then continue so the loop is
            # permanently resilient and never requires manual intervention.
            log.error("Critical Worker Error (will retry in %ds): %s", _ERROR_SLEEP, e, exc_info=True)
            await asyncio.sleep(_ERROR_SLEEP)


async def process_queued_items():
    """
    Continuously publishes QUEUED products to Instagram.
    Polls every 60 seconds when idle, 5 seconds when actively draining the queue.
    """
    log.info("Started queued items publisher loop.")

    while True:
        try:
            products = await db.get_products(
                stage=ProductStage.QUEUED.value,
                limit=5,
                sort="created",
            )

            for p in products:
                pid = p["id"]

                # Resolve the best available image URL
                images = p.get("images") or []
                image_url = images[0] if images else p.get("image_url", "")

                # Build the full caption: AI text + hashtags
                caption = p.get("caption", "")
                hashtags = p.get("hashtags", [])
                if hashtags:
                    caption += "\n\n" + " ".join(hashtags)

                log.info("Publisher: Publishing pid=%d...", pid)
                try:
                    await publish_to_instagram(image_url, caption)
                    await db.set_stage(pid, ProductStage.LIVE.value)
                    log.info("Publisher: pid=%d → LIVE.", pid)
                except Exception as e:
                    # Log but do NOT re-raise — we still want to attempt the
                    # remaining products in the batch and keep the loop alive.
                    log.error("Publisher: Failed to publish pid=%d: %s", pid, e)

            idle = not products
            await asyncio.sleep(60 if idle else 5)

        except asyncio.CancelledError:
            log.info("Publisher loop cancelled.")
            break
        except Exception as e:
            # ── Blast Shield ───────────────────────────────────────────────────
            log.error("Critical Publisher Error (will retry in %ds): %s", _ERROR_SLEEP, e, exc_info=True)
            await asyncio.sleep(_ERROR_SLEEP)
