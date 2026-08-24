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
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import httpx
import jwt
import bcrypt as _bcrypt
from pythonjsonlogger import jsonlogger
import time
from collections import defaultdict
import ipaddress
import socket

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

def _client_ip(request: Request) -> str:
    """
    Rate-limit key. Behind Railway's proxy every client shares one socket IP, so
    prefer the first X-Forwarded-For hop (set by the proxy) over the raw address —
    otherwise one bucket would throttle every user at once.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return get_remote_address(request)


limiter = Limiter(key_func=_client_ip)

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
from config.paths import DATA_DIR, COLLAGE_DIR, CLEANED_DIR, SECRET_FILE, data_path
from image_editor import _convert_to_jpeg
from services.cleaning import clean_product_image
from collage import create_collage
from services.images import upload_product_image
from database import db, init_db
from runner import process_scraped_products, run_pipeline
from scheduler import create_scheduler, get_scheduler_status
from posting_scheduler import create_posting_scheduler, get_posting_scheduler_status
import activity
import autopilot
import content_ai
import keyword_lab
import instagram
import instagram_private
import instagram_replies
import sheets
import ai_assistant
import decision_memory
import preference_analyzer
from utils.google_auth import configure_google_credentials_from_env
from worker import run_worker_loop, process_queued_items

# ── Security & Auth ───────────────────────────────────────────────────────
def verify_password(plain_password, hashed_password):
    try:
        return _bcrypt.checkpw(plain_password.encode(), hashed_password.strip().encode())
    except Exception as exc:
        log.error("bcrypt.checkpw raised: %s", exc)
        return False

_JWT_SECRET_CACHE: Optional[str] = None

def _jwt_secret() -> str:
    """JWT signing secret: JWT_SECRET env var, else a random secret generated once
    and kept in DATA_DIR/jwt_secret so sessions survive restarts (self-hosted mode)."""
    global _JWT_SECRET_CACHE
    if _JWT_SECRET_CACHE:
        return _JWT_SECRET_CACHE
    secret = (os.getenv("JWT_SECRET") or "").strip()
    if not secret:
        try:
            if SECRET_FILE.exists():
                secret = SECRET_FILE.read_text(encoding="utf-8").strip()
            if not secret:
                import secrets as _secrets
                secret = _secrets.token_hex(32)
                SECRET_FILE.write_text(secret, encoding="utf-8")
                log.info("Generated a new JWT secret in %s", SECRET_FILE)
        except Exception as exc:
            log.error("Could not read/write %s (%s) — using a per-process secret", SECRET_FILE, exc)
            import secrets as _secrets
            secret = _secrets.token_hex(32)
    _JWT_SECRET_CACHE = secret
    return secret

_LOGIN_FAILURES: dict[str, list[float]] = defaultdict(list)
_LOCKOUT_MAX = 5
_LOCKOUT_WINDOW = 300  # 5 minutes

def _is_locked_out(email: str) -> bool:
    now = time.time()
    recent = [t for t in _LOGIN_FAILURES[email] if now - t < _LOCKOUT_WINDOW]
    _LOGIN_FAILURES[email] = recent
    return len(recent) >= _LOCKOUT_MAX

def _record_failure(email: str):
    _LOGIN_FAILURES[email].append(time.time())

def _clear_failures(email: str):
    _LOGIN_FAILURES.pop(email, None)

# ── Logging ────────────────────────────────────────────────────────────────
log = logging.getLogger(__name__)

class SensitiveDataFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.msg, str):
            for sensitive in _SENSITIVE_SETTING_FIELDS:
                # Basic redaction if setting keys appear in logs
                pass
        return True

def _setup_app_logging():
    """Configure structured JSON logging."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    logHandler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)
    logger.addFilter(SensitiveDataFilter())

    for name in ("runner", "scraper_cssbuy", "filter_engine", "enrichment", "scorer", "__main__", "fastapi", "uvicorn"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)
        lg.propagate = True

_setup_app_logging()

# ── Globals & Constants ───────────────────────────────────────────────────
_scheduler = None
_posting_scheduler = None
_SENSITIVE_SETTING_FIELDS = {
    "apify_token",
    "anthropic_key",
    "gemini_key",
    "groq_key",
    "openai_key",
    "instagram_access_token",
    "instagram_webhook_token",
    "instagram_app_secret",
    "ig_private_password",
    "ig_session_id",
    "ig_proxy",
    "cssbuy_password",
    "captcha_2captcha_key",
    "google_sheets_credentials",
    "ingest_api_token",
    "clipdrop_key",
}
_COLLAGE_DIR = str(COLLAGE_DIR)
_CLEANED_DIR = str(CLEANED_DIR)
_CSSBUY_DEBUG_DIR = os.getenv("CSSBUY_DEBUG_DIR") or str(data_path("cssbuy_debug"))
os.environ.setdefault("CSSBUY_DEBUG_DIR", _CSSBUY_DEBUG_DIR)

# ── Lifespan ───────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler, _posting_scheduler
    await init_db()
    activity.bind(db)
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

    # Environment hints (nothing here is fatal in self-hosted mode)
    log.info("Data directory: %s", DATA_DIR)
    _jwt_secret()
    if not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY")):
        log.info("Supabase Storage not configured — product images stay on the supplier CDN. "
                 "Instagram posting needs publicly reachable images: set SUPABASE_URL + "
                 "SUPABASE_SERVICE_ROLE_KEY (free tier) or PUBLIC_BASE_URL of a reachable deployment.")
    if not await db.count_admin_users():
        log.warning("No admin user yet — open the app in a browser to create one (first-run setup).")

    # Autonomous worker loops
    asyncio.create_task(run_worker_loop())
    asyncio.create_task(process_queued_items())
    asyncio.create_task(instagram_private.poll_loop(db, _settings))

    if merged_settings.get("local_scraping_only"):
        log.info("Scheduler disabled: local scraping only mode is enabled")
    else:
        _scheduler = create_scheduler()
        _scheduler.start()
        log.info("Scheduler started - jobs: %s", [j.get("id") for j in _scheduler.get_jobs()])

    # Peak-hour Instagram auto-posting (off by default; Settings → Posting schedule)
    try:
        _posting_scheduler = create_posting_scheduler(_settings)
        await _posting_scheduler._dropos_init_jobs()
        _posting_scheduler.start()
        log.info("Posting scheduler started - jobs: %s", [j.id for j in _posting_scheduler.get_jobs()])
    except Exception as exc:
        log.error("Posting scheduler failed to start: %s", exc)
        _posting_scheduler = None

    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)
    if _posting_scheduler:
        try:
            _posting_scheduler.shutdown(wait=False)
        except Exception:
            pass
    await db.close()

# ── App Initialization ─────────────────────────────────────────────────────
# APP_ENV=production hides the API docs and tightens CORS. Railway's env var is
# still honoured for anyone who deploys there.
_is_production = (os.getenv("APP_ENV", "").lower() == "production") or bool(os.getenv("RAILWAY_ENVIRONMENT_NAME"))
is_dev = not _is_production

app = FastAPI(
    title="DropOS",
    lifespan=lifespan,
    docs_url="/docs" if is_dev else None,
    redoc_url="/redoc" if is_dev else None,
    openapi_url="/openapi.json" if is_dev else None
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Trust proxy headers only from a known reverse proxy, not arbitrary clients
_trusted_proxy = os.getenv("TRUSTED_PROXY_HOST") or os.getenv("RAILWAY_PROXY_TRUSTED_HOST", "127.0.0.1")
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=_trusted_proxy)

# CORS: the SPA is same-origin, so this only matters for a separately hosted
# frontend (FRONTEND_DOMAIN) and local development on other ports.
_allowed_origins = [o for o in [os.getenv("FRONTEND_DOMAIN", "")] if o]
if not _is_production:
    _allowed_origins += ["http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:8000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Ingest-Token"],
)

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_domain = urlparse(supabase_url).netloc if supabase_url else ""
    img_src = "img-src 'self' data: blob:" + (f" https://{supabase_domain}" if supabase_domain else "")
    connect_src = "connect-src 'self'" + (f" https://{supabase_domain}" if supabase_domain else "")
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        f"{img_src}; {connect_src};"
    )
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Server"] = "webserver"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response

@app.middleware("http")
async def jwt_auth_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    is_public = path in ["/robots.txt", "/health", "/shop", "/api/catalog", "/api/auth/login", "/api/auth/status", "/api/auth/setup", "/api/version", "/api/ingest/products"] or \
                path.startswith("/api/image") or \
                path.startswith("/api/collage-image/") or \
                path.startswith("/api/instagram/webhook") or \
                (path.startswith("/api/products/") and path.endswith("/cleaned-image")) or \
                path.startswith("/static") or \
                "/assets/" in path or path.endswith("/assets")

    if is_public:
        return await call_next(request)

    # Only protect API routes with JWT. SPA routes like / return index.html where SPA handles redirect
    if not path.startswith("/api/"):
        return await call_next(request)

    secret = _jwt_secret()

    # Accept Bearer token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else None

    if not token:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        if payload.get("role") != "admin":
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    except jwt.PyJWTError:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    return await call_next(request)

# ── Auth Routes ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/auth/login")
@limiter.limit("20/minute")
async def login(request: Request, body: LoginRequest):
    email = body.email.strip().lower()
    if _is_locked_out(email):
        return JSONResponse({"detail": "Too many failed attempts. Try again later."}, status_code=429)

    user = await db.get_admin_user(email)
    if not user:
        _record_failure(email)
        log.warning("login failed: user not found for email=%s", email)
        return JSONResponse({"detail": "Invalid credentials"}, status_code=401)
    if not verify_password(body.password, user["password_hash"]):
        _record_failure(email)
        log.warning("login failed: wrong password for email=%s hash_prefix=%s", email, user["password_hash"][:10])
        return JSONResponse({"detail": "Invalid credentials"}, status_code=401)

    _clear_failures(email)
    return JSONResponse({"ok": True, "token": _issue_token(user["id"])})


def _issue_token(user_id) -> str:
    return jwt.encode(
        {"sub": str(user_id), "role": "admin", "exp": int(time.time() + 86400 * 7)},
        _jwt_secret(),
        algorithm="HS256",
    )


class SetupRequest(BaseModel):
    email: str
    password: str


@app.get("/api/auth/status")
async def auth_status():
    """Public: tells the SPA whether the first-run setup screen is needed."""
    return {"needs_setup": (await db.count_admin_users()) == 0}


@app.post("/api/auth/setup")
@limiter.limit("5/minute")
async def auth_setup(request: Request, body: SetupRequest):
    """Create the first admin account. Only works while no admin exists."""
    if await db.count_admin_users():
        raise HTTPException(409, "Setup already completed — sign in instead.")
    email = body.email.strip().lower()
    if "@" not in email or len(email) < 5:
        raise HTTPException(400, "Enter a valid e-mail address.")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    pw_hash = _bcrypt.hashpw(body.password.encode(), _bcrypt.gensalt(rounds=12)).decode()
    user_id = await db.create_admin_user(email, pw_hash)
    log.info("First admin account created: %s", email)
    return JSONResponse({"ok": True, "token": _issue_token(user_id)})

@app.post("/api/auth/logout")
async def logout():
    return JSONResponse({"ok": True})

# ── Routes & Mounts ────────────────────────────────────────────────────────

@app.exception_handler(404)
async def spa_fallback(request: Request, exc: HTTPException):
    """Fallback for SPA routing: serve index.html for non-API 404s."""
    if not request.url.path.startswith("/api"):
        # Try Backoffice first
        p = os.path.join(BASE_DIR, "frontend", "index.html")
        if os.path.exists(p): return FileResponse(p)
        # Then Shop
        p = os.path.join(PUBLIC_DIR, "index.html")
        if os.path.exists(p): return FileResponse(p)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})

@app.get("/api/version")
async def version():
    return {"auth": "bearer", "version": "v12"}

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

# Root static mount for generic files (last priority)
if os.path.isdir(PUBLIC_DIR):
    app.mount("/static", StaticFiles(directory=PUBLIC_DIR), name="static")

# ── Request Models ──────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    keywords: List[str]
    max_per_keyword: int = 50
    source: str = "taobao"
    brand_id: Optional[int] = None

class IngestProductsRequest(BaseModel):
    products: List[dict]
    keywords: List[str] = []
    source: Optional[str] = None
    brand_id: Optional[int] = None

class ApproveRequest(BaseModel):
    product_ids: List[int]

class BatchRejectRequest(BaseModel):
    product_ids: List[int]
    reason: Optional[str] = None

class PostRequest(BaseModel):
    product_ids: List[int]

class RejectRequest(BaseModel):
    reason: Optional[str] = None

class BulkStatusRequest(BaseModel):
    product_ids: List[int]
    stage: str
    reason: Optional[str] = None

class CollagePostRequest(BaseModel):
    product_ids: List[int]
    caption: Optional[str] = None

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
    instagram_url: Optional[str] = None

class SettingsUpdate(BaseModel):
    store_name: Optional[str] = None
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
    instagram_app_secret: Optional[str] = None
    instagram_backend: Optional[str] = None
    ig_private_username: Optional[str] = None
    ig_private_password: Optional[str] = None
    ig_session_id: Optional[str] = None
    ig_poll_minutes: Optional[float] = None
    ig_country: Optional[str] = None
    ig_country_code: Optional[int] = None
    ig_locale: Optional[str] = None
    ig_timezone_offset: Optional[int] = None
    ig_proxy: Optional[str] = None
    ig_delay_min: Optional[float] = None
    ig_delay_max: Optional[float] = None
    ig_quiet_start: Optional[int] = None
    ig_quiet_end: Optional[int] = None
    ig_post_jitter_min: Optional[int] = None
    apify_token: Optional[str] = None
    anthropic_key: Optional[str] = None
    gemini_key: Optional[str] = None
    groq_key: Optional[str] = None
    openai_key: Optional[str] = None
    anthropic_model: Optional[str] = None
    openai_model: Optional[str] = None
    content_provider: Optional[str] = None
    content_rewrite_enabled: Optional[bool] = None
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
    ai_context_injection: Optional[bool] = None
    # Autopilot
    autopilot_enabled: Optional[bool] = None
    auto_scan_enabled: Optional[bool] = None
    scan_interval_hours: Optional[float] = None
    auto_approve_enabled: Optional[bool] = None
    auto_approve_min_score: Optional[float] = None
    auto_approve_verdicts: Optional[List[str]] = None
    auto_clean_images: Optional[bool] = None
    auto_reject_pending_days: Optional[int] = None
    max_posts_per_day: Optional[int] = None
    lead_keywords: Optional[List[str]] = None

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
        # Restore settings only on startup to maintain environment consistency
        remote_settings = await asyncio.to_thread(sheets.load_settings)
        if remote_settings:
            await db.update_settings(remote_settings)
        await _configure_sheets_from_settings()
    except Exception as e:
        log.warning("Startup sheets sync failed: %s", e)

async def _backup_settings_to_sheets() -> dict:
    if not sheets.is_configured():
        return {"ok": True, "skipped": True}
    try:
        snapshot = await db.get_settings()
        return await asyncio.to_thread(sheets.save_settings, snapshot)
    except Exception as exc:
        log.warning("Settings backup failed: %s", exc)
        return {"ok": False, "error": str(exc)}

async def _backup_products_to_sheets() -> dict:
    # Skip the full-table snapshot entirely when Sheets isn't configured —
    # this is called after every approve/reject/edit.
    if not sheets.is_configured():
        return {"ok": True, "skipped": True}
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

    top_reasons = sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)
    recommendations = []
    if scraped and len(rejected) / scraped > 0.9 and top_reasons:
        recommendations.append(f"Over 90% filtered out — most common: {top_reasons[0][0]}.")
    if scraped and pass_rate == 0 and not ai_pass:
        recommendations.append("Nothing reached the review queue — check the rejection reasons below.")
    accepted_examples = sorted(ai_pass, key=lambda i: float(i.get("ai_score") or 0), reverse=True)[:5]

    return {
        "headline": f"{len(ai_pass)} products accepted for review from {scraped} fetched items.",
        "pass_rate": round(pass_rate, 1),
        "rejected": len(rejected),
        "top_reasons": [{"reason": k, "count": v} for k, v in top_reasons[:6]],
        "accepted_examples": [
            {"title": i.get("title") or i.get("product_name") or "", "composite_score": i.get("ai_score") or 0}
            for i in accepted_examples
        ],
        "recommendations": recommendations,
    }

async def _create_scan_job(bg: BackgroundTasks, keywords: list, max_per_keyword: int, source: str, brand_id: Optional[int] = None) -> int:
    active = await db.get_active_job()
    if active:
        raise HTTPException(409, {"message": f"Job #{active['id']} is already running", "job_id": active["id"]})
    brand_id = brand_id or await db.default_brand_id()
    job_id = await db.create_job(keywords=keywords, brand_id=brand_id)
    if brand_id:
        await db.touch_keywords_scanned(brand_id, keywords)
    bg.add_task(_run_scan, job_id, keywords, max_per_keyword, source, brand_id)
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
    return ProductStage.TEXT_REMOVAL.value if product.get("has_chinese_text") else ProductStage.REVIEWED.value

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
async def get_catalog(limit: int = 100, offset: int = 0, category: Optional[str] = None):
    """Public storefront — only returns LIVE (published) products."""
    products = await db.get_products(stage=ProductStage.LIVE.value, limit=limit, offset=offset)

    # 1. Existing category filtering logic
    if category:
        products = [p for p in products if p.get("category") == category]

    # 2. Prune the payload to prevent leaking backend data (cost, margin, notes)
    safe_products = []
    for p in products:
        safe_products.append({
            "id":                p.get("id"),
            "product_name":      p.get("product_name") or "",
            "title_translated":  p.get("title_translated") or p.get("product_name") or "",
            "sell_price_eur":    p.get("sell_price_eur"),
            "images":            p.get("images") or [],
            "category":          p.get("category") or "",
            "keyword":           p.get("keyword") or "",
            "caption":           p.get("caption") or "",
            "description":       p.get("description") or "",
            "score":             p.get("score") or 0,
            "audience":          p.get("audience") or "",
            "instagram_url":     p.get("instagram_url") or "",
        })


    return {
        "products": safe_products,
        "total": len(safe_products)
    }

@app.get("/api/settings")

async def get_settings():
    data = sanitize_settings(await _settings())
    # Runtime facts the UI needs to give honest guidance
    data["image_storage_set"] = bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    merged = await _settings()
    data["instagram_mode"] = instagram.backend_mode(merged)
    data["instagram_connected"] = data["instagram_mode"] != "none"
    data["ig_private_state"] = instagram_private.state()
    data["runtime"] = {
        "data_dir": str(DATA_DIR),
        "embedded_db": bool(getattr(db, "embedded", False)),
        "production": _is_production,
    }
    return data

@app.patch("/api/settings")
async def update_settings(body: SettingsUpdate):
    try:
        data = body.model_dump(exclude_none=True)
        _remove_blank_sensitive_values(data)
        await db.update_settings(data)

        # Re-plan peak-hour posting jobs if the schedule changed
        if _posting_scheduler and any(k in data for k in ("post_times", "post_timezone")):
            try:
                await _posting_scheduler._dropos_init_jobs()
            except Exception as e:
                log.warning("Posting scheduler re-plan failed: %s", e)

        # Background tasks that shouldn't block the main response if they fail partially
        try:
            await _configure_sheets_from_settings()
            await _backup_settings_to_sheets()
        except Exception as e:
            log.warning("Post-save settings sync failed: %s", e)

        return {"ok": True}
    except Exception as e:
        log.error("Failed to update settings: %s", e)
        raise HTTPException(500, detail=str(e))

@app.post("/api/admin/reset-database")
async def reset_database():
    """DANGER: Erases all product data from the database and Google Sheets."""
    try:
        await db.truncate_product_data()
        # Also clear the Google Sheet if connected, to prevent auto-restore issues
        try:
            await _backup_products_to_sheets()
        except Exception as e:
            log.warning("Could not clear Google Sheet during reset: %s", e)

        return {"ok": True, "message": "Database and cloud backup reset successfully."}
    except Exception as e:
        log.error("Database reset failed: %s", e)
        raise HTTPException(500, detail=f"Reset failed: {str(e)}")

@app.get("/api/stats")
async def get_stats():
    return await db.get_stats()

@app.get("/api/products")
async def get_products(stage: str = ProductStage.SCRAPED.value, limit: int = 50, offset: int = 0, sort: str = "score", q: str = "", brand_id: Optional[int] = None):
    limit = max(1, min(limit, 500))
    products = await db.get_products(stage=stage, limit=limit, offset=max(0, offset), sort=sort, q=q, brand_id=brand_id)
    total = await db.count_products(stage=stage, q=q, brand_id=brand_id)
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

async def _is_private_ip(url_str: str) -> bool:
    try:
        hostname = urlparse(url_str).hostname
        if not hostname: return True
        loop = asyncio.get_running_loop()
        addrs = await loop.getaddrinfo(hostname, None)
        for addr in addrs:
            ip = addr[4][0]
            if ipaddress.ip_address(ip).is_private or ipaddress.ip_address(ip).is_loopback:
                return True
        return False
    except Exception:
        return True

async def _fetch_public_image(src: str, timeout: int = 15) -> httpx.Response:
    """GET an image URL, following at most 3 redirects and refusing any hop
    that is not http(s) or resolves to a private/loopback address (SSRF guard)."""
    url = src
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(4):
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                raise HTTPException(400, "Only http(s) URLs are allowed")
            if await _is_private_ip(url):
                raise HTTPException(403, "Access to private IP addresses is forbidden")
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.1688.com/"})
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                url = str(r.next_request.url) if r.next_request else r.headers["location"]
                continue
            return r
    raise HTTPException(502, "Too many redirects")


@app.get("/api/image")
async def proxy_image(url: str):
    src = unquote(url or "").strip()
    try:
        r = await _fetch_public_image(src)
        if r.status_code != 200: raise HTTPException(r.status_code, "Fetch failed")
        content_type = r.headers.get("content-type", "").split(";")[0].strip()
        if not content_type.startswith("image/"):
            raise HTTPException(415, "URL does not point to an image")
        img_bytes = r.content
        if content_type not in ("image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"):
            img_bytes, content_type = _convert_to_jpeg(img_bytes, content_type)
        return Response(content=img_bytes, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Proxy failed: {e}")

@app.post("/api/products/{product_id}/approve")
async def approve_product(product_id: int):
    p = await _get_product_or_404(product_id)
    _require_stage(p, ProductStage.ENRICHED.value, "Cannot approve product in stage '{stage}'")
    stage = _approval_stage(p)
    await db.set_stage(product_id, stage)
    await activity.record("approved", f"You approved “{_pname(p)}”", product_id=product_id)
    await _backup_products_to_sheets()
    return {"ok": True, "stage": stage}


def _pname(p: dict) -> str:
    return (p.get("product_name") or p.get("title_translated") or p.get("title") or f"#{p.get('id')}")[:60]

@app.post("/api/products/{product_id}/publish-website")
async def publish_to_website(product_id: int):
    """Publish a product directly to the website catalog (sets LIVE, no Instagram posting)."""
    p = await _get_product_or_404(product_id)
    if p.get("stage") != ProductStage.REVIEWED.value:
        raise HTTPException(400, f"Product must be in REVIEWED stage to publish to website (current: {p.get('stage')})")
    await db.set_stage(product_id, ProductStage.LIVE.value)
    await _backup_products_to_sheets()
    return {"ok": True}

@app.post("/api/approve")
async def approve_products(body: ApproveRequest):
    approved = 0
    text_edit = 0
    for pid in body.product_ids[:50]:
        p = await db.get_product(pid)
        if p and p.get("stage") == ProductStage.ENRICHED.value:
            stage = _approval_stage(p)
            await db.set_stage(pid, stage)
            if stage == ProductStage.TEXT_REMOVAL.value: text_edit += 1
            else: approved += 1
    if approved or text_edit:
        await activity.record("approved", f"You approved {approved + text_edit} products" + (f" ({text_edit} need photo cleaning)" if text_edit else ""))
    await _backup_products_to_sheets()
    return {"ok": True, "TEXT_REMOVAL": text_edit, "REVIEWED": approved}

@app.post("/api/reject")
async def reject_products_batch(body: BatchRejectRequest):
    reason = (body.reason or "").strip() or None
    changed = await _stage_products(body.product_ids, ProductStage.REJECTED.value, reason=reason)
    if changed:
        await activity.record("rejected", f"You rejected {len(changed)} products" + (f" — {reason}" if reason else ""))
    await _backup_products_to_sheets()
    return {"ok": True, "rejected": len(changed)}

@app.post("/api/reject-all-pending")
async def reject_all_pending():
    products = await db.get_products(stage=ProductStage.ENRICHED.value, limit=10000, offset=0, sort="score")
    ids = [p["id"] for p in products]
    if ids:
        await _stage_products(ids, ProductStage.REJECTED.value)
        await _backup_products_to_sheets()
    return {"ok": True, "rejected": len(ids)}

_BULK_TRANSITIONS = {
    # target stage → stages it may come from
    ProductStage.REVIEWED.value:     {ProductStage.ENRICHED.value, ProductStage.TEXT_REMOVAL.value, ProductStage.QUEUED.value, ProductStage.REJECTED.value},
    ProductStage.TEXT_REMOVAL.value: {ProductStage.ENRICHED.value, ProductStage.REVIEWED.value},
    ProductStage.QUEUED.value:       {ProductStage.REVIEWED.value},
    ProductStage.REJECTED.value:     {ProductStage.ENRICHED.value, ProductStage.TEXT_REMOVAL.value, ProductStage.REVIEWED.value, ProductStage.QUEUED.value},
    ProductStage.ENRICHED.value:     {ProductStage.REJECTED.value, ProductStage.REVIEWED.value, ProductStage.TEXT_REMOVAL.value},
}

@app.post("/api/products/bulk-status")
async def bulk_status(body: BulkStatusRequest):
    """Move up to 50 products to a stage (review hotkeys, chat actions)."""
    target = (body.stage or "").strip().upper()
    if target not in _BULK_TRANSITIONS:
        raise HTTPException(400, f"Unsupported target stage '{target}'")
    allowed_from = _BULK_TRANSITIONS[target]
    reason = (body.reason or "").strip() or None
    moved, skipped = [], []
    for pid in body.product_ids[:50]:
        p = await db.get_product(pid)
        if not p or p.get("stage") not in allowed_from:
            skipped.append(pid)
            continue
        stage = target
        # Approving a product whose photo still has Chinese text routes it to cleanup first
        if target == ProductStage.REVIEWED.value and p.get("stage") == ProductStage.ENRICHED.value:
            stage = _approval_stage(p)
        await db.set_stage(pid, stage, reason=reason if target == ProductStage.REJECTED.value else None)
        moved.append(pid)
        if target == ProductStage.REJECTED.value:
            await activity.record("rejected", f"You rejected “{_pname(p)}”" + (f" — {reason}" if reason else ""), product_id=pid)
        elif target == ProductStage.REVIEWED.value:
            await activity.record("approved", f"You approved “{_pname(p)}”", product_id=pid)
        elif target == ProductStage.ENRICHED.value:
            await activity.record("reconsidered", f"Moved “{_pname(p)}” back to review", product_id=pid)
    if moved:
        await _backup_products_to_sheets()
    return {"ok": True, "moved": moved, "skipped": skipped}

@app.post("/api/products/{product_id}/rewrite-caption")
async def rewrite_caption(product_id: int):
    """Write a fresh caption + hashtags with the content model (Claude/OpenAI/…)."""
    p = await _get_product_or_404(product_id)
    settings = await _settings()
    if not content_ai.content_ready(settings):
        raise HTTPException(400, "No content model configured — add a Claude or OpenAI key in Settings → Connections.")
    brand = await db.get_brand(p.get("brand_id")) if p.get("brand_id") else None
    result = await content_ai.generate_caption(p, settings, brand)
    if not result:
        raise HTTPException(502, "The content model returned nothing usable — try again.")
    updates = {"caption": result["caption"]}
    if result["hashtags"]:
        updates["hashtags_json"] = json.dumps(result["hashtags"])
    await db.update_product_fields(product_id, updates)
    return {"ok": True, **result, "provider": content_ai.provider_label(settings)}


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
    p = await db.get_product(product_id)
    await db.set_stage(product_id, ProductStage.REJECTED.value, reason=reason)
    if p:
        await activity.record("rejected", f"You rejected “{_pname(p)}”" + (f" — {reason}" if reason else ""), product_id=product_id)
    await _backup_products_to_sheets()
    return {"ok": True}

@app.post("/api/products/{product_id}/reconsider")
async def reconsider_product(product_id: int):
    await db.set_stage(product_id, ProductStage.ENRICHED.value)
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
    if not settings.get("clipdrop_key"):
        raise HTTPException(400, "Clipdrop API key missing")
    outcome = await clean_product_image(p, settings)
    if not outcome.get("ok"):
        await activity.record("image_clean_failed", f"Manual clean failed for product {product_id}: {outcome.get('error')}", product_id=product_id, level="warn")
        raise HTTPException(502, outcome.get("error") or "Clipdrop failed")
    await activity.record("image_cleaned", f"Cleaned photo of “{(p.get('product_name') or p.get('title_translated') or '')[:60]}”", product_id=product_id)
    return {"ok": True, "image_url": outcome["image_url"], "public": outcome["public"]}

@app.get("/api/products/{product_id}/cleaned-image")
async def serve_cleaned_image(product_id: int):
    data = None
    path = f"{_CLEANED_DIR}/cleaned_{product_id}.jpg"
    if os.path.exists(path):
        with open(path, "rb") as f: data = f.read()
    if data:
        return Response(content=data, media_type="image/jpeg")
    # File lost after container restart — proxy the original image so URLs stay valid
    product = await db.get_product(product_id)
    if product:
        fallback = next(
            (img for img in (product.get("images") or []) if img and "/api/products/" not in img),
            None,
        )
        if fallback:
            try:
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                    resp = await client.get(fallback)
                if resp.status_code == 200:
                    ct = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                    img_bytes = resp.content
                    if ct not in ("image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"):
                        img_bytes, ct = _convert_to_jpeg(img_bytes, ct)
                    return Response(content=img_bytes, media_type="image/jpeg")
            except Exception:
                pass
    raise HTTPException(404, "Not found")

@app.patch("/api/products/{product_id}/note")
async def update_note(product_id: int, body: NoteUpdate):
    await db.update_product_note(product_id, body.note)
    return {"ok": True}

@app.post("/api/scan")
async def start_scan(body: ScanRequest, bg: BackgroundTasks):
    job_id = await _create_scan_job(bg, body.keywords, body.max_per_keyword, body.source, body.brand_id)
    return {"job_id": job_id, "status": "started"}

@app.post("/api/ingest/products")
async def ingest_products(body: IngestProductsRequest, bg: BackgroundTasks, authorization: Optional[str] = Header(None), x_ingest_token: Optional[str] = Header(None)):
    await _verify_ingest_token(authorization, x_ingest_token)
    brand_id = body.brand_id or await db.default_brand_id()
    job_id = await db.create_job(keywords=body.keywords or ["local upload"], brand_id=brand_id)
    bg.add_task(_run_ingest, job_id, body.products, brand_id)
    return {"job_id": job_id, "status": "uploaded"}

@app.get("/api/jobs")
async def get_jobs(limit: int = 20):
    return await db.get_jobs(limit)

@app.delete("/api/jobs")
async def delete_jobs():
    """Clear scan history (jobs, raw snapshots, pipeline breakdown). Products are kept."""
    return {"ok": True, "deleted": await db.clear_scan_history()}

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

# ── Decision Intelligence (read-only, no AI calls) ───────────────────────────

@app.get("/api/ai/decision-stats")
async def get_decision_stats():
    """
    Returns raw decision-history statistics aggregated from the products and
    pipeline_products tables.  No AI calls; fast and safe to poll.
    """
    return await decision_memory.build_summary(db)


@app.post("/api/ai/analyze")
async def analyze_decisions():
    """
    Runs the deterministic preference analyzer over the current decision history,
    stores findings in ai_recommendations, and returns them.
    Previous non-dismissed recommendations are cleared first so results stay fresh.
    """
    settings = await _settings()
    summary = await decision_memory.build_summary(db)
    findings, status = preference_analyzer.analyze(summary, settings)

    await db.clear_active_recommendations()
    for f in findings:
        await db.save_recommendation(f)

    return {"findings": findings, "count": len(findings), "status": status}


@app.get("/api/ai/recommendations")
async def get_recommendations(include_dismissed: bool = False):
    """Returns stored AI recommendations, newest first."""
    recs = await db.get_recommendations(include_dismissed=include_dismissed)
    return {"recommendations": recs, "count": len(recs)}


@app.post("/api/ai/recommendations/{rec_id}/dismiss")
async def dismiss_recommendation(rec_id: int):
    """Mark a recommendation as dismissed so it is hidden from the default view."""
    await db.dismiss_recommendation(rec_id)
    return {"ok": True}


@app.get("/api/ai/injection-stats")
async def get_injection_stats():
    """
    Aggregate comparison of enrichment batches scored with context injection ON
    vs OFF.  Use this to evaluate whether enabling ai_context_injection changes
    acceptance rates or score distributions.

    Groups:
      with_injection    — batches where snippet_injected=1 (flag ON, history sufficient)
      without_injection — all other batches (flag OFF, insufficient history, or error)
      by_skip_reason    — full breakdown including flag_off / insufficient_history / error
    """
    return await db.get_injection_stats()


@app.get("/api/ai/injection-log")
async def get_injection_log(limit: int = 50):
    """
    Recent enrichment batch log records, newest first.
    Each row represents one worker batch: flag state, snippet presence,
    snippet length, skip reason, batch size, accepted/rejected counts, avg score.
    """
    if limit > 200:
        limit = 200
    rows = await db.get_injection_log(limit)
    return {"log": rows, "count": len(rows)}


async def _build_chat_context() -> dict:
    """Gather full pipeline context for the AI assistant, using parallel DB queries."""
    (
        stats,
        analytics,
        recent_jobs,
        rejected_sample,
        approved_sample,
        pending_sample,
        recommendations,
    ) = await asyncio.gather(
        db.get_stats(),
        db.get_analytics(),
        db.get_jobs(limit=5),
        db.get_rejected_sample(limit=30),
        db.get_products_compact("REVIEWED", limit=20),
        db.get_products_compact("ENRICHED", limit=30),
        db.get_recommendations(),
    )
    return {
        "stats": stats,
        "analytics_summary": {
            "top_categories": analytics["categories"][:5],
            "top_rejection_reasons": analytics["top_rejections"][:6],
            "keyword_performance": analytics["keywords"][:8],
            "score_distribution": analytics["score_distribution"],
        },
        "recent_jobs": [
            {
                "id": j["id"],
                "status": j.get("status"),
                "keywords": j.get("keywords"),
                "scraped": j.get("scraped", 0),
                "created_at": str(j.get("created_at", ""))[:16],
            }
            for j in recent_jobs[:3]
        ],
        "rejected_sample": rejected_sample,
        "approved_sample": approved_sample,
        "pending_sample": pending_sample,
        "active_recommendations": [
            {"id": r["id"], "headline": r["headline"], "type": r.get("analysis_type")}
            for r in recommendations[:5]
        ],
    }


class ChatRequest(BaseModel):
    message: str
    reconsider: Optional[bool] = False
    execute_edits: Optional[bool] = False
    execute_approvals: Optional[bool] = False

@app.post("/api/ai/chat")
async def ai_chat(body: ChatRequest):
    settings = await _settings()
    context = await _build_chat_context()
    return await ai_assistant.chat(body.message, context, settings)

# ── Brands (markets) ──────────────────────────────────────────────────────────

class BrandBody(BaseModel):
    name: Optional[str] = None
    active: Optional[bool] = None
    niche: Optional[str] = None
    target_audience: Optional[str] = None
    example_products: Optional[str] = None
    sell_price_min: Optional[float] = None
    sell_price_max: Optional[float] = None
    auto_keywords_enabled: Optional[bool] = None
    keywords_per_scan: Optional[int] = None

class KeywordsBody(BaseModel):
    keywords: List[str]

class GenerateBody(BaseModel):
    count: int = 10


@app.get("/api/brands")
async def brands_list():
    brands = await db.list_brands()
    counts = await db.brand_product_counts()
    out = []
    for b in brands:
        kws = await db.list_keywords(b["id"])
        perf = await db.keyword_performance(b["id"])
        rows = keyword_lab.annotate(kws, perf)
        active_rows = [k for k in rows if k["status"] == "active"]
        scored = [k for k in rows if k["tested"]]
        out.append({**b,
            "products": counts.get(b["id"], {}),
            "keywords_active": len(active_rows),
            "keywords_untested": sum(1 for k in active_rows if not k["tested"]),
            "keywords_ai": sum(1 for k in rows if k["source"] == "ai"),
            "best_keyword": max(scored, key=lambda k: k["perf_score"] or 0)["keyword"] if scored else None,
        })
    return {"brands": out}


@app.post("/api/brands")
async def brands_create(body: BrandBody):
    if not (body.name or "").strip():
        raise HTTPException(400, "Brand name is required")
    brand_id = await db.create_brand(body.model_dump(exclude_none=True))
    await activity.record("config", f"Created brand “{body.name.strip()}”")
    return {"ok": True, "id": brand_id}


@app.patch("/api/brands/{brand_id}")
async def brands_update(brand_id: int, body: BrandBody):
    if not await db.get_brand(brand_id):
        raise HTTPException(404, "Brand not found")
    await db.update_brand(brand_id, body.model_dump(exclude_none=True))
    return {"ok": True}


@app.delete("/api/brands/{brand_id}")
async def brands_delete(brand_id: int):
    ok = await db.delete_brand(brand_id)
    if not ok:
        raise HTTPException(409, "Brand has products (or is the last one) — deactivate it instead.")
    return {"ok": True}


@app.get("/api/brands/{brand_id}/keywords")
async def brand_keywords(brand_id: int):
    if not await db.get_brand(brand_id):
        raise HTTPException(404, "Brand not found")
    kws = await db.list_keywords(brand_id)
    perf = await db.keyword_performance(brand_id)
    rows = keyword_lab.annotate(kws, perf)
    brand = await db.get_brand(brand_id)
    next_scan = keyword_lab.select(kws, perf, max(1, int(brand.get("keywords_per_scan") or 6)))
    return {"keywords": rows, "next_scan": next_scan, "min_sample": keyword_lab.MIN_SAMPLE}


@app.post("/api/brands/{brand_id}/keywords")
async def brand_keywords_add(brand_id: int, body: KeywordsBody):
    if not await db.get_brand(brand_id):
        raise HTTPException(404, "Brand not found")
    added = await db.add_keywords(brand_id, body.keywords, source="manual")
    return {"ok": True, "added": added}


@app.post("/api/brands/{brand_id}/keywords/generate")
async def brand_keywords_generate(brand_id: int, body: GenerateBody):
    brand = await db.get_brand(brand_id)
    if not brand:
        raise HTTPException(404, "Brand not found")
    settings = await _settings()
    if not content_ai.content_ready(settings):
        raise HTTPException(400, "Keyword generation needs an AI key — Claude, OpenAI, Gemini or Groq (Settings → Connections).")
    kws = await db.list_keywords(brand_id)
    perf = await db.keyword_performance(brand_id)
    fresh = await keyword_lab.generate(brand, kws, perf, settings, n=max(1, min(body.count, 25)))
    if not fresh:
        raise HTTPException(502, "The AI returned no usable keywords — try again.")
    added = await db.add_keywords(brand_id, fresh, source="ai")
    await db.update_brand(brand_id, {"last_keywords_generated_at": _now_iso()})
    await activity.record("keywords_generated", f"{brand['name']}: AI added {added} keywords — {', '.join(fresh[:5])}{'…' if len(fresh) > 5 else ''}",
                          meta={"brand_id": brand_id, "keywords": fresh})
    return {"ok": True, "added": added, "keywords": fresh}


@app.patch("/api/keywords/{keyword_id}")
async def keyword_update(keyword_id: int, status: str):
    if status not in ("active", "paused", "retired"):
        raise HTTPException(400, "status must be active | paused | retired")
    await db.set_keyword_status(keyword_id, status)
    return {"ok": True}


@app.delete("/api/keywords/{keyword_id}")
async def keyword_delete(keyword_id: int):
    await db.delete_keyword(keyword_id)
    return {"ok": True}


def _now_iso() -> str:
    from datetime import datetime, timezone as _tz
    return datetime.now(_tz.utc).isoformat()


# ── Autopilot ─────────────────────────────────────────────────────────────────

@app.get("/api/autopilot")
async def autopilot_status():
    settings = await _settings()
    posting = get_posting_scheduler_status(_posting_scheduler).get("jobs", [])
    scanning = bool(getattr(_scheduler, "scanning", False))
    return await autopilot.status(db, settings, posting_jobs=posting, scan_loop_running=scanning)


class AutopilotToggle(BaseModel):
    enabled: bool

@app.post("/api/autopilot/toggle")
async def autopilot_toggle(body: AutopilotToggle):
    await db.update_settings({"autopilot_enabled": bool(body.enabled)})
    await activity.record("config", "Autopilot turned " + ("ON" if body.enabled else "OFF"))
    return {"ok": True, "enabled": bool(body.enabled)}


@app.get("/api/activity")
async def activity_feed(limit: int = 60, kinds: Optional[str] = None, since: Optional[str] = None):
    limit = max(1, min(limit, 300))
    kind_list = [k.strip() for k in kinds.split(",") if k.strip()] if kinds else None
    rows = await db.get_activity(limit=limit, since=since, kinds=kind_list)
    return {"items": rows, "count": len(rows)}


# ── Inbox ─────────────────────────────────────────────────────────────────────

@app.get("/api/inbox")
async def inbox_list(all: bool = False, limit: int = 100):
    items = await db.inbox_list(only_open=not all, limit=max(1, min(limit, 500)))
    return {"items": items, "counts": await db.inbox_counts()}


@app.post("/api/inbox/{message_id}/handled")
async def inbox_handled(message_id: int, handled: bool = True):
    await db.inbox_set_handled(message_id, handled)
    return {"ok": True}


class InboxReply(BaseModel):
    text: str

@app.post("/api/inbox/{message_id}/reply")
async def inbox_reply(message_id: int, body: InboxReply):
    msg = await db.inbox_get(message_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "Reply text is empty")
    settings = await _settings()
    if not autopilot.has_instagram(settings):
        raise HTTPException(400, "Connect Instagram (direct login or token) to send replies")
    ext = str(msg.get("external_id") or "")
    if ext.startswith("pc:"):
        ok = await instagram_private.reply_comment(str(msg.get("media_id") or ""), text, settings, ext.removeprefix("pc:"))
    elif ext.startswith("pm:"):
        ok = await instagram_private.reply_dm(str(msg.get("media_id") or ""), text, settings)
    else:
        ok = await instagram_replies.send_reply(msg, text, settings)
    if not ok:
        raise HTTPException(502, "Instagram did not accept the reply — check token permissions")
    await db.inbox_set_handled(message_id, True)
    await activity.record("reply_sent", f"You replied to {msg.get('sender_name') or msg.get('sender_id')}: “{text[:60]}”")
    return {"ok": True}


class InboxTestMessage(BaseModel):
    text: str
    kind: str = "dm"
    sender: str = "test_user"

@app.post("/api/inbox/simulate")
async def inbox_simulate(body: InboxTestMessage):
    """Dev helper: feed a fake comment/DM through the same path as the webhook."""
    settings = await _settings()
    payload = {"object": "instagram", "entry": [{"id": settings.get("instagram_user_id") or "me"}]}
    if body.kind == "comment":
        payload["entry"][0]["changes"] = [{"field": "comments", "value": {"id": f"sim{int(time.time()*1000)}", "text": body.text, "from": {"id": body.sender, "username": body.sender}}}]
    else:
        payload["entry"][0]["messaging"] = [{"sender": {"id": body.sender}, "recipient": {"id": "me"}, "message": {"mid": f"sim{int(time.time()*1000)}", "text": body.text}}]
    stats = await instagram_replies.process_webhook(payload, settings, db)
    return {"ok": True, "stats": stats}


# ── Instagram ─────────────────────────────────────────────────────────────────

@app.get("/api/instagram/accounts")
async def instagram_accounts():
    settings = await _settings()
    token = str(settings.get("instagram_access_token") or "").strip()
    if not token:
        raise HTTPException(400, detail="No Instagram access token configured. Paste your token first.")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://graph.facebook.com/v23.0/me/accounts",
            params={"access_token": token, "fields": "id,name,instagram_business_account"},
        )
        body = resp.json()

    if "error" in body:
        msg = body["error"].get("message", str(body["error"]))
        raise HTTPException(400, detail=msg)

    accounts = []
    for page in body.get("data", []):
        ig = page.get("instagram_business_account")
        if ig and ig.get("id"):
            accounts.append({
                "page_id": page["id"],
                "page_name": page.get("name", ""),
                "instagram_business_account_id": ig["id"],
            })

    return {"accounts": accounts}

@app.get("/api/instagram/diagnostics")
async def instagram_diagnostics(product_id: Optional[int] = None):
    return {"status": "ok"}

class PrivateLoginBody(BaseModel):
    verification_code: Optional[str] = None

@app.post("/api/instagram/private/login")
async def ig_private_login(body: PrivateLoginBody):
    """Log the direct-login backend in now (optionally with an SMS/e-mail code)."""
    settings = await _settings()
    if not instagram_private.configured(settings):
        raise HTTPException(400, "Enter the Instagram username and password first, then Save.")
    # force=True: this is a deliberate human attempt, so it runs even while a
    # challenge is pending (the polling loop deliberately does not).
    cl = await instagram_private.get_client(settings, verification_code=(body.verification_code or "").strip(), force=True)
    st = instagram_private.state()
    if cl is None:
        raise HTTPException(502, st.get("error") or "Login failed")
    await activity.record("config", f"Instagram direct login OK as @{st.get('username')}")
    return {"ok": True, "state": st}

@app.post("/api/instagram/private/reset")
async def ig_private_reset():
    instagram_private.reset_session()
    return {"ok": True, "state": instagram_private.state()}

@app.post("/api/instagram/private/poll")
async def ig_private_poll_now():
    """Read Instagram communications right now (manual poll)."""
    settings = await _settings()
    if not instagram_private.configured(settings):
        raise HTTPException(400, "Direct login is not configured.")
    stats = await instagram_private.process_incoming(db, settings)
    return {"ok": not stats.get("error"), "stats": stats}

@app.get("/api/instagram/webhook")
async def ig_webhook_verify(hub_mode: str = Query(None, alias="hub.mode"), hub_verify_token: str = Query(None, alias="hub.verify_token"), hub_challenge: str = Query(None, alias="hub.challenge")):
    settings = await _settings()
    verify_token = str(settings.get("instagram_webhook_token") or "dropos_webhook_secret")
    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(403)

@app.get("/api/scheduler/status")
async def scheduler_status():
    status = get_scheduler_status(_scheduler)
    status["posting"] = get_posting_scheduler_status(_posting_scheduler)
    return status

@app.get("/api/instagram/reply-log")
async def get_ig_reply_log(limit: int = 50):
    return await db.get_comment_reply_log(limit)

class AITestRequest(BaseModel):
    provider: str
    key: Optional[str] = None

@app.post("/api/ai/test")
async def test_ai_connection(body: AITestRequest):
    settings = await _settings()
    if body.provider in ("claude", "openai"):
        return await content_ai.test_provider(body.provider, body.key, settings)
    return await ai_assistant.test_connection(body.provider, body.key, settings)

@app.post("/api/instagram/webhook")
async def ig_webhook_receive(request: Request, bg: BackgroundTasks):
    raw = await request.body()
    settings = await _settings()
    app_secret = str(settings.get("instagram_app_secret") or "").strip()
    if app_secret and not instagram_replies.verify_signature(app_secret, raw, request.headers.get("X-Hub-Signature-256", "")):
        log.warning("IG webhook: bad X-Hub-Signature-256 — ignoring delivery")
        raise HTTPException(403, "Invalid signature")
    try:
        body = json.loads(raw or b"{}")
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    bg.add_task(_process_ig_webhook, body)
    return {"ok": True}

@app.post("/api/scheduler/trigger")
async def trigger_scheduled_scan(bg: BackgroundTasks, brand_id: Optional[int] = None):
    """Run a scan now for one brand, picking keywords the way Autopilot would."""
    settings = await _settings()
    if settings.get("local_scraping_only"):
        raise HTTPException(409, "Server-side scraping is disabled (local scraping only). Upload from the local scraper instead.")
    if not (settings.get("cssbuy_username") and settings.get("cssbuy_password")):
        raise HTTPException(400, "CSSBuy username/password are not configured.")
    brand_id = brand_id or await db.default_brand_id()
    brand = await db.get_brand(brand_id) if brand_id else None
    if not brand:
        raise HTTPException(404, "Brand not found.")
    kws = await db.list_keywords(brand_id)
    perf = await db.keyword_performance(brand_id)
    keywords = keyword_lab.select(kws, perf, max(1, int(brand.get("keywords_per_scan") or 6)))
    if not keywords:
        raise HTTPException(400, f"“{brand['name']}” has no active keywords — add some on the Brands page.")
    source = str(settings.get("cssbuy_source") or "1688")
    job_id = await _create_scan_job(bg, keywords, 50, source, brand_id)
    return {"job_id": job_id, "status": "started", "keywords": keywords, "brand_id": brand_id}


# ── Collage posting ───────────────────────────────────────────────────────────

@app.post("/api/collage/post")
async def post_collage(body: CollagePostRequest):
    """Stitch 2–6 approved products into one grid image and post it to Instagram."""
    ids = list(dict.fromkeys(body.product_ids))[:6]
    if len(ids) < 2:
        raise HTTPException(400, "Select 2–6 approved products for a collage.")
    products = []
    for pid in ids:
        p = await db.get_product(pid)
        if not p:
            raise HTTPException(404, f"Product {pid} not found")
        if p.get("stage") != ProductStage.REVIEWED.value:
            raise HTTPException(400, f"Product {pid} is not approved (stage: {p.get('stage')})")
        products.append(p)

    image_urls = [(p.get("images") or [""])[0] for p in products]
    collage_bytes = await create_collage(image_urls)
    if not collage_bytes:
        raise HTTPException(502, "Could not build the collage image.")

    settings = await _settings()
    name = f"collage_{int(time.time())}_{_uuid.uuid4().hex[:8]}"
    public_url = await upload_product_image(collage_bytes, name)
    if not public_url:
        # Serve from this server instead (needs public_base_url for Instagram to fetch it)
        with open(os.path.join(_COLLAGE_DIR, f"{name}.jpg"), "wb") as f:
            f.write(collage_bytes)
        base = str(settings.get("public_base_url") or "").rstrip("/")
        public_url = f"{base}/api/collage-image/{name}.jpg" if base else f"/api/collage-image/{name}.jpg"

    names = [p.get("product_name") or p.get("title_translated") or "" for p in products]
    caption = (body.caption or "").strip() or "\n".join(f"• {n}" for n in names if n)
    hashtags: list = []
    for p in products:
        for h in (p.get("hashtags") or []):
            if h and h not in hashtags:
                hashtags.append(h)
    virtual = {"id": 0, "product_name": "collage", "caption": caption, "hashtags": hashtags[:20], "images": [public_url]}
    result = await instagram.post_product(virtual, settings)
    if result.status == "error":
        raise HTTPException(502, f"Instagram: {result.error}")

    for p in products:
        await db.set_stage(p["id"], ProductStage.LIVE.value)
        await db.log_post(p["id"])
        if result.post_url:
            await db.update_product_fields(p["id"], {"instagram_url": result.post_url})
    await _backup_products_to_sheets()
    return {"ok": True, "status": result.status, "post_url": result.post_url, "image_url": public_url, "posted": [p["id"] for p in products]}


@app.get("/api/collage-image/{name}")
async def serve_collage_image(name: str):
    safe = os.path.basename(name)
    if not safe.startswith("collage_") or not safe.endswith(".jpg"):
        raise HTTPException(404, "Not found")
    path = os.path.join(_COLLAGE_DIR, safe)
    if not os.path.exists(path):
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="image/jpeg")


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

async def _run_scan(job_id: int, keywords: list, max_per_keyword: int, source: str, brand_id: Optional[int] = None) -> None:
    try:
        await run_pipeline(job_id, keywords, max_per_keyword, source=source, brand_id=brand_id)
        await _backup_products_to_sheets()
    except Exception as e:
        log.error("Scan %d failed: %s", job_id, e)
        await db.update_job(job_id, status="error")

async def _run_ingest(job_id: int, products: list, brand_id: Optional[int] = None) -> None:
    try:
        await process_scraped_products(job_id, products, brand_id=brand_id)
        await _backup_products_to_sheets()
    except Exception as e:
        log.error("Ingest %d failed: %s", job_id, e)
        await db.update_job(job_id, status="error")

async def _post_and_export(products: list) -> None:
    if not products: return
    try:
        # Publish to website immediately — Instagram may still be in-flight
        for p in products:
            await db.set_stage(p["id"], ProductStage.LIVE.value)
            await db.log_post(p["id"])

        settings = await _settings()
        products = [await content_ai.maybe_rewrite_caption(db, p, settings) for p in products]
        results = await instagram.post_batch(products, settings)
        for p in products:
            res = next((r for r in results if r.product_id == p["id"]), None)
            if res:
                if res.status == "error":
                    log.warning("Instagram post failed for product %s: %s", p["id"], res.error)
                    await activity.record("post_failed", f"Instagram post failed for “{_pname(p)}”: {res.error}", product_id=p["id"], level="error")
                elif res.status in ("posted", "mock"):
                    if res.post_url:
                        p["instagram_url"] = res.post_url  # Update local object for sheets export
                        await db.update_product_fields(p["id"], {"instagram_url": res.post_url})
                    await activity.record("posted", f"Posted “{_pname(p)}” to Instagram" + (" (simulated — no token)" if res.status == "mock" else ""), product_id=p["id"], meta={"url": res.post_url})

        await asyncio.to_thread(sheets.append_rows, products)
        await _backup_products_to_sheets()
    except Exception as e:
        log.error("Post error: %s", e)

async def _process_ig_webhook(body: dict) -> None:
    try:
        settings = await _settings()
        await instagram_replies.process_webhook(body, settings, db)
    except Exception as exc:
        log.error("IG webhook processing failed: %s", exc)

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


