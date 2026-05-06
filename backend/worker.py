import asyncio
import logging
import json
from .database import db
from .main import ProductStage
from .services.enrichment import enrich_product
from .services.images import process_image
from .services.publisher import publish_to_instagram

log = logging.getLogger(__name__)

async def run_worker_loop():
    log.info("Started autonomous worker loop.")
    while True:
        try:
            # Poll for SCRAPED products
            products = await db.get_products(stage=ProductStage.SCRAPED.value, limit=5, sort="created")
            for p in products:
                pid = p["id"]
                title = p.get("title_translated") or p.get("product_name") or p.get("title") or ""
                description = p.get("description_translated") or p.get("description") or ""
                
                # 1. AI Enrichment
                log.info(f"Worker: Enriching product {pid}...")
                try:
                    enriched_data = await enrich_product(title, description)
                except Exception as e:
                    log.error(f"Worker: Enrichment failed for {pid}: {e}")
                    enriched_data = {"caption": f"{title}\n\n{description}", "hashtags": []}
                
                # 2. Image Pipeline (process the first image)
                log.info(f"Worker: Processing images for product {pid}...")
                image_url = p.get("image_url")
                images = p.get("images")
                
                if not image_url and images and isinstance(images, list):
                    image_url = images[0]
                
                new_image_url = None
                if image_url:
                    try:
                        new_image_url = await process_image(image_url)
                    except Exception as e:
                        log.error(f"Worker: Image processing failed for {pid}: {e}")
                        new_image_url = image_url
                
                # 3. Update DB
                updates = {
                    "caption": enriched_data.get("caption", ""),
                    "hashtags_json": json.dumps(enriched_data.get("hashtags", []))
                }
                
                if new_image_url and images and isinstance(images, list):
                    try:
                        images[0] = new_image_url
                        updates["images_json"] = json.dumps(images)
                    except Exception as e:
                        log.warning(f"Worker: Failed to update images array: {e}")

                await db.update_product_fields(pid, updates)
                await db.set_stage(pid, ProductStage.ENRICHED.value)
                log.info(f"Worker: Finished processing product {pid}. Moved to ENRICHED.")
            
            # Wait before polling again
            await asyncio.sleep(10 if not products else 2)
            
        except asyncio.CancelledError:
            log.info("Autonomous worker loop cancelled.")
            break
        except Exception as e:
            log.error(f"Worker loop error: {e}", exc_info=True)
            await asyncio.sleep(10)

async def process_queued_items():
    log.info("Started queued items publisher loop.")
    while True:
        try:
            # Poll for QUEUED products
            products = await db.get_products(stage=ProductStage.QUEUED.value, limit=5, sort="created")
            for p in products:
                pid = p["id"]
                image_url = p.get("image_url")
                
                if not image_url:
                    images = p.get("images")
                    if images and isinstance(images, list):
                        image_url = images[0]
                
                caption = p.get("caption", "")
                hashtags = p.get("hashtags", [])
                if hashtags:
                    caption += "\n\n" + " ".join(hashtags)
                
                log.info(f"Publisher: Publishing product {pid}...")
                try:
                    await publish_to_instagram(image_url, caption)
                    await db.set_stage(pid, ProductStage.LIVE.value)
                    log.info(f"Publisher: Product {pid} published successfully. Moved to LIVE.")
                except Exception as e:
                    log.error(f"Publisher: Failed to publish {pid}: {e}")
                    # Could set to REJECTED or add a retry count if desired.
                    pass
                    
            # Wait 60 seconds if no products, else shorter
            await asyncio.sleep(60 if not products else 5)
            
        except asyncio.CancelledError:
            log.info("Publisher loop cancelled.")
            break
        except Exception as e:
            log.error(f"Publisher loop error: {e}", exc_info=True)
            await asyncio.sleep(60)
