"""
One-click Instagram connect (official "Instagram API with Instagram Login").

What the merchant does: press Connect, log in on Instagram's own page, press
Allow. No password ever reaches DropOS, no token is pasted, no Facebook Page is
needed. The account only has to be a professional one (Business or Creator).

What happens here:
  1. authorize_url()   -> where the Connect button sends the browser
  2. exchange_code()   -> code -> 1-hour token -> 60-day token
  3. get_profile()     -> username and account id
  4. refresh_loop()    -> renews the token about once a month, by itself
  5. subscribe_webhooks() -> comment and message notifications for the inbox

Tokens from this flow are used against graph.instagram.com (see instagram._graph).

Docs: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx

from config.runtime import get_config

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"

SCOPES = [
    "instagram_business_basic",
    "instagram_business_content_publish",
    "instagram_business_manage_comments",
    "instagram_business_manage_messages",
]
WEBHOOK_FIELDS = ["comments", "messages"]
CALLBACK_PATH = "/api/instagram/oauth/callback"

_DAY = 86400
_RENEW_WHEN_LEFT = 30 * _DAY      # tokens live 60 days: renew roughly monthly
_CHECK_EVERY = 6 * 3600

_transport = None  # tests swap in an httpx.MockTransport


class InstagramOAuthError(Exception):
    """kind: 'auth' (code or token no longer valid) | 'api' | 'network' | 'setup'"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


# ── configuration ─────────────────────────────────────────────────────────────

def app_credentials(settings: dict) -> tuple:
    s = settings or {}
    app_id = str(get_config("INSTAGRAM_APP_ID", s.get("instagram_app_id") or "") or "").strip()
    secret = str(s.get("instagram_app_secret") or "").strip()
    return app_id, secret


def configured(settings: dict) -> bool:
    """True once the DropOS owner has entered the Instagram app ID and secret (one time)."""
    return all(app_credentials(settings))


def _version(settings: dict) -> str:
    version = str(get_config("META_GRAPH_VERSION", (settings or {}).get("meta_graph_version", "v23.0")) or "v23.0").strip()
    return version if version.startswith("v") else f"v{version}"


def redirect_uri(base_url: str) -> str:
    return f"{str(base_url).rstrip('/')}{CALLBACK_PATH}"


def authorize_url(settings: dict, state: str, redirect: str) -> str:
    app_id, _ = app_credentials(settings)
    return f"{AUTHORIZE_URL}?" + urlencode({
        "client_id": app_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": ",".join(SCOPES),
        "state": state,
    })


# ── calls to Instagram ────────────────────────────────────────────────────────

async def _call(method: str, url: str, **kwargs) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15, transport=_transport) as client:
            resp = await client.request(method, url, **kwargs)
    except httpx.HTTPError:
        raise InstagramOAuthError("network", "Instagram could not be reached")
    try:
        data = resp.json()
    except ValueError:
        data = None
    # Two error shapes: {error:{message,code}} from the Graph API and
    # {error_type,code,error_message} from the token endpoint.
    if resp.status_code >= 400 or (isinstance(data, dict) and (data.get("error") or data.get("error_type"))):
        err = (data or {}).get("error") if isinstance(data, dict) else None
        err = err if isinstance(err, dict) else {}
        message = err.get("message") or (data or {}).get("error_message") or f"Instagram returned {resp.status_code}"
        auth = err.get("code") == 190 or (data or {}).get("error_type") == "OAuthException" or resp.status_code == 401
        raise InstagramOAuthError("auth" if auth else "api", str(message))
    if not isinstance(data, dict):
        raise InstagramOAuthError("api", "Instagram sent an unreadable reply")
    return data


async def exchange_code(settings: dict, code: str, redirect: str) -> dict:
    """Code from the callback -> {'access_token', 'expires_in', 'scopes'} (a 60-day token)."""
    app_id, secret = app_credentials(settings)
    if not (app_id and secret):
        raise InstagramOAuthError("setup", "The Instagram app ID and secret are not set")
    short = await _call("POST", TOKEN_URL, data={
        "client_id": app_id,
        "client_secret": secret,
        "grant_type": "authorization_code",
        "redirect_uri": redirect,
        "code": str(code).removesuffix("#_"),       # Instagram appends "#_" to the code
    })
    rows = short.get("data")
    first = rows[0] if isinstance(rows, list) and rows else short
    if not first.get("access_token"):
        raise InstagramOAuthError("api", "Instagram did not return a token")
    long_lived = await _call("GET", f"{GRAPH}/access_token", params={
        "grant_type": "ig_exchange_token",
        "client_secret": secret,
        "access_token": first["access_token"],
    })
    granted = first.get("permissions") or ""
    return {
        "access_token": long_lived["access_token"],
        "expires_in": int(long_lived.get("expires_in") or 60 * _DAY),
        "scopes": granted if isinstance(granted, list) else [s for s in str(granted).split(",") if s],
    }


async def get_profile(access_token: str, settings: dict) -> dict:
    me = await _call("GET", f"{GRAPH}/{_version(settings)}/me", params={
        "fields": "id,user_id,username,name,account_type,followers_count",
        "access_token": access_token,
    })
    return {
        "user_id": str(me.get("user_id") or me.get("id") or ""),
        "scoped_id": str(me.get("id") or ""),
        "username": me.get("username") or "",
        "account_type": me.get("account_type") or "",
        "followers": me.get("followers_count"),
    }


async def refresh(access_token: str) -> dict:
    """Long-lived tokens can be renewed once they are a day old and not yet expired."""
    data = await _call("GET", f"{GRAPH}/refresh_access_token", params={
        "grant_type": "ig_refresh_token",
        "access_token": access_token,
    })
    return {"access_token": data["access_token"], "expires_in": int(data.get("expires_in") or 60 * _DAY)}


async def subscribe_webhooks(access_token: str, settings: dict) -> None:
    """Turns on comment and message notifications for the connected account."""
    await _call("POST", f"{GRAPH}/{_version(settings)}/me/subscribed_apps", params={
        "subscribed_fields": ",".join(WEBHOOK_FIELDS),
        "access_token": access_token,
    })


# ── what gets stored ──────────────────────────────────────────────────────────

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def connection_settings(grant: dict, profile: dict) -> dict:
    """Settings written when a merchant connects."""
    now = datetime.now(timezone.utc)
    return {
        "instagram_access_token": grant["access_token"],
        "instagram_user_id": profile["user_id"],
        "instagram_scoped_id": profile.get("scoped_id") or "",
        "instagram_username": profile.get("username") or "",
        "instagram_api_host": "instagram",          # read by instagram._graph
        "instagram_connected_via": "oauth",
        "instagram_backend": "graph",               # the official API becomes the posting method
        "instagram_token_expires_at": _iso(now + timedelta(seconds=grant["expires_in"])),
        "instagram_token_refreshed_at": _iso(now),
        "instagram_scopes": grant.get("scopes") or [],
        "instagram_needs_reconnect": False,
    }


DISCONNECTED = {
    "instagram_access_token": "",
    "instagram_user_id": "",
    "instagram_scoped_id": "",
    "instagram_api_host": "",
    "instagram_connected_via": "",
    "instagram_token_expires_at": "",
    "instagram_token_refreshed_at": "",
    "instagram_scopes": [],
}


def status(settings: dict, base_url: str = "") -> dict:
    """What the Settings page needs to draw the Connect button honestly."""
    s = settings or {}
    connected = s.get("instagram_connected_via") == "oauth" and bool(s.get("instagram_access_token")) \
        and bool(s.get("instagram_user_id"))
    scopes = s.get("instagram_scopes") or []
    return {
        "ready": configured(s),
        "connected": connected,
        "username": s.get("instagram_username") or "" if connected else "",
        "expires_at": s.get("instagram_token_expires_at") or None if connected else None,
        "needs_reconnect": bool(s.get("instagram_needs_reconnect")) and not connected,
        "missing_permissions": [p for p in SCOPES if connected and scopes and p not in scopes],
        "redirect_uri": redirect_uri(base_url) if base_url else "",
        "https": str(base_url).startswith("https://"),
    }


# ── automatic renewal ─────────────────────────────────────────────────────────

async def refresh_if_due(db, settings: dict) -> str:
    """Renews the stored token when it is getting old. Returns what happened:
    'not_connected' | 'fresh' | 'renewed' | 'expired' | 'revoked' | 'failed'."""
    if (settings or {}).get("instagram_connected_via") != "oauth" or not settings.get("instagram_access_token"):
        return "not_connected"
    now = datetime.now(timezone.utc)
    expires = _parse_iso(settings.get("instagram_token_expires_at"))
    refreshed = _parse_iso(settings.get("instagram_token_refreshed_at"))
    if expires and expires <= now:
        await db.update_settings({**DISCONNECTED, "instagram_needs_reconnect": True})
        return "expired"
    due = not expires or (expires - now).total_seconds() < _RENEW_WHEN_LEFT
    old_enough = not refreshed or (now - refreshed).total_seconds() > _DAY
    if not (due and old_enough):
        return "fresh"
    try:
        grant = await refresh(str(settings["instagram_access_token"]))
    except InstagramOAuthError as exc:
        if exc.kind == "auth":
            # The merchant removed DropOS in Instagram, or the token was revoked.
            await db.update_settings({**DISCONNECTED, "instagram_needs_reconnect": True})
            return "revoked"
        log.warning("Instagram token renewal failed (%s) — will try again", exc)
        return "failed"
    await db.update_settings({
        "instagram_access_token": grant["access_token"],
        "instagram_token_expires_at": _iso(now + timedelta(seconds=grant["expires_in"])),
        "instagram_token_refreshed_at": _iso(now),
    })
    return "renewed"


async def refresh_loop(db, settings_loader) -> None:
    """Background task: keeps the connection alive without the merchant doing anything."""
    while True:
        try:
            outcome = await refresh_if_due(db, await settings_loader())
            if outcome in ("renewed", "expired", "revoked"):
                log.info("Instagram connection: %s", outcome)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Instagram token check failed: %s", exc)
        await asyncio.sleep(_CHECK_EVERY)


# ── calls Meta makes to us ────────────────────────────────────────────────────

def parse_signed_request(value: str, secret: str) -> Optional[dict]:
    """Meta signs its 'access removed' and 'delete data' calls with the app
    secret: '<signature>.<payload>', both base64url. Returns the payload, or None."""
    signature, _, payload = str(value or "").partition(".")
    if not (signature and payload and secret):
        return None
    expected = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    if not hmac.compare_digest(expected, signature.rstrip("=")):
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except ValueError:
        return None
