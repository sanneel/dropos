from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import asyncio
import json
import os
import httpx
import hashlib
import re
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from database import db, init_db

app = FastAPI(title="Dropship Backoffice")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ Startup ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
@app.on_event("startup")
async def startup():
    await init_db()

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ Models ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
class ScanRequest(BaseModel):
    keywords: List[str]
    max_per_keyword: int = 100

class ApproveRequest(BaseModel):
    product_ids: List[int]

class SettingsUpdate(BaseModel):
    niche: Optional[str] = None
    min_margin: Optional[float] = None
    min_score: Optional[float] = None
    min_orders: Optional[int] = None
    min_rating: Optional[float] = None
    sell_markup_low: Optional[float] = None
    sell_markup_mid: Optional[float] = None
    sell_markup_high: Optional[float] = None
    instagram_username: Optional[str] = None
    apify_token: Optional[str] = None
    anthropic_key: Optional[str] = None
    exchange_rate: Optional[float] = None

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ Settings ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
@app.get("/api/settings")
async def get_settings():
    return await db.get_settings()

@app.patch("/api/settings")
async def update_settings(body: SettingsUpdate):
    await db.update_settings(body.model_dump(exclude_none=True))
    return {"ok": True}

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ Stats ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
@app.get("/api/stats")
async def get_stats():
    return await db.get_stats()

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ Products ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
@app.get("/api/products")
async def get_products(stage: str = "pending", limit: int = 50, offset: int = 0):
    products = await db.get_products(stage=stage, limit=limit, offset=offset)
    total = await db.count_products(stage=stage)
    return {"products": products, "total": total}

@app.get("/api/products/{product_id}")
async def get_product(product_id: int):
    p = await db.get_product(product_id)
    if not p:
        raise HTTPException(404, "Not found")
    return p

@app.post("/api/products/{product_id}/reject")
async def reject_product(product_id: int):
    await db.set_stage(product_id, "rejected")
    return {"ok": True}

@app.post("/api/approve")
async def approve_products(body: ApproveRequest, bg: BackgroundTasks):
    if len(body.product_ids) > 10:
        raise HTTPException(400, "Max 10 products at once")
    for pid in body.product_ids:
        await db.set_stage(pid, "approved")
    bg.add_task(post_approved_products, body.product_ids)
    return {"ok": True, "queued": len(body.product_ids)}

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ Scan pipeline ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
@app.post("/api/scan")
async def start_scan(body: ScanRequest, bg: BackgroundTasks):
    job_id = await db.create_job(keywords=body.keywords)
    bg.add_task(run_pipeline, job_id, body.keywords, body.max_per_keyword)
    return {"job_id": job_id, "status": "started"}

@app.get("/api/jobs")
async def get_jobs(limit: int = 10):
    return await db.get_jobs(limit)

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: int):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404)
    return job

# ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ Pipeline logic ÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂÃÂ¢ÃÂÃÂ
async def run_pipeline(job_id: int, keywords: list, max_per_keyword: int):
    settings = await db.get_settings()
    await db.update_job(job_id, status="scraping", progress=5)

    # 1. SCRAPE
    raw_products = await scrape_products(settings, keywords, max_per_keyword)
    await db.update_job(job_id, status="scraping", progress=20,
                        scraped=len(raw_products))

    # 2. BASIC FILTER (fast, no AI)
    filtered = basic_filter(raw_products, settings)
    await db.update_job(job_id, status="filtering", progress=40,
                        after_basic=len(filtered))

    # 3. PROFIT FILTER
    profitable = [p for p in filtered if profit_filter(p, settings)]
    await db.update_job(job_id, status="calculating", progress=55,
                        after_profit=len(profitable))

    # 4. DEDUP
    deduped = dedup(profitable)
    await db.update_job(job_id, status="deduping", progress=60,
                        after_dedup=len(deduped))

    # 5. AI REVIEW (batched to save API calls)
    passed = []
    total = len(deduped)
    for i, product in enumerate(deduped):
        reviewed = await ai_review(product, settings)
        if reviewed and reviewed.get("score", 0) >= settings.get("min_score", 7.0):
            product.update(reviewed)
            passed.append(product)
        progress = 60 + int((i / max(total, 1)) * 35)
        if i % 5 == 0:
            await db.update_job(job_id, status="ai_review", progress=progress,
                                after_ai=len(passed))

    await db.update_job(job_id, status="saving", progress=96,
                        after_ai=len(passed))

    # 6. SAVE to DB as "pending"
    for product in passed:
        await db.insert_product(product, job_id)

    await db.update_job(job_id, status="done", progress=100,
                        after_ai=len(passed))


def basic_filter(products: list, settings: dict) -> list:
    out = []
    seen_titles = set()
    for p in products:
        # Must have title and price
        if not p.get("title") or not p.get("price_cny"):
            continue
        # Min orders
        if p.get("orders", 0) < settings.get("min_orders", 100):
            continue
        # Min rating
        if p.get("rating", 0) < settings.get("min_rating", 4.5):
            continue
        # Skip wholesale/factory spam titles
        spam_keywords = ["ÃÂ¦ÃÂÃÂ¹ÃÂ¥ÃÂÃÂ", "ÃÂ¥ÃÂ·ÃÂ¥ÃÂ¥ÃÂÃÂÃÂ§ÃÂÃÂ´ÃÂ©ÃÂÃÂ", "ÃÂ¤ÃÂ»ÃÂ£ÃÂ¥ÃÂÃÂ", "ÃÂ¥ÃÂÃÂÃÂ¥ÃÂ®ÃÂ¶ÃÂ§ÃÂÃÂ´ÃÂ¤ÃÂ¾ÃÂ"]
        if any(kw in p.get("title", "") for kw in spam_keywords):
            continue
        # Skip if no images
        if not p.get("images"):
            continue
        # Dedup by title hash
        title_hash = hashlib.md5(p["title"][:30].encode()).hexdigest()
        if title_hash in seen_titles:
            continue
        seen_titles.add(title_hash)
        out.append(p)
    return out


def profit_filter(product: dict, settings: dict) -> bool:
    price_cny = float(product.get("price_cny", 0))
    exchange_rate = float(settings.get("exchange_rate", 0.13))
    shipping_cny = 15.0  # average shipping cost

    cost_eur = (price_cny + shipping_cny) * exchange_rate

    # Markup tiers
    if cost_eur < 5:
        markup = settings.get("sell_markup_low", 3.5)
    elif cost_eur < 15:
        markup = settings.get("sell_markup_mid", 2.8)
    else:
        markup = settings.get("sell_markup_high", 2.2)

    sell_price = cost_eur * markup
    margin = ((sell_price - cost_eur) / sell_price) * 100

    product["cost_eur"] = round(cost_eur, 2)
    product["sell_price_eur"] = round(sell_price, 2)
    product["margin_pct"] = round(margin, 1)

    return margin >= settings.get("min_margin", 60.0)


def dedup(products: list) -> list:
    seen = set()
    out = []
    for p in products:
        # Hash first image URL to catch duplicate listings
        img = (p.get("images") or [""])[0]
        key = hashlib.md5(img.encode()).hexdigest() if img else None
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(p)
    return out


async def ai_review(product: dict, settings: dict) -> Optional[dict]:
    api_key = settings.get("anthropic_key", "")
    niche = settings.get("niche", "aesthetic lifestyle products")

    prompt = f"""You are reviewing a product for an Instagram dropshipping store.
Store niche: "{niche}"

Product data:
- Translated title: {product.get('title_translated', product.get('title', 'Unknown'))}
- Category: {product.get('category', 'Unknown')}
- Price: ÃÂ¢ÃÂÃÂ¬{product.get('cost_eur', '?')} cost ÃÂ¢ÃÂÃÂ ÃÂ¢ÃÂÃÂ¬{product.get('sell_price_eur', '?')} sell ({product.get('margin_pct', '?')}% margin)
- Orders: {product.get('orders', 0)}
- Rating: {product.get('rating', 0)}/5
- Images available: {len(product.get('images', []))}

Score this product from 1-10 on:
1. Niche fit (does it match the store theme?)
2. Instagram visual appeal (would it look good in a post?)
3. Trend potential (is this something people want now?)
4. Competition level (avoid oversaturated products)

Also generate:
- A punchy English product name (3-5 words, no brand names)
- An Instagram caption (2-3 sentences, aspirational, fits the niche)
- 15 relevant hashtags

Return ONLY valid JSON, no markdown:
{{
  "score": <number 1-10>,
  "niche_fit": <1-10>,
  "visual_appeal": <1-10>,
  "trend_score": <1-10>,
  "rejection_reason": "<if score < 7, why>",
  "product_name": "<punchy name>",
  "caption": "<instagram caption>",
  "hashtags": ["tag1", "tag2", ...]
}}"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",  # cheap + fast for bulk review
                    "max_tokens": 600,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            if resp.status_code != 200:
                return None
            text = resp.json()["content"][0]["text"]
            # Strip any accidental markdown fences
            text = re.sub(r"```json|```", "", text).strip()
            return json.loads(text)
    except Exception:
        return None


async def scrape_products(settings: dict, keywords: list, max_per_keyword: int) -> list:
    token = settings.get("apify_token", "")
    if not token:
        # Return mock data for testing without Apify token
        return _mock_products(keywords)

    all_products = []
    async with httpx.AsyncClient(timeout=60) as client:
        for keyword in keywords:
            try:
                # Start Apify run
                resp = await client.post(
                    "https://api.apify.com/v2/acts/apify~1688-scraper/runs",
                    params={"token": token},
                    json={"keywords": [keyword], "maxResults": max_per_keyword}
                )
                if resp.status_code != 201:
                    continue
                run_id = resp.json()["data"]["id"]

                # Poll until done (max 5 min)
                for _ in range(60):
                    await asyncio.sleep(5)
                    status_resp = await client.get(
                        f"https://api.apify.com/v2/actor-runs/{run_id}",
                        params={"token": token}
                    )
                    status = status_resp.json()["data"]["status"]
                    if status == "SUCCEEDED":
                        break
                    if status in ("FAILED", "ABORTED"):
                        break

                # Fetch results
                items_resp = await client.get(
                    f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items",
                    params={"token": token, "limit": max_per_keyword}
                )
                items = items_resp.json()

                for item in items:
                    all_products.append({
                        "source": "1688",
                        "source_id": str(item.get("offerId", "")),
                        "title": item.get("title", ""),
                        "title_translated": item.get("titleEnglish", item.get("title", "")),
                        "price_cny": float(item.get("priceMin", item.get("price", 0)) or 0),
                        "orders": int(item.get("tradeCount", 0) or 0),
                        "rating": float(item.get("repurchaseRate", 4.5) or 4.5),
                        "images": item.get("images", []),
                        "url": item.get("productUrl", ""),
                        "category": item.get("category", ""),
                        "keyword": keyword,
                    })
            except Exception:
                continue

    return all_products


def _mock_products(keywords: list) -> list:
    """Returns realistic mock data when no Apify token is configured."""
    mock = []
    samples = [
        {"title": "ÃÂ¦ÃÂÃÂ ÃÂ§ÃÂºÃÂ¿ÃÂ¨ÃÂÃÂÃÂ§ÃÂÃÂÃÂ¨ÃÂÃÂ³ÃÂ¦ÃÂÃÂº5.0ÃÂ©ÃÂÃÂÃÂ¥ÃÂÃÂªÃÂ¨ÃÂ¶ÃÂÃÂ©ÃÂÃÂ¿ÃÂ§ÃÂ»ÃÂ­ÃÂ¨ÃÂÃÂª", "title_translated": "Wireless Bluetooth Earphones 5.0 Noise Cancel Long Battery", "price_cny": 28, "orders": 4521, "rating": 4.7, "category": "Electronics"},
        {"title": "ÃÂ§ÃÂ£ÃÂÃÂ¥ÃÂÃÂ¸ÃÂ¦ÃÂÃÂÃÂ¦ÃÂÃÂºÃÂ¦ÃÂÃÂ¯ÃÂ¦ÃÂÃÂ¶ÃÂ¦ÃÂ¡ÃÂÃÂ©ÃÂÃÂ¢ÃÂ¦ÃÂÃÂÃÂ¤ÃÂºÃÂºÃÂ¦ÃÂÃÂ¯ÃÂ¦ÃÂÃÂÃÂ¦ÃÂÃÂ¶", "title_translated": "Magnetic Phone Stand Desktop Lazy Holder", "price_cny": 12, "orders": 8234, "rating": 4.8, "category": "Phone Accessories"},
        {"title": "ÃÂ§ÃÂ®ÃÂÃÂ§ÃÂºÃÂ¦ÃÂ©ÃÂÃÂ¶ÃÂ§ÃÂÃÂ·ÃÂ©ÃÂ©ÃÂ¬ÃÂ¥ÃÂÃÂÃÂ¦ÃÂÃÂ¯ÃÂ¥ÃÂÃÂÃÂ¥ÃÂÃÂ¡ÃÂ¦ÃÂÃÂ¯ÃÂ¥ÃÂÃÂÃÂ¥ÃÂÃÂ¬ÃÂ¥ÃÂ®ÃÂ¤", "title_translated": "Minimalist Ceramic Mug Coffee Cup Office", "price_cny": 18, "orders": 3102, "rating": 4.9, "category": "Home"},
        {"title": "LEDÃÂ¦ÃÂ°ÃÂÃÂ¥ÃÂÃÂ´ÃÂ§ÃÂÃÂ¯USBÃÂ¦ÃÂ¡ÃÂÃÂ©ÃÂÃÂ¢ÃÂ¥ÃÂ°ÃÂÃÂ¥ÃÂ¤ÃÂÃÂ§ÃÂÃÂ¯", "title_translated": "LED Ambient Light USB Desktop Night Light", "price_cny": 22, "orders": 6780, "rating": 4.6, "category": "Home Decor"},
        {"title": "ÃÂ§ÃÂÃÂ®ÃÂ¨ÃÂ´ÃÂ¨ÃÂ§ÃÂ¬ÃÂÃÂ¨ÃÂ®ÃÂ°ÃÂ¦ÃÂÃÂ¬ÃÂ¦ÃÂÃÂÃÂ¨ÃÂ´ÃÂ¦ÃÂ¦ÃÂÃÂ¥ÃÂ¨ÃÂ®ÃÂ°ÃÂ¦ÃÂÃÂ¬", "title_translated": "Leather Notebook Journal Diary", "price_cny": 35, "orders": 2890, "rating": 4.8, "category": "Stationery"},
        {"title": "ÃÂ¥ÃÂ¤ÃÂÃÂ¥ÃÂÃÂÃÂ¨ÃÂÃÂ½ÃÂ¦ÃÂÃÂ¶ÃÂ§ÃÂºÃÂ³ÃÂ§ÃÂÃÂÃÂ¦ÃÂ¡ÃÂÃÂ©ÃÂÃÂ¢ÃÂ¦ÃÂÃÂ´ÃÂ§ÃÂÃÂ", "title_translated": "Multi-function Storage Box Desktop Organizer", "price_cny": 25, "orders": 5430, "rating": 4.7, "category": "Home"},
        {"title": "ÃÂ§ÃÂ¡ÃÂÃÂ¨ÃÂÃÂ¶ÃÂ¦ÃÂÃÂÃÂ¦ÃÂÃÂºÃÂ¥ÃÂ£ÃÂ³ÃÂ©ÃÂÃÂ²ÃÂ¦ÃÂÃÂÃÂ¤ÃÂ¿ÃÂÃÂ¦ÃÂÃÂ¤ÃÂ¥ÃÂ¥ÃÂ", "title_translated": "Silicone Phone Case Anti-drop Protective Cover", "price_cny": 8, "orders": 12000, "rating": 4.5, "category": "Phone Cases"},
        {"title": "ÃÂ§ÃÂ¼ÃÂÃÂ§ÃÂ»ÃÂÃÂ¦ÃÂÃÂÃÂ¦ÃÂÃÂÃÂ¥ÃÂÃÂÃÂ¦ÃÂÃÂÃÂ§ÃÂÃÂ¹ÃÂ¥ÃÂÃÂÃÂ¥ÃÂ¥ÃÂ³", "title_translated": "Woven Tote Bag Shoulder Bag Women", "price_cny": 45, "orders": 1890, "rating": 4.8, "category": "Bags"},
        {"title": "ÃÂ©ÃÂ¦ÃÂÃÂ¨ÃÂÃÂ°ÃÂ¨ÃÂÃÂ¡ÃÂ§ÃÂÃÂÃÂ§ÃÂ¤ÃÂ¼ÃÂ§ÃÂÃÂÃÂ¥ÃÂ¥ÃÂÃÂ¨ÃÂ£ÃÂ", "title_translated": "Aromatherapy Candle Gift Box Set", "price_cny": 38, "orders": 3210, "rating": 4.9, "category": "Home Fragrance"},
        {"title": "insÃÂ©ÃÂ£ÃÂÃÂ¥ÃÂ¹ÃÂ²ÃÂ¨ÃÂÃÂ±ÃÂ§ÃÂÃÂ¸ÃÂ¦ÃÂ¡ÃÂÃÂ¨ÃÂ£ÃÂÃÂ©ÃÂ¥ÃÂ°ÃÂ§ÃÂÃÂ»", "title_translated": "Instagram Style Dried Flower Photo Frame Wall Art", "price_cny": 42, "orders": 2100, "rating": 4.7, "category": "Home Decor"},
        {"title": "ÃÂ¦ÃÂÃÂÃÂ¥ÃÂÃÂ ÃÂ¦ÃÂÃÂ¶ÃÂ§ÃÂºÃÂ³ÃÂ¨ÃÂ¢ÃÂÃÂ¦ÃÂÃÂÃÂ¨ÃÂ¡ÃÂÃÂ¥ÃÂÃÂÃÂ¨ÃÂ£ÃÂÃÂ¨ÃÂ¢ÃÂ", "title_translated": "Foldable Storage Bag Travel Organizer", "price_cny": 15, "orders": 7650, "rating": 4.6, "category": "Travel"},
        {"title": "ÃÂ¦ÃÂÃÂ¹ÃÂ¥ÃÂÃÂÃÂ¥ÃÂ·ÃÂ¥ÃÂ¥ÃÂÃÂÃÂ§ÃÂÃÂ´ÃÂ©ÃÂÃÂÃÂ¦ÃÂÃÂÃÂ¦ÃÂÃÂºÃÂ©ÃÂÃÂÃÂ¤ÃÂ»ÃÂ¶ÃÂ¤ÃÂ½ÃÂÃÂ¤ÃÂ»ÃÂ·", "title_translated": "Wholesale Factory Direct Phone Accessories Cheap", "price_cny": 3, "orders": 50, "rating": 3.8, "category": "Spam"},
        {"title": "ÃÂ¦ÃÂÃÂ¨ÃÂ¨ÃÂ´ÃÂ¨ÃÂ¦ÃÂ¡ÃÂÃÂ©ÃÂÃÂ¢ÃÂ¦ÃÂÃÂÃÂ¤ÃÂ»ÃÂ¶ÃÂ¥ÃÂÃÂÃÂ¦ÃÂÃÂÃÂ¨ÃÂ£ÃÂÃÂ©ÃÂ¥ÃÂ°ÃÂ¥ÃÂÃÂ", "title_translated": "Wooden Desktop Ornament Creative Decoration", "price_cny": 29, "orders": 4320, "rating": 4.8, "category": "Home Decor"},
    ]
    import random
    for kw in keywords:
        for s in random.sample(samples, min(len(samples), 8)):
            p = dict(s)
            p.update({
                "source": "1688_mock",
                "source_id": hashlib.md5(f"{kw}{s['title']}".encode()).hexdigest()[:12],
                "images": [f"https://picsum.photos/seed/{hashlib.md5(s['title'].encode()).hexdigest()[:6]}/600/600"],
                "url": "https://1688.com",
                "keyword": kw,
            })
            mock.append(p)
    return mock


async def post_approved_products(product_ids: list[int]):
    """Placeholder ÃÂ¢ÃÂÃÂ integrate with instagrapi or Buffer API here."""
    for pid in product_ids:
        await asyncio.sleep(1)
        await db.set_stage(pid, "posted")
        await db.log_post(pid)
