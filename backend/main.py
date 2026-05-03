import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))

from config.runtime import get_config, merge_env_with_settings, sanitize_settings
from database import db, init_db
from runner import run_pipeline
from scheduler import create_scheduler, get_scheduler_status
import instagram
import sheets
from utils.google_auth import configure_google_credentials_from_env

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
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    await init_db()
    interrupted = await db.mark_active_jobs_interrupted()
    if interrupted:
        log.warning("Marked %d stale active job(s) as interrupted on startup", interrupted)
    configure_google_credentials_from_env()
    merged_settings = merge_env_with_settings(await db.get_settings())
    sheets.configure(
        merged_settings.get("google_sheets_credentials") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
        merged_settings.get("google_sheets_id", ""),
    )
    if merged_settings.get("google_sheets_id"):
        ok = sheets.verify_writable()
        log.info("Google Sheets writable: %s", ok)
    _scheduler = create_scheduler()
    _scheduler.start()
    log.info("Scheduler started — jobs: %s", [j.get("id") for j in _scheduler.get_jobs()])
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


_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
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


# ── Request models ─────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    keywords: List[str]
    max_per_keyword: int = 50
    source: str = "taobao"


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
    gemini_model: Optional[str] = None
    target_audience: Optional[str] = None
    sell_price_min: Optional[float] = None
    sell_price_max: Optional[float] = None
    example_products: Optional[str] = None


# ── Settings ───────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    settings = merge_env_with_settings(await db.get_settings())
    return sanitize_settings(settings)


@app.patch("/api/settings")
async def update_settings(body: SettingsUpdate):
    data = body.model_dump(exclude_none=True)
    for key in list(data.keys()):
        if key in _SENSITIVE_SETTING_FIELDS and isinstance(data[key], str) and not data[key].strip():
            data.pop(key)
    await db.update_settings(data)

    # Reconfigure sheets exporter if credentials changed
    merged = merge_env_with_settings(await db.get_settings())
    gid = merged.get("google_sheets_id", "")
    gcreds = merged.get("google_sheets_credentials") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
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
        p = await db.get_product(pid)
        if p and p.get("stage") == "pending":
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
    active = await db.get_active_job()
    if active:
        raise HTTPException(
            409,
            {
                "message": f"Job #{active['id']} is already running",
                "job_id": active["id"],
                "keywords": active.get("keywords", []),
                "status": active.get("status", ""),
            },
        )
    job_id = await db.create_job(keywords=body.keywords)
    bg.add_task(_run_scan, job_id, body.keywords, body.max_per_keyword, body.source)
    return {"job_id": job_id, "status": "started"}


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
async def cssbuy_debug_files():
    files = []
    for name in os.listdir(_BACKEND_DIR):
        if name.startswith("cssbuy_") and name.rsplit(".", 1)[-1] in {"png", "html", "txt", "json"}:
            path = os.path.join(_BACKEND_DIR, name)
            files.append({
                "name": name,
                "size": os.path.getsize(path),
                "modified": os.path.getmtime(path),
                "url": f"/api/debug/cssbuy/{name}",
            })
    return sorted(files, key=lambda f: f["modified"], reverse=True)


@app.get("/api/debug/cssbuy/{filename}")
async def get_cssbuy_debug_file(filename: str):
    if "/" in filename or "\\" in filename or not filename.startswith("cssbuy_"):
        raise HTTPException(400, "Invalid filename")
    path = os.path.join(_BACKEND_DIR, filename)
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
    active = await db.get_active_job()
    if active:
        raise HTTPException(
            409,
            {
                "message": f"Job #{active['id']} is already running",
                "job_id": active["id"],
                "keywords": active.get("keywords", []),
                "status": active.get("status", ""),
            },
        )
    settings = merge_env_with_settings(await db.get_settings())
    raw = get_config("SCAN_KEYWORDS", settings.get("scan_keywords", []))
    keywords: list = raw if isinstance(raw, list) else [raw]
    if not keywords:
        keywords = ["aesthetic home decor"]
    job_id = await db.create_job(keywords=keywords)
    scan_src = str(get_config("CSSBUY_SOURCE", settings.get("cssbuy_source", "1688")))
    bg.add_task(_run_scan, job_id, keywords, 50, scan_src)
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
    settings = merge_env_with_settings(await db.get_settings())
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
    settings = merge_env_with_settings(await db.get_settings())
    verify_token = str(get_config("INSTAGRAM_WEBHOOK_TOKEN", settings.get("instagram_webhook_token") or "dropos_webhook_secret"))
    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(403, "Webhook verification failed — check your verify token")


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


# ── Background helpers ─────────────────────────────────────────────────────────

async def _run_scan(job_id: int, keywords: list, max_per_keyword: int, source: str = "1688") -> None:
    try:
        log.info("Job %d starting scan: keywords=%s source=%s max_per_keyword=%s", job_id, keywords, source, max_per_keyword)
        await run_pipeline(job_id, keywords, max_per_keyword, source=source)
    except Exception as e:
        log.error("Pipeline job %d failed: %s", job_id, e)
        await db.update_job(job_id, status="error")


async def _process_ig_webhook(body: dict) -> None:
    if body.get("object") != "instagram":
        return

    settings  = merge_env_with_settings(await db.get_settings())
    ig_uid    = str(get_config("INSTAGRAM_USER_ID", settings.get("instagram_user_id")) or "")
    comment_on = bool(get_config("INSTAGRAM_AUTO_REPLY_ENABLED", settings.get("instagram_auto_reply_enabled")))
    dm_on      = bool(get_config("INSTAGRAM_DM_REPLY_ENABLED", settings.get("instagram_dm_reply_enabled")))

    if not comment_on and not dm_on:
        return

    comment_rules = settings.get("instagram_reply_rules") or []
    dm_rules      = settings.get("instagram_dm_rules")    or []

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
        settings = merge_env_with_settings(await db.get_settings())
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
