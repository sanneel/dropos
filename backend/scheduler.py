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

                last_job = await db.last_job_time()
                if not autopilot.scan_due(settings, last_job):
                    continue
                if await db.get_active_job():
                    continue

                keywords = settings.get("scan_keywords") or []
                if isinstance(keywords, str):
                    keywords = [k.strip() for k in keywords.split(",") if k.strip()]
                if not keywords:
                    continue

                self.scanning = True
                await activity.record("scan_started", f"Autopilot scan started — {len(keywords)} keywords")
                try:
                    summary = await run_pipeline(keywords=keywords, max_per_keyword=50, settings=settings)
                    self._last_run = f"job={summary.get('job_id')} candidates={summary.get('after_score')}"
                    self._last_error = None
                    await activity.record("scan_done", f"Scan finished: {summary.get('scraped', 0)} scraped, {summary.get('after_score', 0)} sent to AI scoring",
                                          meta=summary)
                    log.info("Autopilot scan complete: %s", summary)
                except Exception as exc:
                    self._last_error = str(exc)
                    await activity.record("scan_failed", f"Scan failed: {exc}", level="error")
                    log.exception("Autopilot scan failed")
                finally:
                    self.scanning = False
            except Exception as exc:
                self._last_error = str(exc)
                log.exception("Scheduler tick failed")

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
