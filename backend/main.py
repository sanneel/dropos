import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))

from database import db, init_db
from runner import run_pipeline
from scheduler import create_scheduler, get_scheduler_status
import instagram
import sheets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Ensure app-level loggers survive uvicorn's log override
def _setup_app_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    for name in ("runner", "scraper_cssbuy", "filter_engine", "enrichment", "scorer", "__main__"):
        lg = logging.getLogger(name)
        if not lg.handlers:
            lg.addHandler(handler)
        lg.setLevel(logging.INFO)
        lg.propagate = True

_setup_app_logging()

_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    await init_db()
    _scheduler = create_scheduler()
    _scheduler.start()
    log.info("Scheduler started — jobs: %s", [j.id for j in _scheduler.get_jobs()])
    yield
    _scheduler.shutdown(wait=False)
    await db.close()


app = FastAPI(title="DropOS Backoffice", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "DropOS backend running", "docs": "/docs", "api": "/api/stats"}


# ── Request models ─────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    keywords: List[str]
    max_per_keyword: int = 50
    source: str = "1688"


class ApproveRequest(BaseModel):
    product_ids: List[int]


class BatchRejectRequest(BaseModel):
    product_ids: List[int]
    reason: Optional[str] = None


class PostRequest(BaseModel):
    product_ids: List[int]


class RejectRequest(BaseModel):
    reason: Optional[str] = None


class NoteUpdate(BaseModel):
    note: str


class SettingsUpdate(BaseModel):
    niche: Optional[str] = None
    min_margin: Optional[float] = None
    min_score: Optional[float] = None
    min_orders: Optional[int] = None
    min_rating: Optional[float] = None
    sell_markup_low: Optional[float] = None
    sell_markup_mid: Optional[float] = None
    sell_markup_high: Optional[float] = None
    exchange_rate: Optional[float] = None
    instagram_username: Optional[str] = None
    apify_token: Optional[str] = None
    anthropic_key: Optional[str] = None
    gemini_key: Optional[str] = None
    scan_keywords: Optional[List[str]] = None
    google_sheets_id: Optional[str] = None
    google_sheets_credentials: Optional[str] = None
    cssbuy_username: Optional[str] = None
    cssbuy_password: Optional[str] = None
    cssbuy_source: Optional[str] = None
    captcha_2captcha_key: Optional[str] = None


# ── Settings ───────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    return await db.get_settings()


@app.patch("/api/settings")
async def update_settings(body: SettingsUpdate):
    data = body.model_dump(exclude_none=True)
    await db.update_settings(data)

    # Reconfigure sheets exporter if credentials changed
    gid = data.get("google_sheets_id") or (await db.get_settings()).get("google_sheets_id", "")
    gcreds = data.get("google_sheets_credentials", "")
    if gid and gcreds:
        sheets.configure(gcreds, gid)

    return {"ok": True}


# ── Stats ──────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    return await db.get_stats()


# ── Products ───────────────────────────────────────────────────────────────────

@app.get("/api/products")
async def get_products(
    stage: str = "pending", limit: int = 50, offset: int = 0, sort: str = "score"
):
    products = await db.get_products(stage=stage, limit=limit, offset=offset, sort=sort)
    total = await db.count_products(stage=stage)
    return {"products": products, "total": total}


@app.get("/api/products/{product_id}")
async def get_product(product_id: int):
    p = await db.get_product(product_id)
    if not p:
        raise HTTPException(404, "Not found")
    return p


@app.post("/api/products/{product_id}/approve")
async def approve_product(product_id: int):
    p = await db.get_product(product_id)
    if not p:
        raise HTTPException(404, "Not found")
    if p.get("stage") != "pending":
        raise HTTPException(400, f"Cannot approve product in stage '{p.get('stage')}'")
    await db.set_stage(product_id, "approved")
    return {"ok": True}


@app.post("/api/approve")
async def approve_products(body: ApproveRequest):
    if len(body.product_ids) > 50:
        raise HTTPException(400, "Max 50 products at once")
    for pid in body.product_ids:
        await db.set_stage(pid, "approved")
    return {"ok": True, "approved": len(body.product_ids)}


@app.post("/api/reject")
async def reject_products(body: BatchRejectRequest):
    if len(body.product_ids) > 50:
        raise HTTPException(400, "Max 50 products at once")
    reason = (body.reason or "").strip() or None
    for pid in body.product_ids:
        await db.set_stage(pid, "rejected", reason=reason)
    return {"ok": True, "rejected": len(body.product_ids)}


@app.post("/api/products/{product_id}/post")
async def post_product(product_id: int, bg: BackgroundTasks):
    p = await db.get_product(product_id)
    if not p:
        raise HTTPException(404, "Not found")
    if p.get("stage") != "approved":
        raise HTTPException(400, f"Can only post approved products (stage: '{p.get('stage')}')")
    await db.set_stage(product_id, "posted")
    await db.log_post(product_id)
    bg.add_task(_post_and_export, [p])
    return {"ok": True}


@app.post("/api/post")
async def post_products(body: PostRequest, bg: BackgroundTasks):
    if len(body.product_ids) > 10:
        raise HTTPException(400, "Max 10 products at once")
    to_post = []
    for pid in body.product_ids:
        p = await db.get_product(pid)
        if p and p.get("stage") == "approved":
            await db.set_stage(pid, "posted")
            await db.log_post(pid)
            to_post.append(p)
    bg.add_task(_post_and_export, to_post)
    return {"ok": True, "queued": len(to_post)}


@app.post("/api/products/{product_id}/reject")
async def reject_product(product_id: int, body: RejectRequest = None):
    reason = (body.reason or "").strip() if body else ""
    await db.set_stage(product_id, "rejected", reason=reason or None)
    return {"ok": True}


@app.post("/api/products/{product_id}/reconsider")
async def reconsider_product(product_id: int):
    p = await db.get_product(product_id)
    if not p:
        raise HTTPException(404, "Not found")
    await db.set_stage(product_id, "pending")
    return {"ok": True}


@app.patch("/api/products/{product_id}/note")
async def update_note(product_id: int, body: NoteUpdate):
    p = await db.get_product(product_id)
    if not p:
        raise HTTPException(404, "Not found")
    await db.update_product_note(product_id, body.note)
    return {"ok": True}


# ── Scan / Jobs ────────────────────────────────────────────────────────────────

@app.post("/api/scan")
async def start_scan(body: ScanRequest, bg: BackgroundTasks):
    job_id = await db.create_job(keywords=body.keywords)
    bg.add_task(_run_scan, job_id, body.keywords, body.max_per_keyword, body.source)
    return {"job_id": job_id, "status": "started"}


@app.get("/api/jobs")
async def get_jobs(limit: int = 20):
    return await db.get_jobs(limit)


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: int):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404)
    return job


# ── Scheduler ──────────────────────────────────────────────────────────────────

@app.get("/api/scheduler/status")
async def scheduler_status():
    return get_scheduler_status(_scheduler)


@app.post("/api/scheduler/trigger")
async def scheduler_trigger(bg: BackgroundTasks):
    """Manually fire a scheduled scan now (uses stored scan_keywords)."""
    settings = await db.get_settings()
    raw = settings.get("scan_keywords", [])
    keywords: list = raw if isinstance(raw, list) else [raw]
    if not keywords:
        keywords = ["aesthetic home decor"]
    job_id = await db.create_job(keywords=keywords)
    bg.add_task(_run_scan, job_id, keywords, 50)
    return {"ok": True, "job_id": job_id, "keywords": keywords}


# ── Google Sheets ──────────────────────────────────────────────────────────────

@app.post("/api/sheets/export")
async def export_to_sheets():
    """Export all approved + posted products to Google Sheets."""
    approved = await db.get_products(stage="approved", limit=500)
    posted = await db.get_products(stage="posted", limit=500)
    all_products = approved + posted
    if not all_products:
        return {"ok": True, "exported": 0, "message": "No products to export"}
    result = sheets.export(all_products)
    return result


# ── Background helpers ─────────────────────────────────────────────────────────

async def _run_scan(job_id: int, keywords: list, max_per_keyword: int, source: str = "1688") -> None:
    try:
        await run_pipeline(job_id, keywords, max_per_keyword, source=source)
    except Exception as e:
        log.error("Pipeline job %d failed: %s", job_id, e)
        await db.update_job(job_id, status="error")


async def _post_and_export(products: list) -> None:
    if not products:
        return
    try:
        results = await instagram.post_batch(products)
        log.info("Instagram posted %d products", len(results))
        sheets.export(products)
    except Exception as e:
        log.error("Post/export error: %s", e)
