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
import random
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
    import activity
    import autopilot
    import content_ai
    import instagram
    import instagram_private
    from models import ProductStage

    scheduler = AsyncIOScheduler()

    async def _post_top_approved() -> None:
        """Inner job: grab highest-scoring approved products and post them."""
        try:
            settings = await get_settings_fn()

            if not autopilot.posting_allowed(settings):
                log.debug("Peak-post: autopilot posting off / Instagram not connected — skipping")
                return

            # Direct-login safety: never post during quiet hours or an action block
            import instagram_private
            if instagram.backend_mode(settings) == "private":
                if instagram_private.in_quiet_hours(settings):
                    log.info("Peak-post: quiet hours — skipping")
                    return
                if instagram_private.posting_blocked():
                    log.info("Peak-post: posting paused (action block) — skipping")
                    return

            # Human jitter: wait a random slice of the slot so posts don't fire at
            # exactly HH:MM:00 every day.
            jitter = int(float(settings.get("ig_post_jitter_min") or 0))
            if jitter > 0:
                wait = random.randint(0, jitter * 60)
                log.info("Peak-post: jitter %ds before posting", wait)
                await asyncio.sleep(wait)
                settings = await get_settings_fn()

            posts_per_slot = max(1, int(settings.get("posts_per_slot", 1)))
            max_per_day = max(1, int(float(settings.get("max_posts_per_day") or 2)))
            already = await db.count_posts_since(autopilot._today_start_iso(str(settings.get("post_timezone") or "Asia/Tbilisi")))
            remaining = max_per_day - already
            if remaining <= 0:
                log.info("Peak-post: daily cap reached (%d/%d)", already, max_per_day)
                return
            products = await db.get_products(
                stage=ProductStage.REVIEWED.value, limit=min(posts_per_slot, remaining), sort="score"
            )

            if not products:
                log.info("Peak-post: no approved products in queue")
                return

            log.info("Peak-post: posting %d product(s) at peak hour", len(products))
            products = [await content_ai.maybe_rewrite_caption(db, p, settings) for p in products]
            results = await instagram.post_batch(products, settings)

            for product, result in zip(products, results):
                pid = product["id"]
                name = (product.get("product_name") or product.get("title_translated") or "")[:60]
                if result.status in {"posted", "mock"}:
                    await db.set_stage(pid, ProductStage.LIVE.value)
                    await db.log_post(pid)
                    if result.post_url:
                        await db.update_product_fields(pid, {"instagram_url": result.post_url})
                    log.info(
                        "Peak-post ✓ product_id=%d status=%s", pid, result.status
                    )
                    await activity.record("posted", f"Posted “{name}” at peak hour" + (" (simulated — no token)" if result.status == "mock" else ""),
                                          product_id=pid, meta={"url": result.post_url})
                else:
                    err = result.error or "unknown error"
                    await db.update_product_note(
                        pid, f"Peak-hour auto-post failed: {err}"
                    )
                    log.warning(
                        "Peak-post ✗ product_id=%d error=%s", pid, err
                    )
                    await activity.record("post_failed", f"Peak-hour post failed for “{name}”: {err}", product_id=pid, level="error")

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
