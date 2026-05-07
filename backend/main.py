import logging
import os
import sys
import hmac
import asyncio
import json
import uuid as _uuid
from contextlib import asynccontextmanager
from typing import List, Optional
from urllib.parse import unquote, urlparse

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import httpx

# ── Path Resolution (Railway/Nixpacks Robustness) ──────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Robustly find PROJECT_ROOT:
# 1. If 'frontend' exists in BASE_DIR, we are likely in a flattened structure (/app)
# 2. Otherwise, we assume we are in 'backend/' and go up one level.
if os.path.isdir(os.path.join(BASE_DIR, "frontend")):
    PROJECT_ROOT = BASE_DIR
else:
    PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

PUBLIC_DIR = os.path.join(PROJECT_ROOT, "frontend", "public")


# Ensure backend dir is in path for relative imports
sys.path.insert(0, BASE_DIR)

# Import local modules
from models import ProductStage
from config.runtime import get_config, merge_env_with_settings, sanitize_settings
from image_editor import remove_text as clipdrop_remove_text
from database import db, init_db
from runner import process_scraped_products, run_pipeline
from scheduler import create_scheduler, get_scheduler_status
import instagram
import sheets
import ai_assistant
from utils.google_auth import configure_google_credentials_from_env
from worker import run_worker_loop, process_queued_items

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

def _setup_app_logging():
    """Keep app loggers visible when uvicorn installs its own handlers."""
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

# ── Globals & Constants ───────────────────────────────────────────────────
_scheduler = None
_SENSITIVE_SETTING_FIELDS = {
    "apify_token",
    "anthropic_key",
    "gemini_key",
    "groq_key",
    "instagram_access_token",
    "instagram_webhook_token",
    "cssbuy_password",
    "captcha_2captcha_key",
    "google_sheets_credentials",
    "ingest_api_token",
    "clipdrop_key",
}
_cleaned_images: dict[int, bytes] = {}
_COLLAGE_DIR = "/tmp/dropos_collages"
os.makedirs(_COLLAGE_DIR, exist_ok=True)
_CSSBUY_DEBUG_DIR = os.getenv("CSSBUY_DEBUG_DIR") or "/tmp/cssbuy_debug"

# ── Lifespan ───────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    await init_db()
    interrupted = await db.mark_active_jobs_interrupted()
    if interrupted:
        log.warning("Marked %d stale active job(s) as interrupted on startup", interrupted)
    
    configure_google_credentials_from_env()
    
    settings = await db.get_settings()
    merged_settings = merge_env_with_settings(settings)
    
    sheets.configure(
        merged_settings.get("google_sheets_credentials") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
        merged_settings.get("google_sheets_id", ""),
    )
    
    if merged_settings.get("google_sheets_id"):
        asyncio.create_task(_sync_sheets_after_startup())

    # Environment audit
    _required_env = {
        "DATABASE_URL": "PostgreSQL connection string (Railway/Supabase)",
        "SUPABASE_URL": "Supabase project URL (image storage)",
        "SUPABASE_SERVICE_ROLE_KEY": "Supabase service role key (image storage)",
    }
    for var, description in _required_env.items():
        if not os.getenv(var):
            log.critical("MISSING ENV VAR: %s (%s) — some features will not work.", var, description)

    # Autonomous worker loops
    asyncio.create_task(run_worker_loop())
    asyncio.create_task(process_queued_items())

    if merged_settings.get("local_scraping_only"):
        log.info("Scheduler disabled: local scraping only mode is enabled")
    else:
        _scheduler = create_scheduler()
        _scheduler.start()
        log.info("Scheduler started - jobs: %s", [j.get("id") for j in _scheduler.get_jobs()])
        
    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)
    await db.close()

# ── App Initialization ─────────────────────────────────────────────────────
app = FastAPI(title="DropOS", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes & Mounts ────────────────────────────────────────────────────────

@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    return "User-agent: *\nAllow: /\nUser-agent: facebookexternalhit\nAllow: /\n"

@app.get("/")
async def root():
    """Backoffice (Admin Dashboard)."""
    # Try both backend/frontend and PROJECT_ROOT/frontend (admin is often moved around)
    paths = [
        os.path.join(BASE_DIR, "frontend", "index.html"),
        os.path.join(PROJECT_ROOT, "backend", "frontend", "index.html"),
        os.path.join(PROJECT_ROOT, "frontend", "index.html"),
    ]
    for p in paths:
        if os.path.exists(p):
            return FileResponse(p)
    return {"status": "DropOS Backoffice not found", "searched": paths, "docs": "/docs"}


@app.get("/shop")
async def shop():
    """Public-facing boutique storefront."""
    paths = [
        os.path.join(PUBLIC_DIR, "index.html"),
        os.path.join(PROJECT_ROOT, "frontend", "public", "index.html"),
    ]
    for p in paths:
        if os.path.exists(p):
            return FileResponse(p)
    return {"status": "Storefront not available", "searched": paths}


# Mount Backoffice Assets
admin_assets = os.path.join(BASE_DIR, "frontend", "assets")
if os.path.isdir(admin_assets):
    app.mount("/assets", StaticFiles(directory=admin_assets), name="admin-assets")

# Mount Boutique Assets
shop_assets = os.path.join(PUBLIC_DIR, "assets")
if os.path.isdir(shop_assets):
    app.mount("/shop/assets", StaticFiles(directory=shop_assets), name="shop-assets")

# Legacy/General static mount
if os.path.isdir(os.path.join(BASE_DIR, "frontend")):
    app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "frontend")), name="static")

# ── Request Models ──────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    keywords: List[str]
    max_per_keyword: int = 50
    source: str = "taobao"

class IngestProductsRequest(BaseModel):
    products: List[dict]
    keywords: List[str] = []
    source: Optional[str] = None

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

class ProductUpdate(BaseModel):
    product_name: Optional[str] = None
    title_translated: Optional[str] = None
    description: Optional[str] = None
    sell_price_eur: Optional[float] = None
    caption: Optional[str] = None
    hashtags: Optional[List[str]] = None
    category: Optional[str] = None
    url: Optional[str] = None
    has_chinese_text: Optional[bool] = None
    chinese_text_note: Optional[str] = None

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
    instagram_access_token: Optional[str] = None
    instagram_user_id: Optional[str] = None
    instagram_auto_reply_enabled: Optional[bool] = None
    instagram_reply_rules: Optional[list] = None
    instagram_dm_reply_enabled: Optional[bool] = None
    instagram_dm_rules: Optional[list] = None
    instagram_webhook_token: Optional[str] = None
    apify_token: Optional[str] = None
    anthropic_key: Optional[str] = None
    gemini_key: Optional[str] = None
    groq_key: Optional[str] = None
    scan_keywords: Optional[List[str]] = None
    google_sheets_id: Optional[str] = None
    google_sheets_credentials: Optional[str] = None
    public_base_url: Optional[str] = None
    playwright_timeout: Optional[int] = None
    scrape_interval: Optional[int] = None
    cssbuy_username: Optional[str] = None
    cssbuy_password: Optional[str] = None
    cssbuy_source: Optional[str] = None
    captcha_2captcha_key: Optional[str] = None
    ingest_api_token: Optional[str] = None
    local_scraping_only: Optional[bool] = None
    gemini_model: Optional[str] = None
    target_audience: Optional[str] = None
    sell_price_min: Optional[float] = None
    sell_price_max: Optional[float] = None
    example_products: Optional[str] = None
    clipdrop_key: Optional[str] = None
    post_schedule_enabled: Optional[bool] = None
    post_times: Optional[List[str]] = None
    post_timezone: Optional[str] = None
    posts_per_slot: Optional[int] = None

# ── Helper Functions ────────────────────────────────────────────────────────

async def _settings() -> dict:
    return merge_env_with_settings(await db.get_settings())

def _remove_blank_sensitive_values(data: dict) -> None:
    for key in list(data.keys()):
        value = data[key]
        if key in _SENSITIVE_SETTING_FIELDS and isinstance(value, str):
            val_strip = value.strip()
            # If the value is blank OR it's the masked representation from the UI,
            # we remove it so it doesn't overwrite the existing real key in the DB.
            if not val_strip or val_strip == "••••••••":
                data.pop(key)


async def _get_product_or_404(product_id: int) -> dict:
    product = await db.get_product(product_id)
    if not product:
        raise HTTPException(404, "Not found")
    return product

def _require_stage(product: dict, expected_stage: str, message: str) -> None:
    if product.get("stage") != expected_stage:
        raise HTTPException(400, message.format(stage=product.get("stage")))

async def _configure_sheets_from_settings(settings: Optional[dict] = None) -> None:
    settings = settings or await _settings()
    sheets_id = settings.get("google_sheets_id", "")
    credentials = settings.get("google_sheets_credentials") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    if sheets_id and credentials:
        sheets.configure(credentials, sheets_id)

async def _restore_database_from_sheets() -> dict:
    try:
        remote_settings = await asyncio.to_thread(sheets.load_settings)
        if remote_settings:
            await db.update_settings(remote_settings)
        remote_products = await asyncio.to_thread(sheets.load_products)
        imported = await db.upsert_product_backups(remote_products)
        return {"ok": True, "settings": len(remote_settings), "products": imported}
    except Exception as exc:
        log.warning("Restore from sheets skipped: %s", exc)
        return {"ok": False, "error": str(exc), "settings": 0, "products": 0}

async def _sync_sheets_after_startup() -> None:
    try:
        await asyncio.to_thread(sheets.verify_writable)
    except Exception: pass
    await _restore_database_from_sheets()
    await _configure_sheets_from_settings()

async def _backup_settings_to_sheets() -> dict:
    try:
        snapshot = await db.get_settings()
        return await asyncio.to_thread(sheets.save_settings, snapshot)
    except Exception as exc:
        log.warning("Settings backup failed: %s", exc)
        return {"ok": False, "error": str(exc)}

async def _backup_products_to_sheets() -> dict:
    try:
        snapshot = await db.get_all_products()
        return await asyncio.to_thread(sheets.save_products, snapshot)
    except Exception as exc:
        log.warning("Products backup failed: %s", exc)
        return {"ok": False, "error": str(exc)}

async def _backup_database_to_sheets() -> dict:
    s = await _backup_settings_to_sheets()
    p = await _backup_products_to_sheets()
    return {"ok": s.get("ok") and p.get("ok"), "settings": s, "products": p}

def _pipeline_summary(job: dict, stages: dict) -> dict:
    raw = stages.get("raw_fetch", [])
    ai_pass = stages.get("ai_pass", [])
    rejected = [item for stage, items in stages.items() if stage not in ("ai_pass", "raw_fetch") for item in items]
    
    reason_counts: dict = {}
    for item in rejected:
        r = (item.get("filter_reason") or item.get("filter_stage") or "Filtered out").strip()
        reason_counts[r] = reason_counts.get(r, 0) + 1
    
    scraped = int(job.get("scraped") or len(raw) or 0)
    pass_rate = (len(ai_pass) / scraped * 100) if scraped else 0
    
    return {
        "headline": f"{len(ai_pass)} products accepted for review from {scraped} fetched items.",
        "pass_rate": round(pass_rate, 1),
        "rejected": len(rejected),
        "top_reasons": [{"reason": k, "count": v} for k, v in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:6]],
        "recommendations": ["Filters look balanced."]
    }

async def _create_scan_job(bg: BackgroundTasks, keywords: list, max_per_keyword: int, source: str) -> int:
    active = await db.get_active_job()
    if active:
        raise HTTPException(409, {"message": f"Job #{active['id']} is already running", "job_id": active["id"]})
    job_id = await db.create_job(keywords=keywords)
    bg.add_task(_run_scan, job_id, keywords, max_per_keyword, source)
    return job_id

async def _stage_products(product_ids: List[int], stage: str, **kwargs) -> list:
    changed = []
    for pid in product_ids:
        p = await db.get_product(pid)
        if not p: continue
        if kwargs.get("required_stage") and p.get("stage") != kwargs["required_stage"]: continue
        await db.set_stage(pid, stage, reason=kwargs.get("reason"))
        if kwargs.get("log_posts"): await db.log_post(pid)
        changed.append(p)
    return changed

def _approval_stage(product: dict) -> str:
    return ProductStage.ENRICHED.value if product.get("has_chinese_text") else ProductStage.REVIEWED.value

def _items_to_stages(items: list) -> dict:
    stages: dict = {}
    for i in items:
        s = i.get("filter_stage") or "raw_fetch"
        stages.setdefault(s, []).append(i)
    return stages

# ── API Endpoints ───────────────────────────────────────────────────────────

@app.get("/api/robots.txt", response_class=PlainTextResponse)
async def robots_txt_api():
    return "User-agent: *\nAllow: /\n"

@app.get("/api/catalog")
async def get_catalog(limit: int = 100, offset: int = 0):
    """Consolidated endpoint for the public storefront."""
    reviewed = await db.get_products(stage=ProductStage.REVIEWED.value, limit=limit, offset=offset)
    live = await db.get_products(stage=ProductStage.LIVE.value, limit=limit, offset=offset)
    return {
        "products": reviewed + live,
        "total": len(reviewed) + len(live)
    }

@app.get("/api/settings")

async def get_settings():
    return sanitize_settings(await _settings())

@app.patch("/api/settings")
async def update_settings(body: SettingsUpdate):
    data = body.model_dump(exclude_none=True)
    _remove_blank_sensitive_values(data)
    await db.update_settings(data)
    await _configure_sheets_from_settings()
    await _backup_settings_to_sheets()
    return {"ok": True}

@app.get("/api/stats")
async def get_stats():
    return await db.get_stats()

@app.get("/api/products")
async def get_products(stage: str = ProductStage.SCRAPED.value, limit: int = 50, offset: int = 0, sort: str = "score"):
    products = await db.get_products(stage=stage, limit=limit, offset=offset, sort=sort)
    total = await db.count_products(stage=stage)
    return {"products": products, "total": total}

@app.get("/api/products/{product_id}")
async def get_product(product_id: int):
    return await _get_product_or_404(product_id)

@app.patch("/api/products/{product_id}")
async def update_product(product_id: int, body: ProductUpdate):
    data = body.model_dump(exclude_none=True)
    if "hashtags" in data:
        data["hashtags_json"] = json.dumps(data.pop("hashtags") or [])
    updated = await db.update_product_fields(product_id, data)
    await _backup_products_to_sheets()
    return {"ok": True, "product": updated}

@app.get("/api/image")
async def proxy_image(url: str):
    src = unquote(url or "").strip()
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(src, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.1688.com/"})
        if r.status_code != 200: raise HTTPException(r.status_code, "Fetch failed")
        return Response(content=r.content, media_type=r.headers.get("content-type", "image/jpeg"), headers={"Cache-Control": "public, max-age=86400"})
    except Exception as e:
        raise HTTPException(502, f"Proxy failed: {e}")

@app.post("/api/products/{product_id}/approve")
async def approve_product(product_id: int):
    p = await _get_product_or_404(product_id)
    _require_stage(p, ProductStage.SCRAPED.value, "Cannot approve product in stage '{stage}'")
    stage = _approval_stage(p)
    await db.set_stage(product_id, stage)
    await _backup_products_to_sheets()
    return {"ok": True, "stage": stage}

@app.post("/api/approve")
async def approve_products(body: ApproveRequest):
    approved = 0
    text_edit = 0
    for pid in body.product_ids[:50]:
        p = await db.get_product(pid)
        if p and p.get("stage") == ProductStage.SCRAPED.value:
            stage = _approval_stage(p)
            await db.set_stage(pid, stage)
            if stage == ProductStage.ENRICHED.value: text_edit += 1
            else: approved += 1
    await _backup_products_to_sheets()
    return {"ok": True, "approved": approved, "text_edit": text_edit}

@app.post("/api/reject")
async def reject_products_batch(body: BatchRejectRequest):
    reason = (body.reason or "").strip() or None
    await _stage_products(body.product_ids, ProductStage.REJECTED.value, reason=reason)
    await _backup_products_to_sheets()
    return {"ok": True, "rejected": len(body.product_ids)}

@app.post("/api/products/{product_id}/post")
async def post_product_single(product_id: int, bg: BackgroundTasks):
    p = await _get_product_or_404(product_id)
    _require_stage(p, ProductStage.REVIEWED.value, "Can only post approved products (stage: '{stage}')")
    bg.add_task(_post_and_export, [p])
    return {"ok": True, "queued": 1}

@app.post("/api/post")
async def post_products_batch(body: PostRequest, bg: BackgroundTasks):
    to_post = await _stage_products(body.product_ids[:10], ProductStage.REVIEWED.value, required_stage=ProductStage.REVIEWED.value)
    bg.add_task(_post_and_export, to_post)
    return {"ok": True, "queued": len(to_post)}

@app.post("/api/products/{product_id}/reject")
async def reject_product_single(product_id: int, body: RejectRequest = None):
    reason = (body.reason or "").strip() if body else None
    await db.set_stage(product_id, ProductStage.REJECTED.value, reason=reason)
    await _backup_products_to_sheets()
    return {"ok": True}

@app.post("/api/products/{product_id}/reconsider")
async def reconsider_product(product_id: int):
    await db.set_stage(product_id, ProductStage.SCRAPED.value)
    await _backup_products_to_sheets()
    return {"ok": True}

@app.post("/api/products/{product_id}/text-edited")
async def mark_text_edited(product_id: int):
    await db.update_product_fields(product_id, {"has_chinese_text": False, "chinese_text_note": ""})
    await db.set_stage(product_id, ProductStage.REVIEWED.value)
    await _backup_products_to_sheets()
    return {"ok": True}

@app.post("/api/products/{product_id}/remove-text")
async def remove_product_text(product_id: int):
    p = await _get_product_or_404(product_id)
    settings = await _settings()
    key = settings.get("clipdrop_key")
    if not key: raise HTTPException(400, "Clipdrop API key missing")
    
    url = (p.get("images") or [""])[0]
    cleaned = await clipdrop_remove_text(url, key)
    if not cleaned: raise HTTPException(502, "Clipdrop failed")
    
    _cleaned_images[product_id] = cleaned
    with open(f"{_COLLAGE_DIR}/cleaned_{product_id}.jpg", "wb") as f: f.write(cleaned)
    
    base = str(settings.get("public_base_url") or "").rstrip("/")
    new_url = f"{base}/api/products/{product_id}/cleaned-image" if base else f"/api/products/{product_id}/cleaned-image"
    
    imgs = [new_url] + [img for img in (p.get("images") or []) if img and img != url]
    await db.update_product_fields(product_id, {"images_json": json.dumps(imgs), "has_chinese_text": False})
    await db.set_stage(product_id, ProductStage.REVIEWED.value)
    return {"ok": True, "image_url": new_url}

@app.get("/api/products/{product_id}/cleaned-image")
async def serve_cleaned_image(product_id: int):
    data = _cleaned_images.get(product_id)
    if not data:
        path = f"{_COLLAGE_DIR}/cleaned_{product_id}.jpg"
        if os.path.exists(path):
            with open(path, "rb") as f: data = f.read()
    if not data: raise HTTPException(404, "Not found")
    return Response(content=data, media_type="image/jpeg")

@app.patch("/api/products/{product_id}/note")
async def update_note(product_id: int, body: NoteUpdate):
    await db.update_product_note(product_id, body.note)
    return {"ok": True}

@app.post("/api/scan")
async def start_scan(body: ScanRequest, bg: BackgroundTasks):
    job_id = await _create_scan_job(bg, body.keywords, body.max_per_keyword, body.source)
    return {"job_id": job_id, "status": "started"}

@app.post("/api/ingest/products")
async def ingest_products(body: IngestProductsRequest, bg: BackgroundTasks, authorization: Optional[str] = Header(None), x_ingest_token: Optional[str] = Header(None)):
    await _verify_ingest_token(authorization, x_ingest_token)
    job_id = await db.create_job(keywords=body.keywords or ["local upload"])
    bg.add_task(_run_ingest, job_id, body.products)
    return {"job_id": job_id, "status": "uploaded"}

@app.get("/api/jobs")
async def get_jobs(limit: int = 20):
    return await db.get_jobs(limit)

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: int):
    job = await db.get_job(job_id)
    if not job: raise HTTPException(404)
    return job

@app.get("/api/jobs/{job_id}/pipeline")
async def get_job_pipeline(job_id: int):
    job = await db.get_job(job_id)
    if not job: raise HTTPException(404)
    items = await db.get_scan_items(job_id)
    stages = _items_to_stages(items)
    return {"job": job, "stages": stages, "summary": _pipeline_summary(job, stages)}

@app.get("/api/analytics")
async def get_analytics():
    data = await db.get_analytics()
    data["stats"] = await db.get_stats()
    return data

class ChatRequest(BaseModel):
    message: str
    reconsider: Optional[bool] = False
    execute_edits: Optional[bool] = False
    execute_approvals: Optional[bool] = False

@app.post("/api/ai/chat")
async def ai_chat(body: ChatRequest):
    settings = await _settings()
    context = {"stats": await db.get_stats()}
    return await ai_assistant.chat(body.message, context, settings)

# ── Instagram ─────────────────────────────────────────────────────────────────

@app.get("/api/instagram/accounts")
async def instagram_accounts():
    return {"accounts": []}

@app.get("/api/instagram/diagnostics")
async def instagram_diagnostics(product_id: Optional[int] = None):
    return {"status": "ok"}

@app.get("/api/instagram/webhook")
async def ig_webhook_verify(hub_mode: str = Query(None, alias="hub.mode"), hub_verify_token: str = Query(None, alias="hub.verify_token"), hub_challenge: str = Query(None, alias="hub.challenge")):
    settings = await _settings()
    verify_token = str(settings.get("instagram_webhook_token") or "dropos_webhook_secret")
    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(403)

@app.post("/api/instagram/webhook")
async def ig_webhook_receive(request: Request, bg: BackgroundTasks):
    body = await request.json()
    bg.add_task(_process_ig_webhook, body)
    return {"ok": True}

# ── Sheets ───────────────────────────────────────────────────────────────────

@app.post("/api/sheets/export")
async def export_to_sheets():
    approved = await db.get_products(stage=ProductStage.REVIEWED.value, limit=500)
    posted = await db.get_products(stage=ProductStage.LIVE.value, limit=500)
    all_p = approved + posted
    if not all_p: return {"ok": True, "exported": 0}
    return await asyncio.to_thread(sheets.export, all_p)

@app.post("/api/sheets/backup")
async def backup_to_sheets():
    return await _backup_database_to_sheets()

@app.post("/api/sheets/restore")
async def restore_from_sheets():
    return await _restore_database_from_sheets()

# ── Background Helpers ────────────────────────────────────────────────────────

async def _run_scan(job_id: int, keywords: list, max_per_keyword: int, source: str) -> None:
    try:
        await run_pipeline(job_id, keywords, max_per_keyword, source=source)
        await _backup_products_to_sheets()
    except Exception as e:
        log.error("Scan %d failed: %s", job_id, e)
        await db.update_job(job_id, status="error")

async def _run_ingest(job_id: int, products: list) -> None:
    try:
        await process_scraped_products(job_id, products)
        await _backup_products_to_sheets()
    except Exception as e:
        log.error("Ingest %d failed: %s", job_id, e)
        await db.update_job(job_id, status="error")

async def _post_and_export(products: list) -> None:
    if not products: return
    try:
        settings = await _settings()
        results = await instagram.post_batch(products, settings)
        for p in products:
            res = next((r for r in results if r.product_id == p["id"]), None)
            if res and res.status in ("posted", "mock"):
                await db.set_stage(p["id"], ProductStage.LIVE.value)
                await db.log_post(p["id"])
        await asyncio.to_thread(sheets.append_rows, products)
        await _backup_products_to_sheets()
    except Exception as e:
        log.error("Post error: %s", e)

async def _process_ig_webhook(body: dict) -> None:
    pass

async def _verify_ingest_token(auth: Optional[str], token: Optional[str]) -> None:
    settings = await _settings()
    expected = str(settings.get("ingest_api_token") or "").strip()
    provided = (token or "").strip()
    if not provided and auth:
        _, _, t = auth.partition(" ")
        provided = t.strip()
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(401, "Invalid token")

# ── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}
