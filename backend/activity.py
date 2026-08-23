"""
Activity log — one row per thing the system (or the owner) did.

Powers the Home page feed ("what Autopilot did today"), the "needs you" list,
and error surfacing. Writing never raises: the log is observability, not a
dependency of the pipeline.

Kinds (free-form strings, these are the ones the UI knows):
  scan_started, scan_done, scan_failed
  auto_approved, auto_rejected, needs_review
  image_cleaned, image_clean_failed
  posted, post_failed, post_scheduled
  reply_sent, lead_received
  approved, rejected, reconsidered          (manual actions)
  config                                    (missing keys etc.)
"""

import json
import logging
from typing import Optional

log = logging.getLogger(__name__)

_db = None  # injected by main.py to avoid import cycles


def bind(db) -> None:
    global _db
    _db = db


async def record(kind: str, message: str, *, product_id: Optional[int] = None,
                 level: str = "info", meta: Optional[dict] = None) -> None:
    """Append an activity row. level: info | warn | error."""
    if _db is None:
        return
    try:
        await _db.log_activity(kind, message, product_id=product_id, level=level, meta=meta)
    except Exception as exc:  # never break the caller
        log.debug("activity.record failed: %s", exc)
