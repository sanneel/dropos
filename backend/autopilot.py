"""
Autopilot — the hands-off policy layer.

Settings (all in the settings table, editable from the Home page):
  autopilot_enabled        master switch; when off every stage below is paused
  auto_scan_enabled        run scans with scan_keywords every scan_interval_hours
  scan_interval_hours
  auto_approve_enabled     approve AI winners without a human
  auto_approve_min_score   composite threshold (e.g. 7.0)
  auto_approve_verdicts    which verdicts qualify (top_priority / strong_candidate)
  auto_clean_images        run Clipdrop automatically on has_chinese_text winners
  auto_reject_pending_days auto-reject items nobody reviewed after N days (0 = never)
  post_schedule_enabled    peak-hour posting (posting_scheduler.py)
  post_times / post_timezone / posts_per_slot / max_posts_per_day
  instagram_auto_reply_enabled / instagram_dm_reply_enabled   (instagram_replies.py)

Nothing here talks to external APIs directly; it decides, and the worker /
schedulers act.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config.runtime import get_config

log = logging.getLogger(__name__)


# ── Small helpers ──────────────────────────────────────────────────────────────

def _b(v, default=False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _today_start_iso(tz_name: str = "Asia/Tbilisi") -> str:
    try:
        from zoneinfo import ZoneInfo
        now_local = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now_local = datetime.now(timezone.utc)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return _iso(start_local)


def enabled(settings: dict) -> bool:
    return _b(settings.get("autopilot_enabled"))


# ── Readiness of each stage (what is missing) ──────────────────────────────────

def has_ai(settings: dict) -> bool:
    return bool(get_config("GEMINI_KEY", settings.get("gemini_key", "")) or get_config("GROQ_KEY", settings.get("groq_key", "")))


def has_gemini(settings: dict) -> bool:
    return bool(get_config("GEMINI_KEY", settings.get("gemini_key", "")))


def has_scraper(settings: dict) -> bool:
    return bool(settings.get("cssbuy_username") and settings.get("cssbuy_password")) and not _b(settings.get("local_scraping_only"))


def has_instagram(settings: dict) -> bool:
    import instagram
    return instagram.backend_mode(settings) != "none"


def instagram_mode(settings: dict) -> str:
    import instagram
    return instagram.backend_mode(settings)


def has_clipdrop(settings: dict) -> bool:
    return bool(str(settings.get("clipdrop_key") or "").strip())


def has_public_url(settings: dict) -> bool:
    return str(settings.get("public_base_url") or "").startswith("https://")


# ── Decisions ──────────────────────────────────────────────────────────────────

def approval_decision(res: dict, settings: dict) -> Optional[str]:
    """
    Given a normalised AI result for a product that passed store_match, decide:
      "approve"  → straight to REVIEWED (or TEXT_REMOVAL / clean if Chinese text)
      None       → leave in the human review queue (ENRICHED)
    """
    if not enabled(settings) or not _b(settings.get("auto_approve_enabled"), True):
        return None
    provider = str(res.get("ai_provider") or "")
    if provider == "mock":
        return None  # never auto-approve unscored products
    verdict = str(res.get("verdict") or "")
    allowed = settings.get("auto_approve_verdicts") or ["top_priority", "strong_candidate"]
    if isinstance(allowed, str):
        allowed = [a.strip() for a in allowed.split(",") if a.strip()]
    composite = _f(res.get("composite_score") or res.get("score"))
    if verdict in allowed and composite >= _f(settings.get("auto_approve_min_score"), 7.0):
        return "approve"
    return None


def should_auto_clean(settings: dict) -> bool:
    return enabled(settings) and _b(settings.get("auto_clean_images"), True) and has_clipdrop(settings)


def scan_due(settings: dict, last_job_iso: Optional[str]) -> bool:
    """True when autopilot scanning is on, the scraper is configured, and the
    last scan is older than scan_interval_hours (or there was never one)."""
    if not enabled(settings) or not _b(settings.get("auto_scan_enabled"), True):
        return False
    if not has_scraper(settings):
        return False
    hours = max(0.25, _f(settings.get("scan_interval_hours"), 12))
    if not last_job_iso:
        return True
    try:
        last = datetime.fromisoformat(str(last_job_iso).replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
    except Exception:
        return True
    return datetime.now(timezone.utc) - last >= timedelta(hours=hours)


def _content_writer(settings: dict) -> str:
    """Short label of the content model that rewrites captions, or '' when off."""
    try:
        import content_ai
        if _b(settings.get("content_rewrite_enabled"), True) and content_ai.content_ready(settings):
            return content_ai.pick_provider(settings) or ""
    except Exception:
        pass
    return ""


def posting_allowed(settings: dict) -> bool:
    return enabled(settings) and _b(settings.get("post_schedule_enabled"), False) and has_instagram(settings)


# ── Status for the Home page ───────────────────────────────────────────────────

async def status(db, settings: dict, posting_jobs: list | None = None, scan_loop_running: bool = False) -> dict:
    """
    One object describing every automated stage: on/off, ready (has what it
    needs), blockers (what to configure), today's counts, next run.
    """
    tz = str(settings.get("post_timezone") or "Asia/Tbilisi")
    today = _today_start_iso(tz)
    counts = await db.activity_counts(today)
    stats = await db.get_stats()
    inbox = await db.inbox_counts()
    last_job = await db.last_job_time()
    posts_today = await db.count_posts_since(today)
    master = enabled(settings)

    def stage(key, label, on, ready, blockers, **extra):
        d = {"key": key, "label": label, "on": bool(on), "ready": bool(ready), "blockers": blockers,
             "active": bool(master and on and ready)}
        d.update(extra)
        return d

    scan_hours = max(0.25, _f(settings.get("scan_interval_hours"), 12))
    next_scan = None
    if last_job:
        try:
            last = datetime.fromisoformat(str(last_job).replace("Z", "+00:00"))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            next_scan = _iso(last + timedelta(hours=scan_hours))
        except Exception:
            next_scan = None

    brands = await db.list_brands()
    active_brands = [b for b in brands if b.get("active")]
    kw_counts = {}
    for b in active_brands:
        kw_counts[b["id"]] = sum(1 for k in await db.list_keywords(b["id"]) if k.get("status") == "active")

    scan_blockers = []
    if _b(settings.get("local_scraping_only")):
        scan_blockers.append("Server scraping is disabled (local scraping only)")
    elif not (settings.get("cssbuy_username") and settings.get("cssbuy_password")):
        scan_blockers.append("Add your CSSBuy login in Settings → Connections")
    if not active_brands:
        scan_blockers.append("No active brands — create one on the Brands page")
    elif not any(kw_counts.values()):
        scan_blockers.append("No active keywords — add or generate some on the Brands page")

    score_blockers = [] if has_ai(settings) else ["Add a Gemini key (free) in Settings → Connections"]
    if has_ai(settings) and not has_gemini(settings):
        score_blockers.append("Only Groq (text-only) configured — add Gemini for image scoring")

    approve_blockers = [] if has_ai(settings) else ["Needs AI scoring to judge products"]
    clean_blockers = [] if has_clipdrop(settings) else ["Add a Clipdrop key in Settings → Connections"]
    ig_mode = instagram_mode(settings)
    post_blockers = [] if ig_mode != "none" else ["Connect Instagram in Settings → Connections (direct login — no Meta account needed)"]
    reply_blockers = []
    if ig_mode == "none":
        reply_blockers.append("Connect Instagram first (direct login works without a Meta account)")
    elif ig_mode == "graph" and not has_public_url(settings):
        reply_blockers.append("Official API needs a public HTTPS webhook URL — or switch to direct login (polls instead)")

    stages = [
        stage("scan", "Find products", _b(settings.get("auto_scan_enabled"), True), not scan_blockers, scan_blockers,
              detail=f"every {scan_hours:g}h · {len(active_brands)} brand{'s' if len(active_brands) != 1 else ''} · {sum(kw_counts.values())} keywords",
              next_run=next_scan, last_run=last_job, today=counts.get("scan_done", 0) + counts.get("scan_started", 0),
              running=scan_loop_running),
        stage("score", "AI scoring", True, not score_blockers, score_blockers,
              detail="Gemini vision on every scraped product",
              today=(counts.get("auto_approved", 0) + counts.get("needs_review", 0) + counts.get("auto_rejected", 0)),
              queue=stats.get("SCRAPED", 0)),
        stage("approve", "Auto-approve", _b(settings.get("auto_approve_enabled"), True), not approve_blockers, approve_blockers,
              detail=f"score ≥ {_f(settings.get('auto_approve_min_score'), 7.0):g} · {', '.join(settings.get('auto_approve_verdicts') or ['top_priority','strong_candidate']).replace('_',' ')}",
              today=counts.get("auto_approved", 0), needs_you=stats.get("ENRICHED", 0)),
        stage("clean", "Clean photos", _b(settings.get("auto_clean_images"), True), not clean_blockers, clean_blockers,
              detail="remove Chinese text / watermarks (Clipdrop)",
              today=counts.get("image_cleaned", 0), needs_you=stats.get("TEXT_REMOVAL", 0)),
        stage("post", "Post to Instagram", _b(settings.get("post_schedule_enabled"), False), not post_blockers, post_blockers,
              detail=f"{', '.join(settings.get('post_times') or ['19:00','21:00'])} {tz} · max {int(_f(settings.get('max_posts_per_day'), 2))}/day" + (f" · captions by {_content_writer(settings)}" if _content_writer(settings) else ""),
              today=posts_today, queue=stats.get("REVIEWED", 0),
              next_run=min([j.get("next_run") for j in (posting_jobs or []) if j.get("next_run")], default=None)),
        stage("reply", "Answer comments & DMs", _b(settings.get("instagram_auto_reply_enabled")) or _b(settings.get("instagram_dm_reply_enabled")),
              not reply_blockers, reply_blockers,
              detail=f"{len(settings.get('instagram_reply_rules') or [])} comment rules · {len(settings.get('instagram_dm_rules') or [])} DM rules"
                     + (f" · polls every {int(_f(settings.get('ig_poll_minutes'), 5))}m" if ig_mode == "private" else " · webhook"),
              today=counts.get("reply_sent", 0), leads=inbox.get("leads", 0), open=inbox.get("open", 0)),
    ]

    # "Needs you" — things only a human can do right now
    needs = []
    if stats.get("ENRICHED", 0):
        needs.append({"kind": "review", "count": stats["ENRICHED"], "label": "products waiting for your decision", "page": "review"})
    if stats.get("TEXT_REMOVAL", 0):
        needs.append({"kind": "clean", "count": stats["TEXT_REMOVAL"], "label": "photos need text removed", "page": "review:textEdit"})
    if inbox.get("leads", 0):
        needs.append({"kind": "lead", "count": inbox["leads"], "label": "possible orders in the inbox", "page": "inbox"})
    failed = counts.get("post_failed", 0) + counts.get("scan_failed", 0) + counts.get("image_clean_failed", 0)
    if failed:
        needs.append({"kind": "error", "count": failed, "label": "automation errors today", "page": "home:activity"})
    if stats.get("REVIEWED", 0) and not has_instagram(settings):
        needs.append({"kind": "config", "count": stats["REVIEWED"], "label": "approved products can't be posted — connect Instagram", "page": "settings:connections"})
    if not has_ai(settings):
        needs.append({"kind": "config", "count": 0, "label": "no AI key — products are not being scored", "page": "settings:connections"})

    return {
        "enabled": master,
        "stages": stages,
        "needs_you": needs,
        "today": {
            "scanned": counts.get("scan_done", 0),
            "scored": counts.get("auto_approved", 0) + counts.get("needs_review", 0) + counts.get("auto_rejected", 0),
            "auto_approved": counts.get("auto_approved", 0),
            "auto_rejected": counts.get("auto_rejected", 0),
            "needs_review": counts.get("needs_review", 0),
            "cleaned": counts.get("image_cleaned", 0),
            "posted": posts_today,
            "replies": counts.get("reply_sent", 0),
            "leads": counts.get("lead_received", 0),
            "errors": failed,
        },
        "stats": stats,
        "inbox": inbox,
    }
