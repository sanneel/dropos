"""
Autopilot scan loop.

Every minute: read settings from the DB and, if Autopilot + auto-scan are on,
the scraper is configured and the last scan is older than scan_interval_hours,
run a scan with the saved keywords. Also performs housekeeping (auto-reject
stale pending items when auto_reject_pending_days > 0).

Manual scans (Scans page) and the legacy SCRAPE_INTERVAL env are unaffected:
SCRAPE_INTERVAL (seconds) is honoured as the interval when set.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import activity
import autopilot
from config.runtime import get_config, merge_env_with_settings
from database import db
from runner import run_pipeline

log = logging.getLogger(__name__)

_TICK_SECONDS = 60


class PipelineScheduler:
    def __init__(self):
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._last_error: Optional[str] = None
        self._last_run: Optional[str] = None
        self.scanning = False

    async def _loop(self):
        while self.running:
            await asyncio.sleep(_TICK_SECONDS)
            if not self.running:
                break
            try:
                settings = merge_env_with_settings(await db.get_settings())
                # Legacy env override: SCRAPE_INTERVAL seconds → hours
                env_interval = get_config("SCRAPE_INTERVAL", None)
                if env_interval:
                    try:
                        settings["scan_interval_hours"] = max(0.25, float(env_interval) / 3600)
                    except (TypeError, ValueError):
                        pass

                await self._housekeeping(settings)
                await self._keyword_generation(settings)

                if await db.get_active_job():
                    continue
                brand = await self._next_due_brand(settings)
                if not brand:
                    continue

                keywords = await self._pick_keywords(brand)
                if not keywords:
                    continue

                self.scanning = True
                await activity.record("scan_started", f"Autopilot scan for {brand['name']} — {len(keywords)} keywords: {', '.join(keywords[:4])}{'…' if len(keywords) > 4 else ''}",
                                      meta={"brand_id": brand["id"], "keywords": keywords})
                try:
                    await db.touch_keywords_scanned(brand["id"], keywords)
                    summary = await run_pipeline(keywords=keywords, max_per_keyword=50, settings=settings, brand_id=brand["id"])
                    self._last_run = f"brand={brand['name']} job={summary.get('job_id')} candidates={summary.get('after_score')}"
                    self._last_error = None
                    await activity.record("scan_done", f"{brand['name']}: scan finished — {summary.get('scraped', 0)} scraped, {summary.get('after_score', 0)} sent to AI scoring",
                                          meta={**summary, "brand_id": brand["id"]})
                    log.info("Autopilot scan complete: %s", summary)
                except Exception as exc:
                    self._last_error = str(exc)
                    await activity.record("scan_failed", f"{brand['name']}: scan failed: {exc}", level="error")
                    log.exception("Autopilot scan failed")
                finally:
                    self.scanning = False
            except Exception as exc:
                self._last_error = str(exc)
                log.exception("Scheduler tick failed")

    async def _next_due_brand(self, settings: dict):
        """Round-robin: the active brand whose last scan is oldest and past the interval."""
        if not autopilot.enabled(settings) or not autopilot._b(settings.get("auto_scan_enabled"), True):
            return None
        if not autopilot.has_scraper(settings):
            return None
        brands = [b for b in await db.list_brands() if b.get("active")]
        if not brands:
            return None
        due = []
        for b in brands:
            last = await db.fetchval("SELECT created_at FROM jobs WHERE brand_id=$1 ORDER BY id DESC LIMIT 1", b["id"])
            if autopilot.scan_due(settings, last):
                due.append((str(last or ""), b))
        if not due:
            return None
        due.sort(key=lambda x: x[0])   # oldest last-scan first
        return due[0][1]

    async def _pick_keywords(self, brand: dict) -> list:
        import keyword_lab
        keywords = await db.list_keywords(brand["id"])
        perf = await db.keyword_performance(brand["id"])
        limit = max(1, int(brand.get("keywords_per_scan") or 6))
        return keyword_lab.select(keywords, perf, limit)

    async def _keyword_generation(self, settings: dict) -> None:
        """Autopilot: top up each brand's keyword pool with AI-generated candidates."""
        if not autopilot.enabled(settings) or not autopilot.has_gemini(settings):
            return
        import keyword_lab
        for brand in await db.list_brands():
            if not brand.get("active"):
                continue
            try:
                keywords = await db.list_keywords(brand["id"])
                perf = await db.keyword_performance(brand["id"])
                if not keyword_lab.generation_due(brand, keywords, perf):
                    continue
                fresh = await keyword_lab.generate(brand, keywords, perf, settings)
                await db.update_brand(brand["id"], {"last_keywords_generated_at": datetime.now(timezone.utc).isoformat()})
                if fresh:
                    added = await db.add_keywords(brand["id"], fresh, source="ai")
                    await activity.record("keywords_generated", f"{brand['name']}: AI added {added} new keywords — {', '.join(fresh[:5])}{'…' if len(fresh) > 5 else ''}",
                                          meta={"brand_id": brand["id"], "keywords": fresh})
            except Exception as exc:
                log.warning("Keyword generation for brand %s failed: %s", brand.get("id"), exc)

    async def _housekeeping(self, settings: dict) -> None:
        days = 0
        try:
            days = int(float(settings.get("auto_reject_pending_days") or 0))
        except (TypeError, ValueError):
            days = 0
        if not autopilot.enabled(settings) or days <= 0:
            return
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        n = await db.reject_stage_older_than("ENRICHED", cutoff, f"Autopilot: not reviewed within {days} days")
        if n:
            await activity.record("auto_rejected", f"Auto-rejected {n} pending products older than {days} days", level="warn")

    def start(self):
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop(), name="autopilot-scan-loop")

    def shutdown(self, wait: bool = False):
        self.running = False
        if self._task and not self._task.done():
            self._task.cancel()

    def get_jobs(self):
        return [{"id": "autopilot_scan", "tick_seconds": _TICK_SECONDS, "last_run": self._last_run, "last_error": self._last_error, "scanning": self.scanning}]


def create_scheduler() -> PipelineScheduler:
    return PipelineScheduler()


def get_scheduler_status(scheduler: Optional[PipelineScheduler]) -> dict:
    if not scheduler or not scheduler.running:
        return {"running": False, "jobs": []}
    return {"running": True, "jobs": scheduler.get_jobs()}
