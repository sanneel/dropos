import logging
import os
import sys
import hmac
from contextlib import asynccontextmanager
from typing import List, Optional
from urllib.parse import unquote, urlparse

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))

from config.runtime import get_config, merge_env_with_settings, sanitize_settings
from database import db, init_db
from runner import process_scraped_products, run_pipeline
from scheduler import create_scheduler, get_scheduler_status
import instagram
import sheets
import httpx
from utils.google_auth import configure_google_credentials_from_env

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
    await _restore_database_from_sheets()
    merged_settings = merge_env_with_settings(await db.get_settings())
    sheets.configure(
        merged_settings.get("google_sheets_credentials") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
        merged_settings.get("google_sheets_id", ""),
    )
    if merged_settings.get("google_sheets_id"):
        ok = sheets.verify_writable()
        log.info("Google Sheets writable: %s", ok)
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

# Serve static files from frontend/
if _FRONTEND_ABS and os.path.isdir(_FRONTEND_ABS):
    app.mount("/static", StaticFiles(directory=_FRONTEND_ABS), name="static")
    assets_dir = os.path.join(_FRONTEND_ABS, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


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
        remote_settings = sheets.load_settings()
        if remote_settings:
            await db.update_settings(remote_settings)

        remote_products = sheets.load_products()
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


async def _backup_settings_to_sheets() -> dict:
    try:
        return sheets.save_settings(await db.get_settings())
    except Exception as exc:
        log.warning("Google Sheets settings backup failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def _backup_products_to_sheets() -> dict:
    try:
        return sheets.save_products(await db.get_all_products())
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
    stage: str = "pending", limit: int = 50, offset: int = 0, sort: str = "score"
):
    products = await db.get_products(stage=stage, limit=limit, offset=offset, sort=sort)
    total = await db.count_products(stage=stage)
    return {"products": products, "total": total}


@app.get("/api/products/{product_id}")
async def get_product(product_id: int):
    return await _get_product_or_404(product_id)


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
    _require_stage(p, "pending", "Cannot approve product in stage '{stage}'")
    await db.set_stage(product_id, "approved")
    await _backup_products_to_sheets()
    return {"ok": True}


@app.post("/api/approve")
async def approve_products(body: ApproveRequest):
    if len(body.product_ids) > 50:
        raise HTTPException(400, "Max 50 products at once")
    await _stage_products(body.product_ids, "approved", required_stage="pending")
    await _backup_products_to_sheets()
    return {"ok": True, "approved": len(body.product_ids)}


@app.post("/api/reject")
async def reject_products(body: BatchRejectRequest):
    if len(body.product_ids) > 50:
        raise HTTPException(400, "Max 50 products at once")
    reason = (body.reason or "").strip() or None
    await _stage_products(body.product_ids, "rejected", reason=reason)
    await _backup_products_to_sheets()
    return {"ok": True, "rejected": len(body.product_ids)}


@app.post("/api/products/{product_id}/post")
async def post_product(product_id: int, bg: BackgroundTasks):
    p = await _get_product_or_404(product_id)
    _require_stage(p, "approved", "Can only post approved products (stage: '{stage}')")
    await db.set_stage(product_id, "posted")
    await db.log_post(product_id)
    await _backup_products_to_sheets()
    bg.add_task(_post_and_export, [p])
    return {"ok": True}


@app.post("/api/post")
async def post_products(body: PostRequest, bg: BackgroundTasks):
    if len(body.product_ids) > 10:
        raise HTTPException(400, "Max 10 products at once")
    to_post = await _stage_products(
        body.product_ids,
        "posted",
        required_stage="approved",
        log_posts=True,
    )
    await _backup_products_to_sheets()
    bg.add_task(_post_and_export, to_post)
    return {"ok": True, "queued": len(to_post)}


@app.post("/api/products/{product_id}/reject")
async def reject_product(product_id: int, body: RejectRequest = None):
    await _get_product_or_404(product_id)
    reason = (body.reason or "").strip() if body else ""
    await db.set_stage(product_id, "rejected", reason=reason or None)
    await _backup_products_to_sheets()
    return {"ok": True}


@app.post("/api/products/{product_id}/reconsider")
async def reconsider_product(product_id: int):
    await _get_product_or_404(product_id)
    await db.set_stage(product_id, "pending")
    await _backup_products_to_sheets()
    return {"ok": True}


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
    stages = await db.get_pipeline(job_id)
    return {"job": job, "stages": stages}


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
    token = str(get_config("INSTAGRAM_ACCESS_TOKEN", settings.get("instagram_access_token")) or "").strip()
    if not token:
        raise HTTPException(400, "instagram_access_token not configured")

    graph = "https://graph.facebook.com/v21.0"
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


@app.get("/api/instagram/webhook")
async def ig_webhook_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification handshake."""
    settings = await _settings()
    verify_token = str(get_config("INSTAGRAM_WEBHOOK_TOKEN", settings.get("instagram_webhook_token") or "dropos_webhook_secret"))
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
    approved = await db.get_products(stage="approved", limit=500)
    posted = await db.get_products(stage="posted", limit=500)
    all_products = approved + posted
    if not all_products:
        return {"ok": True, "exported": 0, "message": "No products to export"}
    result = sheets.export(all_products)
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


# ── Background helpers ─────────────────────────────────────────────────────────

async def _run_scan(job_id: int, keywords: list, max_per_keyword: int, source: str = "1688") -> None:
    try:
        log.info("Job %d starting scan: keywords=%s source=%s max_per_keyword=%s", job_id, keywords, source, max_per_keyword)
        await run_pipeline(job_id, keywords, max_per_keyword, source=source)
        await _backup_products_to_sheets()
    except Exception as e:
        log.error("Pipeline job %d failed: %s", job_id, e)
        await db.update_job(job_id, status="error")


async def _run_ingest(job_id: int, products: list) -> None:
    try:
        log.info("Job %d starting local ingest: products=%d", job_id, len(products))
        await process_scraped_products(job_id, products)
        await _backup_products_to_sheets()
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
    ig_uid = str(get_config("INSTAGRAM_USER_ID", settings.get("instagram_user_id")) or "")
    comment_on = bool(get_config("INSTAGRAM_AUTO_REPLY_ENABLED", settings.get("instagram_auto_reply_enabled")))
    dm_on      = bool(get_config("INSTAGRAM_DM_REPLY_ENABLED", settings.get("instagram_dm_reply_enabled")))

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
        for r in errors:
            log.warning("Instagram error product=%s: %s", r.product_id, r.error)
        sheets.append_rows(products)
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
