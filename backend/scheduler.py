"""
Simple async scheduler loop.
Runs pipeline continuously with configurable interval.
"""

import asyncio
import logging
from typing import Optional

from config.runtime import get_config, merge_env_with_settings
from database import db
from runner import run_pipeline

log = logging.getLogger(__name__)

DEFAULT_KEYWORDS = [
    "aesthetic home decor",
    "minimalist room decor",
    "aesthetic lifestyle",
]


class PipelineScheduler:
    def __init__(self):
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._last_error: Optional[str] = None
        self._last_run: Optional[str] = None

    async def _loop(self):
        while self.running:
            interval = int(get_config("SCRAPE_INTERVAL", 3600))
            await asyncio.sleep(max(interval, 60))
            if not self.running:
                break
            try:
                settings = merge_env_with_settings(await db.get_settings())
                raw = get_config("SCAN_KEYWORDS", settings.get("scan_keywords", DEFAULT_KEYWORDS))
                keywords: list = raw if isinstance(raw, list) else [raw]
                if not keywords:
                    keywords = DEFAULT_KEYWORDS
                active = await db.get_active_job()
                if active:
                    log.info(
                        "Scheduled pipeline skipped: job %s already %s",
                        active.get("id"),
                        active.get("status"),
                    )
                    self._last_run = f"skipped active_job={active.get('id')}"
                    self._last_error = None
                    continue
                summary = await run_pipeline(keywords=keywords, max_per_keyword=50, settings=settings)
                self._last_run = f"job={summary.get('job_id')} passed_ai={summary.get('passed_ai')}"
                self._last_error = None
                log.info("Scheduled pipeline complete: %s", summary)
            except Exception as exc:
                self._last_error = str(exc)
                log.exception("Scheduled pipeline failed")


    def start(self):
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop(), name="pipeline-scheduler")

    def shutdown(self, wait: bool = False):
        self.running = False
        if self._task and not self._task.done():
            self._task.cancel()

    def get_jobs(self):
        return [{"id": "pipeline_loop", "interval": int(get_config("SCRAPE_INTERVAL", 3600))}]


def create_scheduler() -> PipelineScheduler:
    return PipelineScheduler()


def get_scheduler_status(scheduler: Optional[PipelineScheduler]) -> dict:
    if not scheduler or not scheduler.running:
        return {"running": False, "jobs": []}
    return {"running": True, "jobs": scheduler.get_jobs()}
