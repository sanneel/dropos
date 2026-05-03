"""
APScheduler cron — triggers full pipeline twice daily (09:00 and 21:00 UTC).
Reads scan_keywords from settings; falls back to DEFAULT_KEYWORDS.
"""

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from database import db
from runner import run_pipeline

log = logging.getLogger(__name__)

DEFAULT_KEYWORDS = [
    "aesthetic home decor",
    "minimalist room decor",
    "aesthetic lifestyle",
]


async def _run_scheduled_scan() -> None:
    settings = await db.get_settings()
    raw = settings.get("scan_keywords", DEFAULT_KEYWORDS)
    keywords: list = raw if isinstance(raw, list) else [raw]
    if not keywords:
        keywords = DEFAULT_KEYWORDS

    log.info("Scheduled scan triggered: %d keywords: %s", len(keywords), keywords)
    job_id = await db.create_job(keywords=keywords)
    summary = await run_pipeline(job_id, keywords, max_per_keyword=50, settings=settings)
    log.info("Scheduled scan complete: %s", summary)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    scheduler.add_job(
        _run_scheduled_scan,
        CronTrigger(hour=9, minute=0, timezone="UTC"),
        id="morning_scan",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _run_scheduled_scan,
        CronTrigger(hour=21, minute=0, timezone="UTC"),
        id="evening_scan",
        replace_existing=True,
        misfire_grace_time=300,
    )

    return scheduler


def get_scheduler_status(scheduler: Optional[AsyncIOScheduler]) -> dict:
    if not scheduler or not scheduler.running:
        return {"running": False, "jobs": []}

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })

    return {"running": True, "jobs": jobs}
