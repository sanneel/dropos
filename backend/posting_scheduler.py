"""
Peak-hour auto-posting scheduler for DropOS.

Posts approved products to Instagram at optimal times for maximum reach.

Default schedule: 19:00 and 21:00 Georgian time (Asia/Tbilisi = UTC+4).
Both times are configurable in Settings.

Settings used:
  - post_schedule_enabled  (bool, default True)  — master on/off switch
  - post_times             (list, default ["19:00","21:00"]) — HH:MM in post_timezone
  - post_timezone          (str,  default "Asia/Tbilisi")
  - posts_per_slot         (int,  default 1) — how many products to post per time slot
    Keep this at 1 unless you want aggressive posting. Instagram may flag rapid-fire posts.
"""

import asyncio
import logging
import httpx
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

    scheduler = AsyncIOScheduler()

    async def _post_top_approved() -> None:
        """Inner job: grab highest-scoring approved products and post them."""
        try:
            settings = await get_settings_fn()

            if not settings.get("post_schedule_enabled", True):
                log.info("Peak-post: disabled in settings — skipping")
                return

            posts_per_slot = max(1, int(settings.get("posts_per_slot", 1)))
            products = await db.get_products(
                stage="approved", limit=posts_per_slot, sort="score"
            )

            if not products:
                log.info("Peak-post: no approved products in queue")
                return

            log.info("Peak-post: posting %d product(s) at peak hour", len(products))
            results = await instagram.post_batch(products, settings)

            for product, result in zip(products, results):
                pid = product["id"]
                if result.status in {"posted", "mock"}:
                    await db.set_stage(pid, "posted")
                    await db.log_post(pid)
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

    async def _fetch_exchange_rate() -> None:
        """Daily job: fetch latest CNY->EUR exchange rate and update settings."""
        try:
            log.info("Fetching latest exchange rate from Frankfurter API...")
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get("https://api.frankfurter.app/latest?from=CNY&to=EUR")
                r.raise_for_status()
                data = r.json()
                rate = data.get("rates", {}).get("EUR")
                if rate:
                    log.info(f"Successfully fetched exchange rate: {rate}")
                    await db.update_settings({"exchange_rate": float(rate)})
                else:
                    log.warning("Exchange rate not found in API response.")
        except Exception as exc:
            log.error("Failed to fetch exchange rate, falling back to DB rate: %s", exc)

    # ── Build cron jobs from settings ─────────────────────────────────────────
    # We read settings once at startup. If the user changes post_times, they
    # need to restart the server. (Acceptable trade-off for simplicity.)

    async def _init_jobs() -> None:
        """Called once after the app starts to schedule posting from live settings."""
        try:
            settings = await get_settings_fn()
            post_times: list = settings.get("post_times", ["19:00", "21:00"])
            timezone: str = settings.get("post_timezone", "Asia/Tbilisi")

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

            # Schedule the daily exchange rate fetcher at midnight
            scheduler.add_job(
                _fetch_exchange_rate,
                trigger=CronTrigger(hour=0, minute=0, timezone=timezone),
                id="daily_exchange_rate_fetch",
                replace_existing=True,
                misfire_grace_time=300,
            )
            log.info("Daily exchange rate fetcher scheduled at 00:00 %s", timezone)

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
