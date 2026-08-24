"""
Instagram "Direct login" backend — no Meta developer account needed.

Uses the community instagrapi library (Instagram's private mobile API) with your
plain Instagram username + password. Running from a home PC (residential IP) is
the good case for this approach. It covers everything DropOS needs:

  • posting photos / albums with captions        → post_photos()
  • reading comments on your own recent posts     → poll_loop() → Inbox + auto-reply
  • reading and answering DMs                      → poll_loop() / reply_*()

Configured for safety (Settings → Connections → Instagram → Advanced):
  - Consistent device profile — country / phone code / timezone / locale are
    fixed (Georgia by default) so the session always looks like the same phone
    in the same place; optional residential proxy.
  - Session-first login — the saved session is reused and only validated with a
    lightweight timeline fetch; a full password login runs solely when the
    session died, and the device UUIDs are preserved so Instagram sees the same
    "phone" logging back in (not a brand-new device every time).
  - Human pacing — randomized delay between API calls, quiet hours at night, and
    typed handling of Instagram's pushback: challenge / 2FA surface as "needs
    you"; "please wait a few minutes" and rate limits trigger an automatic
    backoff; an action block (FeedbackRequired) pauses posting for a day.

The session (cookies + device) is persisted in DATA_DIR/ig_session.json so a
successful login survives restarts and re-login is rare.
"""

import asyncio
import logging
import os
import random
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from config.paths import data_path

log = logging.getLogger(__name__)

SESSION_FILE = data_path("ig_session.json", is_file=True)

_client = None            # instagrapi.Client — one per process
_client_user = None       # username the client is logged in as
_client_sig = None        # device signature the client was built with
_lock = asyncio.Lock()

_state = {
    "status": "logged_out",   # logged_out | ok | challenge | error
    "error": "",
    "challenge": False,       # needs a human: challenge / 2FA / bad password
    "username": "",
    "last_login_at": None,
    "last_poll_at": None,
    "last_poll_new": 0,
    "backoff_until": None,    # ISO — all private calls paused until then (rate limit)
    "post_block_until": None, # ISO — posting paused (action block) until then
}

# Default device: a phone in Georgia. Kept stable across logins.
_DEFAULT_DEVICE = {
    "country": "GE", "country_code": 995, "locale": "ka_GE",
    "timezone_offset": 4 * 3600,  # Asia/Tbilisi = UTC+4
}


# ── helpers ───────────────────────────────────────────────────────────────────

def creds(settings: dict) -> tuple[str, str]:
    return (str(settings.get("ig_private_username") or "").strip(),
            str(settings.get("ig_private_password") or "").strip())


def session_id(settings: dict) -> str:
    """The `sessionid` cookie copied from a browser already logged into Instagram.

    Instagram sometimes answers a password login with a native checkpoint that
    has no code to enter ("complete it in the official app") — unsolvable from
    here. Handing over an already-authenticated session sidesteps the login
    entirely, so this is the reliable way in once a checkpoint appears.
    """
    raw = str(settings.get("ig_session_id") or "").strip()
    # Accept a pasted cookie string ("sessionid=abc%3A...; ds_user_id=...") too
    if "sessionid=" in raw:
        raw = raw.split("sessionid=", 1)[1].split(";", 1)[0].strip()
    return raw.strip('"').strip()


def configured(settings: dict) -> bool:
    u, p = creds(settings)
    return bool(session_id(settings) or (u and p))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _parse_iso(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def state() -> dict:
    return {**_state, "session_saved": os.path.exists(SESSION_FILE)}


def _backoff_active() -> bool:
    until = _parse_iso(_state.get("backoff_until"))
    return bool(until and _now() < until)


def posting_blocked() -> bool:
    until = _parse_iso(_state.get("post_block_until"))
    return bool(until and _now() < until)


def _set_backoff(minutes: float, reason: str) -> None:
    _state["backoff_until"] = _iso(_now() + timedelta(minutes=minutes))
    _state["error"] = reason[:300]
    log.warning("IG private: backing off %.0f min — %s", minutes, reason)


def _device_settings(settings: dict) -> dict:
    def _num(key, default):
        v = settings.get(key)
        return default if v in (None, "") else v
    return {
        "country": str(settings.get("ig_country") or _DEFAULT_DEVICE["country"]).strip() or "GE",
        "country_code": int(_num("ig_country_code", _DEFAULT_DEVICE["country_code"])),
        "locale": str(settings.get("ig_locale") or _DEFAULT_DEVICE["locale"]).strip() or "ka_GE",
        "timezone_offset": int(_num("ig_timezone_offset", _DEFAULT_DEVICE["timezone_offset"])),
        "proxy": str(settings.get("ig_proxy") or "").strip(),
        "delay_min": float(_num("ig_delay_min", 1.5)),
        "delay_max": float(_num("ig_delay_max", 4.0)),
    }


# ── Login / client management (sync internals, called via to_thread) ──────────

def _apply_device(cl, dev: dict) -> None:
    """Pin locale / country / timezone / proxy so the session is consistent."""
    try:
        cl.set_locale(dev["locale"])
        cl.set_country(dev["country"])
        cl.set_country_code(dev["country_code"])
        cl.set_timezone_offset(dev["timezone_offset"])
    except Exception as exc:
        log.debug("IG private: device pin partial: %s", exc)
    if dev.get("proxy"):
        try:
            cl.set_proxy(dev["proxy"])
        except Exception as exc:
            log.warning("IG private: proxy rejected (%s) — continuing without it", exc)
    lo, hi = dev["delay_min"], dev["delay_max"]
    cl.delay_range = [max(0.5, lo), max(lo + 0.5, hi)]


def _login_sync(username: str, password: str, dev: dict, verification_code: str = "",
                sessionid: str = ""):
    """
    Return a logged-in instagrapi Client, reusing the saved session when valid.

    Session-first (the recommended instagrapi pattern):
      1. load session → try a cheap authenticated call (timeline feed).
      2. adopt the browser `sessionid` cookie when one is configured — this is
         the only way past Instagram's native checkpoint, which offers no code.
      3. otherwise log in with the password but KEEP the device UUIDs so
         Instagram sees the same device re-authenticating.
    """
    global _client, _client_user, _client_sig
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired

    cl = Client()
    _apply_device(cl, dev)

    loaded = False
    if os.path.exists(SESSION_FILE):
        try:
            cl.load_settings(SESSION_FILE)
            _apply_device(cl, dev)   # re-pin (load_settings can overwrite locale)
            loaded = True
        except Exception as exc:
            log.warning("IG private: stale session file ignored: %s", exc)

    if loaded and not verification_code:
        try:
            cl.login(username, password)   # cheap when the session cookie is valid
            cl.get_timeline_feed()          # validate the session actually works
            _client, _client_user, _client_sig = cl, username, dev
            return cl
        except LoginRequired:
            log.info("IG private: saved session expired — logging in fresh (same device)")
            old = cl.get_settings()
            cl = Client()
            _apply_device(cl, dev)
            cl.set_settings({})
            cl.set_uuids(old.get("uuids", {}))   # keep the device identity
        except Exception as exc:
            log.info("IG private: session validation failed (%s) — full login", exc)

    if sessionid and not verification_code:
        try:
            uuids = {}
            try:
                uuids = cl.get_settings().get("uuids", {}) or {}
            except Exception:
                pass
            sc = Client()
            _apply_device(sc, dev)
            if uuids:
                sc.set_uuids(uuids)   # keep this "phone" identity across methods
            sc.login_by_sessionid(sessionid)
            sc.get_timeline_feed()    # a checkpointed session fails here, not silently
            try:
                sc.dump_settings(SESSION_FILE)
            except Exception as exc:
                log.warning("IG private: could not persist session: %s", exc)
            log.info("IG private: authenticated with the browser sessionid cookie")
            _client, _client_user, _client_sig = sc, username, dev
            return sc
        except Exception as exc:
            log.warning("IG private: sessionid login failed (%s: %s)", type(exc).__name__, exc)
            if not (username and password):
                raise

    cl.login(username, password, verification_code=verification_code or "")
    cl.get_timeline_feed()
    try:
        cl.dump_settings(SESSION_FILE)
    except Exception as exc:
        log.warning("IG private: could not persist session: %s", exc)
    _client, _client_user, _client_sig = cl, username, dev
    return cl


def _client_username(cl) -> str:
    """Best-effort handle for the logged-in account (sessionid login has no username)."""
    try:
        return str(cl.username or "") or str(cl.account_info().username or "")
    except Exception:
        return ""


def _classify(exc: Exception) -> str:
    """Map an instagrapi exception to a state category."""
    name = type(exc).__name__
    if name in ("ChallengeRequired", "TwoFactorRequired", "BadPassword",
                "RecaptchaChallengeForm", "SelectContactPointRecoveryForm"):
        return "challenge"
    if name == "FeedbackRequired":
        return "action_block"
    if name in ("PleaseWaitFewMinutes", "RateLimitError", "ProxyAddressIsBlocked"):
        return "rate_limit"
    if name == "LoginRequired":
        return "login_required"
    return "error"


async def get_client(settings: dict, verification_code: str = "", force: bool = False):
    """Async wrapper with state tracking + backoff. Returns client or None."""
    username, password = creds(settings)
    sid = session_id(settings)
    if not sid and (not username or not password):
        _state.update(status="logged_out", error="No username/password", username="", challenge=False)
        return None
    if _backoff_active() and not force and not verification_code:
        return None
    dev = _device_settings(settings)
    async with _lock:
        if _client is not None and _client_user == username and _client_sig == dev and not verification_code and not force:
            return _client
        try:
            cl = await asyncio.to_thread(_login_sync, username, password, dev, verification_code, sid)
            name = username or _client_username(cl)
            _state.update(status="ok", error="", challenge=False, username=name,
                          last_login_at=_iso(_now()), backoff_until=None)
            return cl
        except Exception as exc:
            kind = _classify(exc)
            msg = f"{type(exc).__name__}: {exc}"[:300]
            if kind == "challenge":
                _state.update(status="challenge", challenge=True, username=username, error=msg)
            elif kind == "rate_limit":
                _state.update(status="error", challenge=False, username=username)
                _set_backoff(random.uniform(30, 60), msg)
            elif kind == "action_block":
                _state.update(status="error", challenge=False, username=username)
                _set_backoff(180, "Action block — " + msg)
            else:
                _state.update(status="error", challenge=False, username=username, error=msg)
            log.error("IG private login failed (%s): %s", kind, exc)
            return None


def reset_session() -> None:
    """Forget the cached client + saved session (forces a fresh login)."""
    global _client, _client_user, _client_sig
    _client, _client_user, _client_sig = None, None, None
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
    except Exception:
        pass
    _state.update(status="logged_out", error="", challenge=False,
                  backoff_until=None, post_block_until=None)


def _note_exception(exc: Exception) -> None:
    """Update shared state from an error raised during an authenticated call."""
    global _client
    kind = _classify(exc)
    msg = f"{type(exc).__name__}: {exc}"[:300]
    if kind == "challenge":
        _state.update(status="challenge", challenge=True, error=msg)
    elif kind == "action_block":
        _state["post_block_until"] = _iso(_now() + timedelta(hours=24))
        _set_backoff(60, "Action block — posting paused 24h — " + msg)
    elif kind == "rate_limit":
        _set_backoff(random.uniform(30, 60), msg)
    elif kind == "login_required":
        _state.update(status="error", error="Session expired — will re-login")
        _client = None   # drop the cached client so the next call re-logs in
    else:
        _state["error"] = msg


# ── Posting ───────────────────────────────────────────────────────────────────

async def _download(url: str) -> Optional[str]:
    """Download an image to a temp .jpg (or return a local file:// path). None on failure."""
    if url.startswith("file://"):
        local = url[7:]
        return local if os.path.exists(local) else None
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.1688.com/"})
        if r.status_code != 200 or not r.content:
            return None
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
    """Post one photo or an album. Returns {"ok", "url", "error"}."""
    if posting_blocked():
        return {"ok": False, "error": f"Posting paused until {_state.get('post_block_until')} (Instagram action block)", "url": ""}
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
        _state["error"] = ""
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


# ── Reading communications (the polling side) ────────────────────────────────

async def fetch_incoming(settings: dict, media_amount: int = 6, dm_amount: int = 10) -> dict:
    """
    Pull recent comments on our own posts + recent DMs. Normalized dicts:
      comment: {external_id, media_id, sender_id, sender_name, text, media_url}
      dm:      {external_id, thread_id, sender_id, sender_name, text}
    """
    if _backoff_active():
        return {"comments": [], "dms": [], "error": f"backing off until {_state.get('backoff_until')}"}
    cl = await get_client(settings)
    if cl is None:
        return {"comments": [], "dms": [], "error": _state.get("error") or "Not logged in"}

    def _pull():
        me = str(cl.user_id)
        comments, dms = [], []
        medias = cl.user_medias(cl.user_id, amount=media_amount)
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
        result = await asyncio.to_thread(_pull)
        _state["error"] = ""
        return result
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


# ── Polling: capture → lead flag → auto-reply ─────────────────────────────────

async def process_incoming(db, settings: dict) -> dict:
    """One polling pass. New messages land in the Inbox exactly like webhook
    traffic; auto-reply rules run when enabled. Dedup: inbox_add returns None
    for anything already seen."""
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
            continue
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

    _state.update(last_poll_at=_iso(_now()), last_poll_new=stats["new"])
    if stats["new"]:
        log.info("IG private poll: %s", stats)
    return stats


def in_quiet_hours(settings: dict) -> bool:
    """True during the configured night window (local time), when we don't act."""
    try:
        start = 1 if settings.get("ig_quiet_start") in (None, "") else int(settings.get("ig_quiet_start"))
        end = 7 if settings.get("ig_quiet_end") in (None, "") else int(settings.get("ig_quiet_end"))
    except (TypeError, ValueError):
        start, end = 1, 7
    if start == end:
        return False
    tz = str(settings.get("post_timezone") or "Asia/Tbilisi")
    try:
        from zoneinfo import ZoneInfo
        hour = datetime.now(ZoneInfo(tz)).hour
    except Exception:
        hour = _now().hour
    return (start <= hour < end) if start < end else (hour >= start or hour < end)


async def poll_loop(db, get_settings):
    """
    Background task: read Instagram communications on a jittered interval
    (ig_poll_minutes ± 30%, default 5) when direct login is configured, Autopilot
    is on, and we're not in quiet hours or a backoff.
    """
    import autopilot
    log.info("Started Instagram polling loop (direct login).")
    last_error_note = 0.0
    while True:
        try:
            settings = await get_settings()
            base = max(2.0, float(settings.get("ig_poll_minutes") or 5))
            active = (configured(settings)
                      and str(settings.get("instagram_backend") or "auto") in ("auto", "private")
                      and autopilot.enabled(settings)
                      and not in_quiet_hours(settings)
                      and not _backoff_active())
            if not active:
                await asyncio.sleep(60)
                continue
            stats = await process_incoming(db, settings)
            if stats.get("error") and time.time() - last_error_note > 3600:
                last_error_note = time.time()
                import activity
                await activity.record("config", f"Instagram polling problem: {stats['error'][:140]}"
                                      + (" — approve the login in the Instagram app, then use “Log in now” in Settings." if _state.get("challenge") else ""),
                                      level="warn")
            jitter = base * random.uniform(0.7, 1.3)
            await asyncio.sleep(jitter * 60)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("IG polling loop error: %s", exc, exc_info=True)
            await asyncio.sleep(120)
