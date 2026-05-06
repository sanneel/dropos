import asyncio
import logging
import json
from database import db, init_db
from runner import process_scraped_products
from filter_engine import profit_filter
from collage import create_collage
from enrichment import ai_enrich_batch

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("smoke_test")

async def run_smoke_test():
    log.info("Starting Phase 7 Smoke Test...")
    
    # 1. Setup DB
    # We use the existing DB from DATABASE_URL
    await db.connect()
    
    # 2. Mock 20 products
    mock_raw = []
    
    # a. 1688 item with 0 orders (Should be REJECTED by Bouncer)
    mock_raw.append({
        "source_id": "1688_bad_orders",
        "source_platform": "1688",
        "title": "Low Order Item",
        "price_cny": 50.0,
        "orders": 0,
        "images": ["https://picsum.photos/200"]
    })
    
    # b. Very cheap item (Should have high markup)
    mock_raw.append({
        "source_id": "cheap_item_1",
        "source_platform": "taobao",
        "title": "Cheap Jewelry",
        "price_cny": 10.0,
        "orders": 100,
        "images": ["https://picsum.photos/201"]
    })
    
    # c. Expensive item (Should have lower margin req/mid markup)
    mock_raw.append({
        "source_id": "expensive_item_1",
        "source_platform": "taobao",
        "title": "Premium Gadget",
        "price_cny": 300.0,
        "orders": 100,
        "images": ["https://picsum.photos/202"]
    })
    
    # d. Tech item (Should have low markup)
    mock_raw.append({
        "source_id": "tech_item_1",
        "source_platform": "1688",
        "title": "Digital Camera CCD",
        "price_cny": 100.0,
        "orders": 50,
        "images": ["https://picsum.photos/203"]
    })
    
    # Add more to reach 20
    for i in range(16):
        mock_raw.append({
            "source_id": f"bulk_item_{i}",
            "source_platform": "taobao",
            "title": f"Regular Product {i}",
            "price_cny": 50.0,
            "orders": 50,
            "images": [f"https://picsum.photos/20{i+4}"]
        })
    
    # 3. Test Runner Logic (The Bouncer & Detective)
    job_id = await db.create_job(keywords=["smoke test"])
    log.info(f"Created Job {job_id}. Processing {len(mock_raw)} mock products...")
    
    summary = await process_scraped_products(job_id, mock_raw)
    log.info(f"Runner Summary: {summary}")
    
    # 4. Verify DB State (Dead Letter Log)
    rejected = await db._db.fetch("SELECT rejection_reason FROM products WHERE job_id = $1 AND stage = 'REJECTED'", job_id)
    scraped = await db._db.fetch("SELECT source_id, cost_eur, sell_price_eur FROM products WHERE job_id = $1 AND stage = 'SCRAPED'", job_id)
    
    log.info(f"Found {len(rejected)} REJECTED items in DB.")
    for r in rejected:
        log.info(f"  - Rejection Reason: {r['rejection_reason']}")
        
    log.info(f"Found {len(scraped)} SCRAPED items in DB.")
    for s in scraped:
        log.info(f"  - Item {s['source_id']}: Cost={s['cost_eur']} Sell={s['sell_price_eur']}")

    # 5. Test Collage Logic (Batch of 4)
    log.info("Testing collage logic with batch of 4...")
    test_images = ["https://picsum.photos/200", "https://picsum.photos/201", "https://picsum.photos/202", "https://picsum.photos/203"]
    collage = await create_collage(test_images)
    if collage:
        log.info(f"Collage created successfully ({len(collage)} bytes).")
    else:
        log.error("Collage creation failed!")

    await db.close()
    log.info("Smoke Test Complete.")

if __name__ == "__main__":
    asyncio.run(run_smoke_test())
