"""
Instagram comment / DM auto-reply engine.

Driven by the Meta webhook (`POST /api/instagram/webhook`). Rules come from
Settings:

    instagram_auto_reply_enabled  bool
    instagram_reply_rules         [{"keywords": [...], "reply": "..."}]   comments
    instagram_dm_reply_enabled    bool
    instagram_dm_rules            [{"keywords": [...], "reply": "..."}]   DMs

The first rule whose keyword appears in the (lower-cased) text wins; a rule
with no keywords is a catch-all. Every reply is logged in comment_reply_log so
a redelivered webhook never answers twice.

Requires a public HTTPS URL for the webhook (Meta must reach it) and the
`instagram_manage_comments` / `instagram_manage_messages` permissions on the
Page access token.
"""

import hashlib
import hmac
import logging
from typing import Optional

import httpx

from instagram import _graph, _token
import activity

log = logging.getLogger(__name__)


def is_lead(text: str, settings: dict) -> bool:
    """Does this message look like purchase intent? (keyword list in settings)"""
    t = (text or "").lower()
    kws = settings.get("lead_keywords") or []
    if isinstance(kws, str):
        kws = [k.strip() for k in kws.split(",") if k.strip()]
    return any(str(k).lower() in t for k in kws if str(k).strip())


# ── Rule matching ──────────────────────────────────────────────────────────────

def match_rule(text: str, rules: list) -> Optional[dict]:
    """Return the first matching rule (dict with 'reply') or None."""
    t = (text or "").lower()
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        reply = str(rule.get("reply") or "").strip()
        if not reply:
            continue
        keywords = [str(k).strip().lower() for k in (rule.get("keywords") or []) if str(k).strip()]
        if not keywords or any(k in t for k in keywords):
            return {"reply": reply, "keywords": keywords}
    return None


def verify_signature(app_secret: str, raw_body: bytes, header: str) -> bool:
    """Validate X-Hub-Signature-256 when an app secret is configured."""
    if not app_secret:
        return True  # not configured → cannot verify, accept
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[7:])


# ── Graph API calls ────────────────────────────────────────────────────────────

async def _reply_to_comment(client: httpx.AsyncClient, comment_id: str, message: str, settings: dict) -> bool:
    resp = await client.post(
        f"{_graph(settings)}/{comment_id}/replies",
        params={"message": message, "access_token": _token(settings)},
    )
    body = resp.json() if resp.content else {}
    if resp.status_code != 200 or "error" in body:
        log.warning("IG comment reply failed (%s): %s", comment_id, body.get("error", body))
        return False
    return True


async def _send_dm(client: httpx.AsyncClient, ig_user_id: str, recipient_id: str, message: str, settings: dict) -> bool:
    resp = await client.post(
        f"{_graph(settings)}/{ig_user_id}/messages",
        params={"access_token": _token(settings)},
        json={"recipient": {"id": recipient_id}, "message": {"text": message}},
    )
    body = resp.json() if resp.content else {}
    if resp.status_code != 200 or "error" in body:
        log.warning("IG DM reply failed (%s): %s", recipient_id, body.get("error", body))
        return False
    return True


async def send_reply(message: dict, text: str, settings: dict) -> bool:
    """Reply to an inbox message (comment → comment reply, dm → DM). Used by the Inbox page."""
    token = _token(settings)
    if not token:
        return False
    async with httpx.AsyncClient(timeout=20) as client:
        if message.get("kind") == "comment":
            return await _reply_to_comment(client, str(message.get("external_id", "")).removeprefix("c:"), text, settings)
        own_id = str(settings.get("instagram_user_id") or "")
        return await _send_dm(client, own_id, str(message.get("sender_id") or ""), text, settings)


# ── Webhook processing ─────────────────────────────────────────────────────────

async def process_webhook(body: dict, settings: dict, db) -> dict:
    """
    Handle one webhook delivery. Returns counters for logging/tests.
    Never raises — failures are logged and counted.
    """
    stats = {"comments_seen": 0, "comments_replied": 0, "dms_seen": 0, "dms_replied": 0}
    if not isinstance(body, dict) or body.get("object") not in ("instagram", "page"):
        return stats

    own_id = str(settings.get("instagram_user_id") or "").strip()
    token = _token(settings)
    comments_on = bool(settings.get("instagram_auto_reply_enabled"))
    dms_on = bool(settings.get("instagram_dm_reply_enabled"))
    comment_rules = settings.get("instagram_reply_rules") or []
    dm_rules = settings.get("instagram_dm_rules") or []

    async def _capture(external_id: str, kind: str, sender_id: str, sender_name: str, text: str, media_id: str = "", reply: str = "") -> None:
        """Store every incoming message in the inbox; flag order intent."""
        try:
            lead = is_lead(text, settings)
            new_id = await db.inbox_add(external_id, kind, sender_id, sender_name, text, media_id, is_lead=lead, auto_reply=reply)
            if new_id and lead:
                await activity.record("lead_received", f"Possible order from {sender_name or sender_id}: “{(text or '')[:80]}”", meta={"inbox_id": new_id, "kind": kind}, level="warn")
        except Exception as exc:
            log.debug("inbox capture failed: %s", exc)

    # Capture everything even when replies are off — the inbox is useful on its own
    if not token:
        token = ""

    async with httpx.AsyncClient(timeout=20) as client:
        for entry in body.get("entry") or []:
            entry_owner = str(entry.get("id") or own_id)

            # ── Comments (field "comments") ─────────────────────────────────
            for change in entry.get("changes") or []:
                if change.get("field") != "comments":
                    continue
                value = change.get("value") or {}
                comment_id = str(value.get("id") or "")
                text = value.get("text") or ""
                sender = str((value.get("from") or {}).get("id") or "")
                if not comment_id or not text:
                    continue
                stats["comments_seen"] += 1
                if own_id and sender == own_id:
                    continue  # our own reply echoed back
                sender_name = str((value.get("from") or {}).get("username") or "")
                rule = match_rule(text, comment_rules) if (comments_on and token) else None
                await _capture(f"c:{comment_id}", "comment", sender, sender_name, text, str((value.get("media") or {}).get("id") or ""), rule["reply"] if rule else "")
                if not rule:
                    continue
                if await db.has_replied_to_comment(comment_id):
                    continue
                try:
                    ok = await _reply_to_comment(client, comment_id, rule["reply"], settings)
                except Exception as exc:
                    log.warning("IG comment reply error: %s", exc)
                    ok = False
                if ok:
                    stats["comments_replied"] += 1
                    await db.log_comment_reply(comment_id, ",".join(rule["keywords"]) or "*", "comment")
                    await activity.record("reply_sent", f"Replied to a comment from {sender_name or sender}: “{rule['reply'][:60]}”")

            # ── Direct messages (field "messages" → messaging events) ───────
            for event in entry.get("messaging") or []:
                msg = event.get("message") or {}
                if not msg or msg.get("is_echo"):
                    continue
                mid = str(msg.get("mid") or "")
                text = msg.get("text") or ""
                sender = str((event.get("sender") or {}).get("id") or "")
                if not mid or not text or not sender:
                    continue
                stats["dms_seen"] += 1
                if own_id and sender == own_id:
                    continue
                rule = match_rule(text, dm_rules) if (dms_on and token) else None
                await _capture(f"m:{mid}", "dm", sender, "", text, "", rule["reply"] if rule else "")
                if not rule:
                    continue
                if await db.has_replied_to_comment(mid):
                    continue
                try:
                    ok = await _send_dm(client, own_id or entry_owner, sender, rule["reply"], settings)
                except Exception as exc:
                    log.warning("IG DM reply error: %s", exc)
                    ok = False
                if ok:
                    stats["dms_replied"] += 1
                    await db.log_comment_reply(mid, ",".join(rule["keywords"]) or "*", "dm")
                    await activity.record("reply_sent", f"Replied to a DM from {sender}: “{rule['reply'][:60]}”")

    if stats["comments_seen"] or stats["dms_seen"]:
        log.info("IG webhook: %s", stats)
    return stats
