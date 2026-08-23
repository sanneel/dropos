"""
Peak-hour auto-posting scheduler for DropOS.

Posts approved products to Instagram at optimal times for maximum reach.

Default schedule: 19:00 and 21:00 Georgian time (Asia/Tbilisi = UTC+4).
Both times are configurable in Settings.

Settings used:
  - post_schedule_enabled  (bool, default False) — master on/off switch
  - post_times             (list, default ["19:00","21:00"]) — HH:MM in post_timezone
  - post_timezone          (str,  default "Asia/Tbilisi")
  - posts_per_slot         (int,  default 1) — how many products to post per time slot
    Keep this at 1 unless you want aggressive posting. Instagram may flag rapid-fire posts.
"""

import asyncio
import logging
from typing import Callable, Coroutine

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)


def create_posting_scheduler(get_settings_fn: Callable[[], Coroutine]) -> AsyncIOScheduler:
    """Create an APScheduler that posts approved products at peak hours.

    Args:
        get_settings_fn: Async callable that returns the current settings dict.
                         (Pass main.py's `_settings` function.)

    Returns:
        Configured AsyncIOScheduler, not yet started.
        Call `.start()` in your app lifespan.
    """
    # Import here to avoid circular imports at module level
    from database import db
    import instagram
    from models import ProductStage

    scheduler = AsyncIOScheduler()

    async def _post_top_approved() -> None:
        """Inner job: grab highest-scoring approved products and post them."""
        try:
            settings = await get_settings_fn()

            if not settings.get("post_schedule_enabled", False):
                log.debug("Peak-post: disabled in settings — skipping")
                return

            posts_per_slot = max(1, int(settings.get("posts_per_slot", 1)))
            products = await db.get_products(
                stage=ProductStage.REVIEWED.value, limit=posts_per_slot, sort="score"
            )

            if not products:
                log.info("Peak-post: no approved products in queue")
                return

            log.info("Peak-post: posting %d product(s) at peak hour", len(products))
            results = await instagram.post_batch(products, settings)

            for product, result in zip(products, results):
                pid = product["id"]
                if result.status in {"posted", "mock"}:
                    await db.set_stage(pid, ProductStage.LIVE.value)
                    await db.log_post(pid)
                    if result.post_url:
                        await db.update_product_fields(pid, {"instagram_url": result.post_url})
                    log.info(
                        "Peak-post ✓ product_id=%d status=%s", pid, result.status
                    )
                else:
                    err = result.error or "unknown error"
                    await db.update_product_note(
                        pid, f"Peak-hour auto-post failed: {err}"
                    )
                    log.warning(
                        "Peak-post ✗ product_id=%d error=%s", pid, err
                    )

        except Exception as exc:
            log.error("Peak-post job crashed: %s", exc, exc_info=True)

    # ── Build cron jobs from settings ─────────────────────────────────────────
    # Planned at startup and re-planned by main.py whenever post_times /
    # post_timezone are saved in Settings.

    async def _init_jobs() -> None:
        """Called once after the app starts to schedule posting from live settings."""
        try:
            settings = await get_settings_fn()
            post_times: list = settings.get("post_times") or ["19:00", "21:00"]
            if isinstance(post_times, str):
                post_times = [t for t in post_times.split(",") if t.strip()]
            timezone: str = settings.get("post_timezone") or "Asia/Tbilisi"

            # Drop previously planned slots so a shorter list does not leave stale jobs
            for job in list(scheduler.get_jobs()):
                if str(job.id).startswith("peak_post_"):
                    scheduler.remove_job(job.id)

            for i, time_str in enumerate(post_times):
                try:
                    hour_str, minute_str = time_str.strip().split(":")
                    hour, minute = int(hour_str), int(minute_str)
                    scheduler.add_job(
                        _post_top_approved,
                        trigger=CronTrigger(
                            hour=hour,
                            minute=minute,
                            timezone=timezone,
                        ),
                        id=f"peak_post_{i}",
                        replace_existing=True,
                        misfire_grace_time=300,  # 5-min grace if server was briefly down
                    )
                    log.info(
                        "Peak-post job scheduled: %s %s", time_str, timezone
                    )
                except Exception as exc:
                    log.warning(
                        "Could not schedule post job '%s': %s", time_str, exc
                    )

        except Exception as exc:
            log.error("Peak-post scheduler init failed: %s", exc)

    # Store init_jobs so main.py can call it after the DB is ready
    scheduler._dropos_init_jobs = _init_jobs  # type: ignore[attr-defined]

    return scheduler


def get_posting_scheduler_status(scheduler: AsyncIOScheduler | None) -> dict:
    """Return a simple status dict for the API endpoint."""
    if not scheduler:
        return {"running": False, "jobs": []}

    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append({
            "id":       job.id,
            "next_run": next_run.isoformat() if next_run else None,
            "trigger":  str(job.trigger),
        })

    return {
        "running": scheduler.running,
        "jobs":    jobs,
    }
