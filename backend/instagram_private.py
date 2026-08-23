"""
Instagram "Direct login" backend — no Meta developer account needed.

Uses the community instagrapi library (Instagram's private mobile API) with your
plain Instagram username + password. Running from a home PC (residential IP) is
the good case for this approach. It covers everything DropOS needs:

  • posting photos / albums with captions        → post_product()
  • reading comments on your own recent posts    → poll() → Inbox + auto-reply
  • reading and answering DMs                    → poll() / reply()

Honest notes:
  - This is against Instagram's ToS; accounts doing aggressive automation get
    action-blocked. DropOS keeps volumes human (posting capped per day, polling
    every few minutes, randomized delays between calls).
  - Instagram sometimes asks for a verification code / in-app approval
    ("challenge"). We surface that on the Home page; approve the login in the
    Instagram app or submit the e-mail/SMS code in Settings, then retry.

The session (cookies/device) is persisted in DATA_DIR/ig_session.json so a
successful login survives restarts and re-login is rare.
"""

import asyncio
import logging
import os
import tempfile
import time
from typing import Optional

import httpx

from config.paths import data_path

log = logging.getLogger(__name__)

SESSION_FILE = data_path("ig_session.json", is_file=True)

_client = None            # instagrapi.Client — one per process
_client_user = None       # username the client is logged in as
_lock = asyncio.Lock()
_state = {"status": "logged_out", "error": "", "challenge": False, "username": ""}
# status: logged_out | ok | challenge | error


def creds(settings: dict) -> tuple[str, str]:
    return (str(settings.get("ig_private_username") or "").strip(),
            str(settings.get("ig_private_password") or "").strip())


def configured(settings: dict) -> bool:
    u, p = creds(settings)
    return bool(u and p)


def state() -> dict:
    return dict(_state)


# ── Login / client management (sync internals, called via to_thread) ──────────

def _login_sync(username: str, password: str, verification_code: str = ""):
    """Create/return a logged-in instagrapi Client. Raises on failure."""
    global _client, _client_user
    from instagrapi import Client

    if _client is not None and _client_user == username:
        return _client

    cl = Client()
    cl.delay_range = [1, 3]  # human-ish delay between private API calls
    if os.path.exists(SESSION_FILE):
        try:
            cl.load_settings(SESSION_FILE)
        except Exception as exc:
            log.warning("IG private: stale session file ignored: %s", exc)
    cl.login(username, password, verification_code=verification_code or "")
    try:
        cl.dump_settings(SESSION_FILE)
    except Exception as exc:
        log.warning("IG private: could not persist session: %s", exc)
    _client, _client_user = cl, username
    return cl


async def get_client(settings: dict, verification_code: str = ""):
    """Async wrapper with state tracking. Returns client or None."""
    username, password = creds(settings)
    if not username or not password:
        _state.update(status="logged_out", error="No username/password", username="")
        return None
    async with _lock:
        try:
            cl = await asyncio.to_thread(_login_sync, username, password, verification_code)
            _state.update(status="ok", error="", challenge=False, username=username)
            return cl
        except Exception as exc:
            name = type(exc).__name__
            challenge = "Challenge" in name or "challenge" in str(exc).lower() or "TwoFactor" in name
            _state.update(status="challenge" if challenge else "error", error=f"{name}: {exc}"[:300],
                          challenge=challenge, username=username)
            log.error("IG private login failed (%s): %s", name, exc)
            return None


def reset_session() -> None:
    """Forget the cached client + saved session (forces a fresh login)."""
    global _client, _client_user
    _client, _client_user = None, None
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
    except Exception:
        pass
    _state.update(status="logged_out", error="", challenge=False)


# ── Posting ───────────────────────────────────────────────────────────────────

async def _download(url: str) -> Optional[str]:
    """Download an image to a temp .jpg; returns the local path or None."""
    if url.startswith("file://"):
        local = url[7:]
        return local if os.path.exists(local) else None
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.1688.com/"})
        if r.status_code != 200 or not r.content:
            return None
        # instagrapi needs a real JPEG on disk
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(r.content))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        fd, path = tempfile.mkstemp(suffix=".jpg", prefix="igpost_")
        os.close(fd)
        img.save(path, format="JPEG", quality=92)
        img.close()
        return path
    except Exception as exc:
        log.warning("IG private: image download failed %s: %s", url[:80], exc)
        return None


async def post_photos(image_urls: list, caption: str, settings: dict) -> dict:
    """
    Post one photo or an album. Returns {"ok", "url", "error"}.
    Absolute http(s) URLs only — the caller filters like the Graph path does.
    """
    cl = await get_client(settings)
    if cl is None:
        return {"ok": False, "error": _state.get("error") or "Not logged in", "url": ""}
    paths = []
    for u in image_urls[:10]:
        p = await _download(u)
        if p:
            paths.append(p)
    if not paths:
        return {"ok": False, "error": "No image could be downloaded", "url": ""}
    try:
        def _upload():
            if len(paths) >= 2:
                media = cl.album_upload([str(p) for p in paths], caption)
            else:
                media = cl.photo_upload(str(paths[0]), caption)
            code = getattr(media, "code", None)
            return f"https://www.instagram.com/p/{code}/" if code else ""
        url = await asyncio.to_thread(_upload)
        return {"ok": True, "url": url, "error": ""}
    except Exception as exc:
        log.error("IG private: upload failed: %s", exc)
        _note_exception(exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300], "url": ""}
    finally:
        for p in paths:
            if os.path.basename(str(p)).startswith("igpost_"):
                try: os.remove(p)
                except Exception: pass


def _note_exception(exc: Exception) -> None:
    name = type(exc).__name__
    if "Challenge" in name or "LoginRequired" in name:
        _state.update(status="challenge" if "Challenge" in name else "error",
                      challenge="Challenge" in name, error=f"{name}: {exc}"[:300])


# ── Reading communications (the polling side) ────────────────────────────────

async def fetch_incoming(settings: dict, media_amount: int = 6, dm_amount: int = 10) -> dict:
    """
    Pull recent comments on our own posts + recent DMs.
    Returns {"comments": [...], "dms": [...], "error": str|None} with normalized dicts:
      comment: {external_id, media_id, sender_id, sender_name, text, media_url}
      dm:      {external_id, thread_id, sender_id, sender_name, text}
    """
    cl = await get_client(settings)
    if cl is None:
        return {"comments": [], "dms": [], "error": _state.get("error") or "Not logged in"}

    def _pull():
        me = str(cl.user_id)
        comments, dms = [], []
        try:
            medias = cl.user_medias(cl.user_id, amount=media_amount)
        except Exception as exc:
            raise RuntimeError(f"user_medias: {exc}") from exc
        for m in medias:
            try:
                for c in cl.media_comments(m.id, amount=20):
                    uid = str(getattr(c.user, "pk", "") or "")
                    if uid == me:
                        continue
                    comments.append({
                        "external_id": f"pc:{c.pk}",
                        "media_id": str(m.id),
                        "sender_id": uid,
                        "sender_name": str(getattr(c.user, "username", "") or ""),
                        "text": str(c.text or ""),
                        "media_url": f"https://www.instagram.com/p/{m.code}/" if getattr(m, "code", None) else "",
                    })
            except Exception as exc:
                log.debug("IG private: comments for media %s failed: %s", m.id, exc)
        try:
            threads = cl.direct_threads(amount=dm_amount)
        except Exception as exc:
            threads = []
            log.debug("IG private: direct_threads failed: %s", exc)
        for t in threads:
            users = {str(getattr(u, "pk", "")): str(getattr(u, "username", "") or "") for u in (t.users or [])}
            for msg in (t.messages or [])[:10]:
                sender = str(getattr(msg, "user_id", "") or "")
                text = str(getattr(msg, "text", "") or "")
                if not text or sender == me:
                    continue
                dms.append({
                    "external_id": f"pm:{getattr(msg, 'id', '')}",
                    "thread_id": str(t.id),
                    "sender_id": sender,
                    "sender_name": users.get(sender, ""),
                    "text": text,
                })
        return {"comments": comments, "dms": dms, "error": None}

    try:
        return await asyncio.to_thread(_pull)
    except Exception as exc:
        _note_exception(exc)
        log.warning("IG private: fetch_incoming failed: %s", exc)
        return {"comments": [], "dms": [], "error": str(exc)[:300]}


# ── Replying ──────────────────────────────────────────────────────────────────

async def reply_comment(media_id: str, text: str, settings: dict, replied_to_comment_id: Optional[str] = None) -> bool:
    cl = await get_client(settings)
    if cl is None:
        return False
    try:
        rid = int(replied_to_comment_id) if replied_to_comment_id else None
        await asyncio.to_thread(cl.media_comment, media_id, text, rid)
        return True
    except Exception as exc:
        _note_exception(exc)
        log.warning("IG private: comment reply failed: %s", exc)
        return False


async def reply_dm(thread_id: str, text: str, settings: dict) -> bool:
    cl = await get_client(settings)
    if cl is None:
        return False
    try:
        await asyncio.to_thread(cl.direct_answer, int(thread_id), text)
        return True
    except Exception as exc:
        _note_exception(exc)
        log.warning("IG private: DM reply failed: %s", exc)
        return False


# ── Polling loop body: capture → lead flag → auto-reply ──────────────────────

async def process_incoming(db, settings: dict) -> dict:
    """
    One polling pass. New messages land in the Inbox exactly like webhook
    traffic; auto-reply rules run when enabled. Dedup: inbox_add returns None
    for anything already seen.
    """
    from instagram_replies import match_rule, is_lead
    import activity

    stats = {"comments_seen": 0, "comments_replied": 0, "dms_seen": 0, "dms_replied": 0, "new": 0}
    data = await fetch_incoming(settings)
    if data.get("error"):
        stats["error"] = data["error"]
        return stats

    comments_on = bool(settings.get("instagram_auto_reply_enabled"))
    dms_on = bool(settings.get("instagram_dm_reply_enabled"))
    comment_rules = settings.get("instagram_reply_rules") or []
    dm_rules = settings.get("instagram_dm_rules") or []

    for c in data["comments"]:
        stats["comments_seen"] += 1
        rule = match_rule(c["text"], comment_rules) if comments_on else None
        new_id = await db.inbox_add(c["external_id"], "comment", c["sender_id"], c["sender_name"],
                                    c["text"], c["media_id"], is_lead=is_lead(c["text"], settings),
                                    auto_reply=rule["reply"] if rule else "")
        if new_id is None:
            continue  # already seen in a previous poll
        stats["new"] += 1
        if is_lead(c["text"], settings):
            await activity.record("lead_received", f"Possible order from {c['sender_name'] or 'someone'}: “{c['text'][:80]}”",
                                  meta={"inbox_id": new_id, "kind": "comment"}, level="warn")
        if rule and not await db.has_replied_to_comment(c["external_id"]):
            if await reply_comment(c["media_id"], rule["reply"], settings, c["external_id"].removeprefix("pc:")):
                stats["comments_replied"] += 1
                await db.log_comment_reply(c["external_id"], ",".join(rule["keywords"]) or "*", "comment")
                await activity.record("reply_sent", f"Replied to {c['sender_name'] or 'a comment'}: “{rule['reply'][:60]}”")

    for m in data["dms"]:
        stats["dms_seen"] += 1
        rule = match_rule(m["text"], dm_rules) if dms_on else None
        new_id = await db.inbox_add(m["external_id"], "dm", m["sender_id"], m["sender_name"],
                                    m["text"], m["thread_id"], is_lead=is_lead(m["text"], settings),
                                    auto_reply=rule["reply"] if rule else "")
        if new_id is None:
            continue
        stats["new"] += 1
        if is_lead(m["text"], settings):
            await activity.record("lead_received", f"Possible order from {m['sender_name'] or m['sender_id']}: “{m['text'][:80]}”",
                                  meta={"inbox_id": new_id, "kind": "dm"}, level="warn")
        if rule and not await db.has_replied_to_comment(m["external_id"]):
            if await reply_dm(m["thread_id"], rule["reply"], settings):
                stats["dms_replied"] += 1
                await db.log_comment_reply(m["external_id"], ",".join(rule["keywords"]) or "*", "dm")
                await activity.record("reply_sent", f"Replied to a DM from {m['sender_name'] or m['sender_id']}: “{rule['reply'][:60]}”")

    if stats["new"]:
        log.info("IG private poll: %s", stats)
    return stats


async def poll_loop(db, get_settings):
    """
    Background task: read Instagram communications every ig_poll_minutes
    (default 5) when the direct-login backend is configured and Autopilot runs.
    """
    import autopilot
    log.info("Started Instagram polling loop (direct login).")
    last_error_note = 0.0
    while True:
        try:
            settings = await get_settings()
            minutes = max(2, float(settings.get("ig_poll_minutes") or 5))
            if not (configured(settings) and str(settings.get("instagram_backend") or "auto") in ("auto", "private")
                    and autopilot.enabled(settings)):
                await asyncio.sleep(60)
                continue
            stats = await process_incoming(db, settings)
            if stats.get("error") and time.time() - last_error_note > 3600:
                last_error_note = time.time()
                import activity
                await activity.record("config", f"Instagram polling problem: {stats['error'][:140]}"
                                      + (" — approve the login in the Instagram app, then use “Log in now” in Settings." if _state.get("challenge") else ""),
                                      level="warn")
            await asyncio.sleep(minutes * 60)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("IG polling loop error: %s", exc, exc_info=True)
            await asyncio.sleep(120)
