import logging
import os
import sys
import hmac
import asyncio
from contextlib import asynccontextmanager
from typing import List, Optional
from urllib.parse import unquote, urlparse
import json

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
sys.path.insert(0, os.path.dirname(__file__))

# ProductStage lives in models.py — importing it here AFTER sys.path is set
# so it resolves correctly, and worker.py can also import it without pulling
# in main.py (which would create a circular import and crash at startup).
from models import ProductStage  # noqa: E402
from config.runtime import get_config, merge_env_with_settings, sanitize_settings
from image_editor import remove_text as clipdrop_remove_text
import uuid as _uuid
import os as _os
from database import db, init_db
from runner import process_scraped_products, run_pipeline
from scheduler import create_scheduler, get_scheduler_status
import instagram
import sheets
import ai_assistant
import httpx
from utils.google_auth import configure_google_credentials_from_env
from worker import run_worker_loop, process_queued_items
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# --- PATH RESOLUTION ---
# This file is in /app/backend/main.py
# Your shop is in /app/frontend/public/
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
PUBLIC_DIR = os.path.join(PROJECT_ROOT, "frontend", "public")

@app.get("/shop")
async def serve_shop():
    index_path = os.path.join(PUBLIC_DIR, "index.html")
    if not os.path.exists(index_path):
        # This will tell you EXACTLY where it's looking if it fails
        return {"status": "error", "path_searched": index_path}
    return FileResponse(index_path)

# Important: This tells the HTML where to find the CSS/JS
app.mount("/shop/assets", StaticFiles(directory=os.path.join(PUBLIC_DIR, "assets")), name="shop-assets")
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    await init_db()
    interrupted = await db.mark_active_jobs_interrupted()
    if interrupted:
        log.warning("Marked %d stale active job(s) as interrupted on startup", interrupted)
    configure_google_credentials_from_env()
    await _configure_sheets_from_settings()
    merged_settings = merge_env_with_settings(await db.get_settings())
    sheets.configure(
        merged_settings.get("google_sheets_credentials") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
        merged_settings.get("google_sheets_id", ""),
    )
    if merged_settings.get("google_sheets_id"):
        asyncio.create_task(_sync_sheets_after_startup())

    # ── Critical environment variable audit ───────────────────────────────────
    # Log CRITICAL (not raise) so Railway healthchecks still pass on partial
    # config, but the operator is clearly warned in the log stream.
    _required_env = {
        "DATABASE_URL":            "PostgreSQL connection string (Railway/Supabase)",
        "SUPABASE_URL":            "Supabase project URL (image storage)",
        "SUPABASE_SERVICE_ROLE_KEY": "Supabase service role key (image storage)",
    }
    for var, description in _required_env.items():
        if not os.getenv(var):
            log.critical(
                "MISSING ENV VAR: %s (%s) — some features will not work.",
                var, description,
            )

    # ── Start the autonomous worker loops ─────────────────────────────────────
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


app = FastAPI(title="DropOS Backoffice", lifespan=lifespan)

# In-memory store for cleaned images {product_id: bytes}
_cleaned_images: dict[int, bytes] = {}
_COLLAGE_DIR = "/tmp/dropos_collages"
_os.makedirs(_COLLAGE_DIR, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_CSSBUY_DEBUG_DIR = os.getenv("CSSBUY_DEBUG_DIR") or "/tmp/cssbuy_debug"
_FRONTEND_ABS = next(
    (os.path.abspath(p) for p in [
        os.path.join(_BACKEND_DIR, "frontend"),        # Railway: copied during build
        os.path.join(_BACKEND_DIR, "..", "frontend"),  # local dev
    ] if os.path.isdir(os.path.abspath(p))),
    None,
)
log.info("Frontend path: %s", _FRONTEND_ABS)

def _resolve_public() -> str | None:
    """Lazily resolve the public storefront directory at request time."""
    candidates = [
        os.path.join(_BACKEND_DIR, "frontend", "public"),
        os.path.join(_BACKEND_DIR, "..", "frontend", "public"),
    ]
    for p in candidates:
        abs_p = os.path.abspath(p)
        if os.path.isdir(abs_p):
            return abs_p
    return None


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    return "User-agent: *\nAllow: /\nUser-agent: facebookexternalhit\nAllow: /\n"


@app.get("/")
async def root():
    if _FRONTEND_ABS:
        index = os.path.join(_FRONTEND_ABS, "index.html")
        if os.path.exists(index):
            return FileResponse(index)
    return {"status": "DropOS backend running", "docs": "/docs", "api": "/api/stats"}


@app.get("/shop")
async def shop():
    """Public-facing couple's boutique storefront."""
    pub = _resolve_public()
    if pub:
        index = os.path.join(pub, "index.html")
        if os.path.exists(index):
            return FileResponse(index)
    # Debug: log all candidate paths to help diagnose
    log.warning(
        "[/shop] index.html not found. Backend dir: %s | Candidates: %s",
        _BACKEND_DIR,
        [os.path.abspath(p) for p in [
            os.path.join(_BACKEND_DIR, "frontend", "public", "index.html"),
            os.path.join(_BACKEND_DIR, "..", "frontend", "public", "index.html"),
        ]],
    )
    return {"status": "Storefront not available", "backend_dir": _BACKEND_DIR}


# Serve static files from frontend/
if _FRONTEND_ABS and os.path.isdir(_FRONTEND_ABS):
    app.mount("/static", StaticFiles(directory=_FRONTEND_ABS), name="static")
    assets_dir = os.path.join(_FRONTEND_ABS, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

# Serve public storefront assets at /shop/assets
# Use _FRONTEND_ABS as base since it's already resolved and proven to work
if _FRONTEND_ABS:
    _pub_assets_candidate = os.path.join(_FRONTEND_ABS, "public", "assets")
    if os.path.isdir(_pub_assets_candidate):
        app.mount("/shop/assets", StaticFiles(directory=_pub_assets_candidate), name="shop-assets")
        log.info("Public assets mounted at /shop/assets from %s", _pub_assets_candidate)
    else:
        log.warning("Public assets dir not found at %s", _pub_assets_candidate)


# ── Request models ─────────────────────────────────────────────────────────────

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


async def _settings() -> dict:
    return merge_env_with_settings(await db.get_settings())


def _remove_blank_sensitive_values(data: dict) -> None:
    for key in list(data.keys()):
        value = data[key]
        if key in _SENSITIVE_SETTING_FIELDS and isinstance(value, str) and not value.strip():
            data.pop(key)


def _active_job_error(active: dict, include_keywords: bool = False) -> HTTPException:
    detail = {
        "message": f"Job #{active['id']} is already running",
        "job_id": active["id"],
        "status": active.get("status", ""),
    }
    if include_keywords:
        detail["keywords"] = active.get("keywords", [])
    return HTTPException(409, detail)


async def _ensure_no_active_job(include_keywords: bool = False) -> None:
    active = await db.get_active_job()
    if active:
        raise _active_job_error(active, include_keywords)


def _local_scraping_error(message: str) -> HTTPException:
    return HTTPException(409, {"message": message, "local_scraping_only": True})


async def _ensure_server_scraping_enabled(message: str) -> None:
    if (await _settings()).get("local_scraping_only"):
        raise _local_scraping_error(message)


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
        if remote_settings or imported:
            log.info(
                "Restored Google Sheets backup: settings=%d products=%d",
                len(remote_settings),
                imported,
            )
        return {"ok": True, "settings": len(remote_settings), "products": imported}
    except Exception as exc:
        log.warning("Google Sheets restore skipped: %s", exc)
        return {"ok": False, "error": str(exc), "settings": 0, "products": 0}


async def _sync_sheets_after_startup() -> None:
    """Run slow Google Sheets checks after the web server is already healthy."""
    try:
        ok = await asyncio.to_thread(sheets.verify_writable)
        log.info("Google Sheets writable: %s", ok)
    except Exception as exc:
        log.warning("Google Sheets writable check skipped: %s", exc)
    result = await _restore_database_from_sheets()
    if result.get("ok") and (result.get("settings") or result.get("products")):
        await _configure_sheets_from_settings()


async def _backup_settings_to_sheets() -> dict:
    try:
        settings_snapshot = await db.get_settings()
        return await asyncio.to_thread(sheets.save_settings, settings_snapshot)
    except Exception as exc:
        log.warning("Google Sheets settings backup failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def _backup_products_to_sheets() -> dict:
    try:
        products_snapshot = await db.get_all_products()
        return await asyncio.to_thread(sheets.save_products, products_snapshot)
    except Exception as exc:
        log.warning("Google Sheets products backup failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def _backup_database_to_sheets() -> dict:
    settings_result = await _backup_settings_to_sheets()
    products_result = await _backup_products_to_sheets()
    return {
        "ok": bool(settings_result.get("ok")) and bool(products_result.get("ok")),
        "settings": settings_result,
        "products": products_result,
    }


def _pipeline_summary(job: dict, stages: dict) -> dict:
    raw = stages.get("raw_fetch", [])
    ai_pass = stages.get("ai_pass", [])
    rejected = [
        item
        for stage, items in stages.items()
        if stage != "ai_pass" and stage != "raw_fetch"
        for item in items
    ]
    ai_reject = stages.get("ai_reject", [])

    reason_counts: dict[str, int] = {}
    for item in rejected:
        reason = (item.get("filter_reason") or item.get("filter_stage") or "Filtered out").strip()
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    top_reasons = [
        {"reason": reason, "count": count}
        for reason, count in sorted(reason_counts.items(), key=lambda kv: kv[1], reverse=True)[:6]
    ]

    recommendations = []
    scraped = int(job.get("scraped") or len(raw) or 0)
    pass_rate = (len(ai_pass) / scraped * 100) if scraped else 0
    ai_reject_rate = (len(ai_reject) / max(len(ai_reject) + len(ai_pass), 1) * 100)

    if scraped and pass_rate < 3:
        recommendations.append("Very few fetched products reached review. Broaden keywords or lower MIN_SCORE slightly.")
    if ai_reject_rate > 70:
        recommendations.append("AI is rejecting most reviewed candidates. Lower MIN_SCORE by 0.5 or make the niche prompt more generous.")
    if reason_counts.get("margin too low", 0) > len(rejected) * 0.35:
        recommendations.append("Many products fail margin. Lower MIN_MARGIN or increase sell markup for cheaper items.")
    if reason_counts.get("spam/no-image/low-orders", 0) > len(rejected) * 0.35:
        recommendations.append("Many products fail basic quality filters. Try keywords closer to gift intent, like 'couple bracelet' or 'love letter gift'.")
    if reason_counts.get("duplicate product", 0) > len(rejected) * 0.25:
        recommendations.append("Duplicate rate is high. Add more varied keywords or reduce max products per keyword.")
    if not recommendations:
        recommendations.append("Filters look balanced. Improve results by adding more specific couple-gift keywords.")

    accepted_examples = [
        {
            "title": item.get("title", ""),
            "score": item.get("ai_score", 0),
            "visual": item.get("ai_visual", 0),
        }
        for item in sorted(ai_pass, key=lambda p: float(p.get("ai_score") or 0), reverse=True)[:5]
    ]

    return {
        "headline": f"{len(ai_pass)} products accepted for review from {scraped} fetched items.",
        "pass_rate": round(pass_rate, 1),
        "rejected": len(rejected),
        "top_reasons": top_reasons,
        "accepted_examples": accepted_examples,
        "recommendations": recommendations,
    }


def _items_to_stages(items: list) -> dict:
    stages: dict[str, list] = {}
    for item in items:
        stage = item.get("filter_stage") or "raw_fetch"
        stages.setdefault(stage, []).append(item)
    return stages


async def _create_scan_job(
    bg: BackgroundTasks,
    keywords: list,
    max_per_keyword: int,
    source: str,
) -> int:
    await _ensure_no_active_job(include_keywords=True)
    job_id = await db.create_job(keywords=keywords)
    bg.add_task(_run_scan, job_id, keywords, max_per_keyword, source)
    return job_id


async def _stage_products(
    product_ids: List[int],
    stage: str,
    *,
    required_stage: Optional[str] = None,
    reason: Optional[str] = None,
    log_posts: bool = False,
) -> list:
    changed = []
    for product_id in product_ids:
        product = await db.get_product(product_id)
        if not product:
            continue
        if required_stage and product.get("stage") != required_stage:
            continue
        await db.set_stage(product_id, stage, reason=reason)
        if log_posts:
            await db.log_post(product_id)
        changed.append(product)
    return changed


def _approval_stage(product: dict) -> str:
    return ProductStage.ENRICHED.value if product.get("has_chinese_text") else ProductStage.REVIEWED.value


# Settings

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


# ── Stats ──────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    return await db.get_stats()


# ── Products ───────────────────────────────────────────────────────────────────

@app.get("/api/products")
async def get_products(
    stage: str = ProductStage.SCRAPED.value, limit: int = 50, offset: int = 0, sort: str = "score"
):
    products = await db.get_products(stage=stage, limit=limit, offset=offset, sort=sort)
    total = await db.count_products(stage=stage)
    return {"products": products, "total": total}


@app.get("/api/products/{product_id}")
async def get_product(product_id: int):
    return await _get_product_or_404(product_id)


@app.patch("/api/products/{product_id}")
async def update_product(product_id: int, body: ProductUpdate):
    await _get_product_or_404(product_id)
    data = body.model_dump(exclude_none=True)
    if "hashtags" in data:
        data["hashtags_json"] = json.dumps(data.pop("hashtags") or [])
    updated = await db.update_product_fields(product_id, data)
    await _backup_products_to_sheets()
    return {"ok": True, "product": updated}


@app.get("/api/image")
async def proxy_image(url: str):
    src = unquote(url or "").strip()
    parsed = urlparse(src)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "Invalid image URL")
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(400, "Invalid image host")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(
                src,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "Referer": "https://www.1688.com/",
                },
            )
        if r.status_code != 200:
            raise HTTPException(r.status_code, "Image fetch failed")
        content_type = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if not content_type.startswith("image/"):
            raise HTTPException(400, "URL did not return an image")
        return Response(
            content=r.content,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Image proxy failed: {exc}")


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
    if len(body.product_ids) > 50:
        raise HTTPException(400, "Max 50 products at once")
    approved = 0
    text_edit = 0
    for pid in body.product_ids:
        product = await db.get_product(pid)
        if not product or product.get("stage") != ProductStage.SCRAPED.value:
            continue
        stage = _approval_stage(product)
        await db.set_stage(pid, stage)
        if stage == ProductStage.ENRICHED.value:
            text_edit += 1
        else:
            approved += 1
    await _backup_products_to_sheets()
    return {"ok": True, "approved": approved, "text_edit": text_edit}


@app.post("/api/reject")
async def reject_products(body: BatchRejectRequest):
    if len(body.product_ids) > 50:
        raise HTTPException(400, "Max 50 products at once")
    reason = (body.reason or "").strip() or None
    await _stage_products(body.product_ids, ProductStage.REJECTED.value, reason=reason)
    await _backup_products_to_sheets()
    return {"ok": True, "rejected": len(body.product_ids)}


@app.post("/api/products/{product_id}/post")
async def post_product(product_id: int, bg: BackgroundTasks):
    p = await _get_product_or_404(product_id)
    _require_stage(p, ProductStage.REVIEWED.value, "Can only post approved products (stage: '{stage}')")
    bg.add_task(_post_and_export, [p])
    return {"ok": True, "queued": 1}


@app.post("/api/post")
async def post_products(body: PostRequest, bg: BackgroundTasks):
    if len(body.product_ids) > 10:
        raise HTTPException(400, "Max 10 products at once")
    to_post = await _stage_products(
        body.product_ids, ProductStage.REVIEWED.value, required_stage=ProductStage.REVIEWED.value
    )
    bg.add_task(_post_and_export, to_post)
    return {"ok": True, "queued": len(to_post)}

class BulkStatusRequest(BaseModel):
    product_ids: list[int]
    stage: ProductStage

@app.post("/api/products/bulk-status")
async def bulk_status(body: BulkStatusRequest):
    for pid in body.product_ids:
        await db.set_stage(pid, body.stage.value)
    await _backup_products_to_sheets()
    return {"ok": True}

@app.put("/api/products/{product_id}")
async def update_product(product_id: int, body: dict):
    await db.update_product_fields(product_id, body)
    await _backup_products_to_sheets()
    return {"ok": True}


@app.post("/api/products/{product_id}/reject")
async def reject_product(product_id: int, body: RejectRequest = None):
    await _get_product_or_404(product_id)
    reason = (body.reason or "").strip() if body else ""
    await db.set_stage(product_id, ProductStage.REJECTED.value, reason=reason or None)
    await _backup_products_to_sheets()
    return {"ok": True}


@app.post("/api/products/{product_id}/reconsider")
async def reconsider_product(product_id: int):
    await _get_product_or_404(product_id)
    await db.set_stage(product_id, ProductStage.SCRAPED.value)
    await _backup_products_to_sheets()
    return {"ok": True}


@app.post("/api/products/{product_id}/text-edited")
async def mark_text_edited(product_id: int):
    p = await _get_product_or_404(product_id)
    _require_stage(p, ProductStage.ENRICHED.value, "Can only mark text-edited products from stage '{stage}'")
    await db.update_product_fields(product_id, {
        "has_chinese_text": False,
        "chinese_text_note": "",
    })
    await db.set_stage(product_id, ProductStage.REVIEWED.value)
    await _backup_products_to_sheets()
    return {"ok": True}


@app.post("/api/products/{product_id}/remove-text")
async def remove_product_text(product_id: int):
    """Call Clipdrop to remove Chinese text/watermarks from product's first image."""
    p = await _get_product_or_404(product_id)
    settings = await db.get_settings()
    merged = merge_env_with_settings(settings)
    clipdrop_key = merged.get("clipdrop_key", "")
    if not clipdrop_key:
        raise HTTPException(400, "Clipdrop API key not configured — add clipdrop_key in Settings")

    images = p.get("images") or []
    image_url = images[0] if images else ""
    if not image_url:
        raise HTTPException(400, "Product has no image to clean")

    cleaned_bytes = await clipdrop_remove_text(image_url, clipdrop_key)
    if not cleaned_bytes:
        raise HTTPException(502, "Clipdrop failed — check API key or try a different image")

    _cleaned_images[product_id] = cleaned_bytes
    disk_path = f"{_COLLAGE_DIR}/cleaned_{product_id}.jpg"
    with open(disk_path, "wb") as fh:
        fh.write(cleaned_bytes)

    base = str(get_config("PUBLIC_BASE_URL", merged.get("public_base_url", "")) or "").rstrip("/")
    if not base:
        base = str(get_config("RAILWAY_PUBLIC_DOMAIN", "") or "").strip()
        if base and not base.startswith("http"):
            base = f"https://{base}"
        base = base.rstrip("/")

    new_url = f"{base}/api/products/{product_id}/cleaned-image" if base else f"/api/products/{product_id}/cleaned-image"

    next_images = [new_url] + [img for img in images if img and img != image_url]
    await db.update_product_fields(product_id, {
        "images_json": json.dumps(next_images),
        "has_chinese_text": False,
        "chinese_text_note": "",
    })
    await db.set_stage(product_id, ProductStage.REVIEWED.value)
    await _backup_products_to_sheets()
    return {"ok": True, "image_url": new_url, "product": await db.get_product(product_id)}


@app.get("/api/products/{product_id}/cleaned-image")
async def serve_cleaned_image(product_id: int):
    """Serve Clipdrop-cleaned image bytes."""
    data = _cleaned_images.get(product_id)
    if not data:
        disk_path = f"{_COLLAGE_DIR}/cleaned_{product_id}.jpg"
        if _os.path.exists(disk_path):
            with open(disk_path, "rb") as fh:
                data = fh.read()
    if not data:
        raise HTTPException(404, "Cleaned image not found — please clean again")
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.patch("/api/products/{product_id}/note")
async def update_note(product_id: int, body: NoteUpdate):
    await _get_product_or_404(product_id)
    await db.update_product_note(product_id, body.note)
    await _backup_products_to_sheets()
    return {"ok": True}


# ── Scan / Jobs ────────────────────────────────────────────────────────────────

@app.post("/api/scan")
async def start_scan(body: ScanRequest, bg: BackgroundTasks):
    await _ensure_server_scraping_enabled(
        "Server-side scraping is disabled. Run backend/local_scrape_upload.py on your local machine instead."
    )
    job_id = await _create_scan_job(bg, body.keywords, body.max_per_keyword, body.source)
    return {"job_id": job_id, "status": "started"}


@app.post("/api/ingest/products")
async def ingest_products(
    body: IngestProductsRequest,
    bg: BackgroundTasks,
    authorization: Optional[str] = Header(default=None),
    x_ingest_token: Optional[str] = Header(default=None),
):
    await _verify_ingest_token(authorization, x_ingest_token)
    if not body.products:
        raise HTTPException(400, "No products supplied")
    if len(body.products) > 2000:
        raise HTTPException(400, "Max 2000 products per upload")
    await _ensure_no_active_job()
    keywords = body.keywords or sorted({p.get("keyword", "") for p in body.products if p.get("keyword")})
    if body.source and keywords:
        keywords = [f"{kw} ({body.source})" for kw in keywords]
    job_id = await db.create_job(keywords=keywords or ["local upload"])
    bg.add_task(_run_ingest, job_id, body.products)
    return {"job_id": job_id, "status": "uploaded", "products": len(body.products)}


@app.get("/api/jobs")
async def get_jobs(limit: int = 20):
    return await db.get_jobs(limit)


@app.delete("/api/jobs")
async def clear_jobs():
    counts = await db.clear_scan_history()
    return {"ok": True, "deleted": counts}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: int):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404)
    return job


@app.get("/api/jobs/{job_id}/pipeline")
async def get_job_pipeline(job_id: int):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404)
    items = await db.get_scan_items(job_id)
    stages: dict[str, list] = {}
    for item in items:
        stage = item.get("filter_stage") or "raw_fetch"
        stages.setdefault(stage, []).append(item)
    return {"job": job, "stages": stages, "summary": _pipeline_summary(job, stages)}


@app.get("/api/jobs/{job_id}/items")
async def get_job_items(job_id: int):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(404)
    items = await db.get_scan_items(job_id)
    return {"job": job, "items": items, "summary": _pipeline_summary(job, _items_to_stages(items))}


@app.get("/api/debug/cssbuy")
@app.get("/api/debug/cssbuy/files")
async def cssbuy_debug_files():
    files = []
    debug_dir = os.path.abspath(_CSSBUY_DEBUG_DIR)
    if not os.path.isdir(debug_dir):
        return []
    for name in os.listdir(debug_dir):
        if name.startswith("cssbuy_") and name.rsplit(".", 1)[-1] in {"png", "html", "txt", "json"}:
            path = os.path.join(debug_dir, name)
            files.append({
                "name": name,
                "size": os.path.getsize(path),
                "modified": os.path.getmtime(path),
                "url": f"/api/debug/cssbuy/files/{name}",
            })
    return sorted(files, key=lambda f: f["modified"], reverse=True)


@app.get("/api/debug/cssbuy/{filename}")
@app.get("/api/debug/cssbuy/files/{filename}")
async def get_cssbuy_debug_file(filename: str):
    if "/" in filename or "\\" in filename or not filename.startswith("cssbuy_"):
        raise HTTPException(400, "Invalid filename")
    debug_dir = os.path.abspath(_CSSBUY_DEBUG_DIR)
    path = os.path.abspath(os.path.join(debug_dir, filename))
    if os.path.commonpath([debug_dir, path]) != debug_dir:
        raise HTTPException(400, "Invalid filename")
    if not os.path.isfile(path):
        raise HTTPException(404)
    return FileResponse(path)


# ── Scheduler ──────────────────────────────────────────────────────────────────

@app.get("/api/scheduler/status")
async def scheduler_status():
    return get_scheduler_status(_scheduler)


@app.post("/api/scheduler/trigger")
async def scheduler_trigger(bg: BackgroundTasks):
    """Manually fire a scheduled scan now (uses stored scan_keywords)."""
    settings = await _settings()
    if settings.get("local_scraping_only"):
        raise _local_scraping_error(
            "Scheduled server-side scraping is disabled. Run backend/local_scrape_upload.py locally."
        )
    raw = get_config("SCAN_KEYWORDS", settings.get("scan_keywords", []))
    keywords: list = raw if isinstance(raw, list) else [raw]
    if not keywords:
        keywords = ["aesthetic home decor"]
    scan_src = str(get_config("CSSBUY_SOURCE", settings.get("cssbuy_source", "1688")))
    job_id = await _create_scan_job(bg, keywords, 50, scan_src)
    return {"ok": True, "job_id": job_id, "keywords": keywords}


# ── Instagram ─────────────────────────────────────────────────────────────────

@app.get("/api/instagram/accounts")
async def instagram_accounts():
    """
    Resolve the Instagram Business Account ID from the stored Page Access Token.
    Calls GET /me/accounts to list Facebook Pages, then fetches the linked
    Instagram Business Account ID for each page.
    """
    import httpx as _httpx
    settings = await _settings()
    token = "".join(str(settings.get("instagram_access_token") or "").split())
    if not token:
        raise HTTPException(400, "instagram_access_token not configured")

    version = str(get_config("META_GRAPH_VERSION", settings.get("meta_graph_version", "v23.0")) or "v23.0")
    if not version.startswith("v"):
        version = f"v{version}"
    graph = f"https://graph.facebook.com/{version}"
    try:
        async with _httpx.AsyncClient(timeout=15) as client:
            # 1. List all Facebook Pages the token has access to
            r = await client.get(f"{graph}/me/accounts", params={"access_token": token})
            body = r.json()
            if "error" in body:
                raise HTTPException(400, body["error"].get("message", str(body["error"])))

            pages = body.get("data", [])
            results = []
            for page in pages:
                page_id = page.get("id")
                page_name = page.get("name", "")
                # 2. Fetch the linked Instagram Business Account for each page
                r2 = await client.get(
                    f"{graph}/{page_id}",
                    params={"fields": "instagram_business_account", "access_token": token},
                )
                b2 = r2.json()
                ig = b2.get("instagram_business_account")
                results.append({
                    "page_id":   page_id,
                    "page_name": page_name,
                    "instagram_business_account_id": ig.get("id") if ig else None,
                })
        return {"accounts": results}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.get("/api/instagram/diagnostics")
async def instagram_diagnostics(product_id: Optional[int] = None):
    settings = await _settings()
    token = "".join(str(settings.get("instagram_access_token") or "").split())
    user_id = str(settings.get("instagram_user_id") or "").strip()
    version = str(get_config("META_GRAPH_VERSION", settings.get("meta_graph_version", "v23.0")) or "v23.0")
    if not version.startswith("v"):
        version = f"v{version}"
    graph = f"https://graph.facebook.com/{version}"
    result = {
        "token_configured": bool(token),
        "instagram_user_id": user_id,
        "graph_version": version,
        "account_ok": False,
        "image_ok": None,
        "errors": [],
    }
    if not token or not user_id:
        result["errors"].append("Instagram access token or user ID is missing from settings")
        return result

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            account_resp = await client.get(
                f"{graph}/{user_id}",
                params={"fields": "id,username,account_type", "access_token": token},
            )
            account_body = account_resp.json()
            if "error" in account_body:
                result["errors"].append(account_body["error"].get("message", str(account_body["error"])))
            else:
                result["account_ok"] = True
                result["account"] = account_body

            if product_id:
                product = await _get_product_or_404(product_id)
                src = (product.get("images") or [""])[0]
                if src:
                    image_resp = await client.get(src, headers={"User-Agent": "Mozilla/5.0"})
                    content_type = image_resp.headers.get("content-type", "")
                    result["image_ok"] = image_resp.status_code == 200 and content_type.startswith("image/")
                    result["image_status"] = image_resp.status_code
                    result["image_content_type"] = content_type
                else:
                    result["image_ok"] = False
                    result["errors"].append("Product has no image URL")
    except Exception as exc:
        result["errors"].append(str(exc))
    return result


@app.get("/api/instagram/webhook")
async def ig_webhook_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification handshake."""
    settings = await _settings()
    verify_token = str(settings.get("instagram_webhook_token") or "dropos_webhook_secret")
    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(403, "Webhook verification failed - check your verify token")


@app.post("/api/instagram/webhook")
async def ig_webhook_receive(request: Request, bg: BackgroundTasks):
    """Receive Instagram comment events from Meta and process in background."""
    body = await request.json()
    bg.add_task(_process_ig_webhook, body)
    return {"ok": True}


@app.get("/api/instagram/reply-log")
async def ig_reply_log():
    return await db.get_comment_reply_log(limit=100)


# ── Google Sheets ──────────────────────────────────────────────────────────────

@app.post("/api/sheets/export")
async def export_to_sheets():
    """Export all approved + posted products to Google Sheets."""
    approved = await db.get_products(stage=ProductStage.REVIEWED.value, limit=500)
    posted = await db.get_products(stage=ProductStage.LIVE.value, limit=500)
    all_products = approved + posted
    if not all_products:
        return {"ok": True, "exported": 0, "message": "No products to export"}
    result = await asyncio.to_thread(sheets.export, all_products)
    return result


@app.post("/api/sheets/backup")
async def backup_to_sheets():
    """Save settings and product database snapshots to Google Sheets."""
    return await _backup_database_to_sheets()


@app.post("/api/sheets/restore")
async def restore_from_sheets():
    """Restore settings and product database snapshots from Google Sheets."""
    result = await _restore_database_from_sheets()
    await _configure_sheets_from_settings()
    return result




# ── Analytics ──────────────────────────────────────────────────────────────────

@app.get("/api/analytics")
async def get_analytics():
    """Return analytics data for the dashboard."""
    data = await db.get_analytics()
    stats_data = await db.get_stats()
    jobs = await db.get_jobs(5)
    data["stats"] = stats_data
    data["recent_jobs"] = jobs[:5]
    return data


# ── AI Chat Assistant ──────────────────────────────────────────────────────────

class AIChatEditItem(BaseModel):
    id: int
    title: Optional[str] = None
    price: Optional[float] = None
    caption: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    reconsider: Optional[bool] = False
    execute_edits: Optional[bool] = False
    execute_approvals: Optional[bool] = False


@app.post("/api/ai/test")
async def test_ai_key(body: dict):
    """Test if a Gemini or Groq API key works."""
    import httpx, time
    provider = (body.get("provider") or "gemini").lower()
    settings = await _settings()

    if provider == "gemini":
        api_key = body.get("key") or settings.get("gemini_key") or ""
        if not api_key:
            return {"ok": False, "error": "No Gemini key — paste your key first or save it in Settings"}
        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                    headers={"x-goog-api-key": api_key, "content-type": "application/json"},
                    json={"contents": [{"parts": [{"text": "Say OK"}]}],
                          "generationConfig": {"max_output_tokens": 10}},
                )
            ms = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                return {"ok": True, "model": "gemini-2.5-flash", "latency_ms": ms}
            else:
                err = resp.json().get("error", {}).get("message", resp.text[:120])
                return {"ok": False, "error": f"Gemini API error: {err}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    elif provider == "groq":
        api_key = body.get("key") or settings.get("groq_key") or ""
        if not api_key:
            return {"ok": False, "error": "No Groq key — paste your key first or save it in Settings"}
        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": "llama-3.3-70b-versatile",
                          "messages": [{"role": "user", "content": "Say OK"}],
                          "max_tokens": 5},
                )
            ms = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                return {"ok": True, "model": "llama-3.3-70b-versatile", "latency_ms": ms}
            else:
                err = resp.json().get("error", {}).get("message", resp.text[:120])
                return {"ok": False, "error": f"Groq API error: {err}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {"ok": False, "error": "Unknown provider — use 'gemini' or 'groq'"}


# ── Collage ────────────────────────────────────────────────────────────────────

class CollageRequest(BaseModel):
    product_ids: list[int]
    caption: Optional[str] = None


@app.post("/api/collage/post")
async def post_collage(body: CollageRequest):
    """Generate a 2×3 product collage and post to Instagram."""
    try:
        from collage import create_collage
    except ImportError:
        raise HTTPException(501, "Pillow not installed — add Pillow>=10.0.0 to requirements.txt and redeploy")

    if len(body.product_ids) < 2:
        raise HTTPException(400, "Need at least 2 product IDs")

    products = []
    for pid in body.product_ids[:6]:
        try:
            p = await db.get_product(pid)
            if p:
                products.append(p)
        except Exception:
            pass

    if not products:
        raise HTTPException(404, "No valid products found")

    settings = await db.get_settings()
    merged = merge_env_with_settings(settings)

    base = str(merged.get("public_base_url", "")).rstrip("/")
    if not base:
        base = str(get_config("PUBLIC_BASE_URL", "") or get_config("RAILWAY_PUBLIC_DOMAIN", "") or "").strip()
        if base and not base.startswith("http"):
            base = f"https://{base}"
        base = base.rstrip("/")

    image_urls = []
    for p in products:
        imgs = p.get("images") or []
        url = p.get("image_url") or (imgs[0] if imgs else "")
        if url and url.startswith("/api/products") and base:
            url = f"{base}{url}"
        if url:
            image_urls.append(url)

    if not image_urls:
        raise HTTPException(400, "Could not find image URLs for collage")

    collage_bytes = await create_collage(image_urls)
    if not collage_bytes:
        raise HTTPException(502, "Collage generation failed — ensure Pillow is installed")

    filename = f"collage_{_uuid.uuid4().hex[:8]}.jpg"
    collage_path = f"{_COLLAGE_DIR}/{filename}"
    with open(collage_path, "wb") as fh:
        fh.write(collage_bytes)

    collage_url = f"{base}/api/collages/{filename}" if base else f"/api/collages/{filename}"

    first = products[0]
    caption = body.caption or first.get("caption") or first.get("product_name") or "New arrivals ✨"
    names = [p.get("product_name") or p.get("title_translated") or "" for p in products]
    names_str = "\n".join(f"• {n}" for n in names if n)
    full_caption = f"{caption}\n\n{names_str}" if names_str else caption

    from instagram import post_product
    results = await post_product(
        {"id": -1, "images": [collage_url], "caption": full_caption},
        settings=merged,
    )
    if results and results[0].status in (ProductStage.LIVE.value, "mock"):
        for p in products:
            try:
                await db.set_stage(p["id"], ProductStage.LIVE.value)
            except Exception:
                pass
        await _backup_products_to_sheets()
        return {"ok": True, "post_url": results[0].post_url, "collage_url": collage_url}
    else:
        err = results[0].error if results else "Unknown error"
        raise HTTPException(502, f"Instagram posting failed: {err}")


@app.get("/api/collages/{filename}")
async def serve_collage(filename: str):
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    path = f"{_COLLAGE_DIR}/{filename}"
    if not _os.path.exists(path):
        raise HTTPException(404, "Collage not found")
    with open(path, "rb") as fh:
        data = fh.read()
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.post("/api/ai/chat")
async def ai_chat(body: ChatRequest):
    """AI chat assistant — reviews products, answers questions, resurfaces gems."""
    if not body.message or not body.message.strip():
        raise HTTPException(400, "message is required")

    settings = await _settings()
    stats_data = await db.get_stats()
    jobs = await db.get_jobs(3)
    last_job = jobs[0] if jobs else {}
    rejected_sample = await db.get_rejected_sample(30)

    # Fetch approved and pending samples for richer context
    approved_raw = await db.get_products(stage=ProductStage.REVIEWED.value, limit=20, offset=0)
    pending_raw = await db.get_products(stage=ProductStage.SCRAPED.value, limit=50, offset=0)
    approved_sample = approved_raw.get("items", []) if isinstance(approved_raw, dict) else approved_raw[:20]
    pending_sample = pending_raw.get("items", []) if isinstance(pending_raw, dict) else pending_raw[:50]

    # Slim down the samples to reduce token usage
    def slim(products, fields=("id","title_translated","sell_price_eur","score","niche_fit","category","stage","caption","image_url","images")):
        import json as _json
        rows = []
        for p in products:
            row = {k: p.get(k) for k in fields if p.get(k) is not None}
            # Ensure image_url is populated — fall back to first image in array
            if not row.get("image_url"):
                imgs = row.get("images")
                if isinstance(imgs, str):
                    try: imgs = _json.loads(imgs)
                    except Exception: imgs = []
                if isinstance(imgs, list) and imgs:
                    row["image_url"] = imgs[0]
            # Keep images as a proper list (not JSON string) for the frontend
            if "images" in row and isinstance(row["images"], str):
                try: row["images"] = _json.loads(row["images"])
                except Exception: row["images"] = []
            rows.append(row)
        return rows

    # Compute top rejection reasons from sample
    reason_counts: dict = {}
    for p in rejected_sample:
        r = (p.get("rejection_reason") or "Unknown").strip()
        reason_counts[r] = reason_counts.get(r, 0) + 1
    recent_rejection_reasons = [
        {"reason": k, "count": v}
        for k, v in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:6]
    ]

    context = {
        "stats": stats_data,
        "last_job": last_job,
        "rejected_sample": slim(rejected_sample),
        "approved_sample": slim(approved_sample),
        "pending_sample": slim(pending_sample),
        "recent_rejection_reasons": recent_rejection_reasons,
    }

    result = await ai_assistant.chat(body.message, context, settings)

    # Execute: reconsider
    if body.reconsider and result.get("action") == "reconsider" and result.get("product_ids"):
        reconsidered = 0
        for pid in result["product_ids"][:20]:
            try:
                await db.set_stage(int(pid), ProductStage.SCRAPED.value)
                reconsidered += 1
            except Exception:
                pass
        if reconsidered:
            await _backup_products_to_sheets()
            result["reconsidered"] = reconsidered

    # Execute: reject_products
    if body.reconsider and result.get("action") == "reject_products" and result.get("product_ids"):
        rejected_count = 0
        for pid in result["product_ids"][:50]:
            try:
                await db.set_stage(int(pid), ProductStage.REJECTED.value)
                rejected_count += 1
            except Exception:
                pass
        if rejected_count:
            result["rejected_count"] = rejected_count

    # Execute: approve_products
    if body.execute_approvals and result.get("action") == "approve_products" and result.get("product_ids"):
        approved_count = 0
        for pid in result["product_ids"][:20]:
            try:
                product = await db.get_product(int(pid))
                if product and product.get("stage") == ProductStage.SCRAPED.value:
                    stage = _approval_stage(product)
                    await db.set_stage(int(pid), stage)
                    approved_count += 1
            except Exception:
                pass
        if approved_count:
            await _backup_products_to_sheets()
            result["approved_count"] = approved_count

    # Execute: edit_products
    if body.execute_edits and result.get("action") == "edit_products" and result.get("edits"):
        edited_count = 0
        for edit in result["edits"][:20]:
            try:
                pid = int(edit.get("id", 0))
                if not pid:
                    continue
                fields = {}
                if edit.get("title"):
                    fields["title_translated"] = edit["title"]
                if edit.get("price") is not None:
                    fields["sell_price_eur"] = float(edit["price"])
                if edit.get("caption"):
                    fields["caption"] = edit["caption"]
                if fields:
                    await db.update_product_fields(pid, fields)
                    edited_count += 1
            except Exception:
                pass
        if edited_count:
            await _backup_products_to_sheets()
            result["edited_count"] = edited_count

    return result

# ── Background helpers ─────────────────────────────────────────────────────────

async def _run_scan(job_id: int, keywords: list, max_per_keyword: int, source: str = "1688") -> None:
    try:
        log.info("Job %d starting scan: keywords=%s source=%s max_per_keyword=%s", job_id, keywords, source, max_per_keyword)
        await run_pipeline(job_id, keywords, max_per_keyword, source=source)
        await _backup_products_to_sheets()
        scan_items = await db.get_scan_items(job_id)
        await asyncio.to_thread(sheets.save_scan_items, job_id, scan_items)
    except Exception as e:
        log.error("Pipeline job %d failed: %s", job_id, e)
        await db.update_job(job_id, status="error")


async def _run_ingest(job_id: int, products: list) -> None:
    try:
        log.info("Job %d starting local ingest: products=%d", job_id, len(products))
        await process_scraped_products(job_id, products)
        await _backup_products_to_sheets()
        scan_items = await db.get_scan_items(job_id)
        await asyncio.to_thread(sheets.save_scan_items, job_id, scan_items)
    except Exception as e:
        log.error("Ingest job %d failed: %s", job_id, e)
        await db.update_job(job_id, status="error")


async def _verify_ingest_token(
    authorization: Optional[str],
    x_ingest_token: Optional[str],
) -> None:
    settings = await _settings()
    expected = str(get_config("INGEST_API_TOKEN", settings.get("ingest_api_token", "")) or "").strip()
    if not expected:
        raise HTTPException(503, "INGEST_API_TOKEN is not configured on the website")
    provided = (x_ingest_token or "").strip()
    if not provided and authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer":
            provided = token.strip()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(401, "Invalid ingest token")


async def _process_ig_webhook(body: dict) -> None:
    if body.get("object") != "instagram":
        return

    settings = await _settings()
    ig_uid = str(settings.get("instagram_user_id") or "")
    comment_on = bool(settings.get("instagram_auto_reply_enabled"))
    dm_on      = bool(settings.get("instagram_dm_reply_enabled"))

    if not comment_on and not dm_on:
        return

    comment_rules = settings.get("instagram_reply_rules") or []
    dm_rules = settings.get("instagram_dm_rules") or []

    for entry in body.get("entry", []):

        # ── Comment events (in "changes") ──────────────────────────────────────
        if comment_on:
            for change in entry.get("changes", []):
                if change.get("field") != "comments":
                    continue
                value      = change.get("value", {})
                comment_id = value.get("id")
                text       = value.get("text", "")
                from_id    = str((value.get("from") or {}).get("id", ""))

                if not comment_id or from_id == ig_uid:
                    continue
                if await db.has_replied_to_comment(comment_id):
                    continue

                reply = instagram.match_reply_rule(text, comment_rules)
                if not reply:
                    continue

                success = await instagram.reply_to_comment(comment_id, reply, settings)
                if success:
                    await db.log_comment_reply(comment_id, reply[:80], "comment")
                    log.info("Auto-replied to comment %s: %.50s", comment_id, reply)

        # ── DM events (in "messaging") ─────────────────────────────────────────
        if dm_on:
            for msg_event in entry.get("messaging", []):
                sender_id = str((msg_event.get("sender") or {}).get("id", ""))
                message   = msg_event.get("message", {})
                msg_id    = message.get("mid", "")
                text      = message.get("text", "")

                if not sender_id or not msg_id or not text:
                    continue
                if sender_id == ig_uid:
                    continue  # don't reply to our own messages
                if message.get("is_echo"):
                    continue  # echoes of our own sent messages
                if await db.has_replied_to_comment(msg_id):
                    continue  # already replied

                reply = instagram.match_reply_rule(text, dm_rules)
                if not reply:
                    continue

                success = await instagram.reply_to_dm(sender_id, reply, settings)
                if success:
                    await db.log_comment_reply(msg_id, reply[:80], "dm")
                    log.info("Auto-replied to DM from %s: %.50s", sender_id, reply)


async def _post_and_export(products: list) -> None:
    if not products:
        return
    try:
        settings = await _settings()
        results = await instagram.post_batch(products, settings)
        posted  = sum(1 for r in results if r.status == "posted")
        mocked  = sum(1 for r in results if r.status == "mock")
        errors  = [r for r in results if r.status == "error"]
        log.info("Instagram: posted=%d mock=%d errors=%d", posted, mocked, len(errors))
        result_by_id = {r.product_id: r for r in results}
        for product in products:
            result = result_by_id.get(product.get("id"))
            if not result:
                continue
            if result.status in {"posted", "mock"}:
                await db.set_stage(product["id"], "posted")
                await db.log_post(product["id"])
            else:
                await db.update_product_note(product["id"], f"Instagram post failed: {result.error or 'unknown error'}")
        for r in errors:
            log.warning("Instagram error product=%s: %s", r.product_id, r.error)
        await asyncio.to_thread(sheets.append_rows, products)
        await _backup_products_to_sheets()
    except Exception as e:
        log.error("Post/export error: %s", e)


@app.get("/test-playwright")
async def test_playwright():
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise HTTPException(500, f"Playwright import failed: {exc}")
    timeout_ms = int(get_config("PLAYWRIGHT_TIMEOUT", 30000))
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            page = await browser.new_page()
            await page.goto("https://example.com", timeout=timeout_ms)
            title = await page.title()
            await browser.close()
            return {"ok": True, "title": title}
    except Exception as exc:
        log.exception("Playwright test failed")
        raise HTTPException(500, f"Playwright test failed: {exc}")


@app.get("/health-playwright")
async def health_playwright():
    result = await test_playwright()
    return {"status": "ok", **result}
