"""
Instagram "Browser" backend — Playwright driving the real instagram.com UI.

Why this exists
---------------
The private-API backend (instagram_private.py) logs in like the phone app. When
Instagram flags an account for automation it answers that login with a native
checkpoint that has no code to enter, and the account is stuck — while the same
account's *web* session keeps working normally in a browser.

This backend lives on the working side of that split. It never performs a login:
the browser profile is seeded with the `sessionid` cookie from a browser where
the user is already signed in, so there is no login event for Instagram to
challenge. From there it clicks through the same "Create post" flow a human uses.

Trade-offs, honestly
--------------------
  • Selectors follow Instagram's web UI and will break when they redesign it.
    Every step therefore tries several strategies and logs which one worked.
  • The UI is localized. Set the Instagram account language to English, or the
    text-based fallbacks will miss (the aria-label and structural fallbacks
    still work in any language).
  • Keep volumes human. This is the same account-safety story as the private
    backend: a couple of posts a day, never a burst.

State lives in DATA_DIR/ig_browser_profile — a normal Chromium profile, so a
working session survives restarts exactly like a browser you left logged in.
"""

import asyncio
import logging
import os
import random
import tempfile
from datetime import datetime, timezone
from typing import Optional

import httpx

from config.paths import data_path

log = logging.getLogger(__name__)

PROFILE_DIR = data_path("ig_browser_profile")

_pw = None            # playwright driver
_ctx = None           # persistent browser context
_lock = asyncio.Lock()

_state = {
    "status": "logged_out",   # logged_out | ok | needs_login | error
    "error": "",
    "username": "",
    "last_post_at": None,
    "last_check_at": None,
}

_MAX_IMAGES = 10


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def state() -> dict:
    return {**_state, "profile_saved": os.path.isdir(PROFILE_DIR) and bool(os.listdir(PROFILE_DIR))}


def enabled(settings: dict) -> bool:
    return bool(settings.get("ig_browser_enabled"))


def configured(settings: dict) -> bool:
    """Usable when switched on and we have either a seeded profile or a cookie."""
    if not enabled(settings):
        return False
    has_profile = os.path.isdir(PROFILE_DIR) and bool(os.listdir(PROFILE_DIR))
    import instagram_private
    return bool(has_profile or instagram_private.session_id(settings))


def _headless(settings: dict) -> bool:
    """Headed on a desktop by default: Instagram trusts a real window more, and
    the user can watch the first post go out. PLAYWRIGHT_HEADLESS=1 overrides."""
    if str(os.getenv("PLAYWRIGHT_HEADLESS", "")).lower() in {"1", "true", "yes"}:
        return True
    if str(os.getenv("PLAYWRIGHT_HEADED", "")).lower() in {"1", "true", "yes"}:
        return False
    if os.path.exists("/.dockerenv") or os.getenv("RAILWAY_ENVIRONMENT_NAME"):
        return True
    return not bool(settings.get("ig_browser_headed", True))


async def _human_pause(lo: float = 0.6, hi: float = 1.8) -> None:
    await asyncio.sleep(random.uniform(lo, hi))


# ── Browser lifecycle ─────────────────────────────────────────────────────────

async def _ensure_context(settings: dict):
    """Return a logged-in persistent context, seeding the sessionid cookie when
    the profile has none yet. None when the browser could not be started."""
    global _pw, _ctx
    if _ctx is not None:
        return _ctx
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        _state.update(status="error", error="Playwright is not installed (pip install playwright)")
        return None

    os.makedirs(PROFILE_DIR, exist_ok=True)
    try:
        _pw = await async_playwright().start()
        _ctx = await _pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=_headless(settings),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id=str(settings.get("post_timezone") or "Asia/Tbilisi"),
            args=["--disable-blink-features=AutomationControlled"],
        )
    except Exception as exc:
        _state.update(status="error", error=f"Could not start the browser: {exc}"[:300])
        log.error("IG browser: launch failed: %s", exc)
        _pw, _ctx = None, None
        return None

    # Seed the session cookie so the profile starts authenticated (no login event)
    import instagram_private
    sid = instagram_private.session_id(settings)
    if sid:
        try:
            await _ctx.add_cookies([{
                "name": "sessionid", "value": sid,
                "domain": ".instagram.com", "path": "/",
                "httpOnly": True, "secure": True, "sameSite": "Lax",
            }])
            log.info("IG browser: seeded the profile with the saved sessionid cookie")
        except Exception as exc:
            log.warning("IG browser: could not seed the sessionid cookie: %s", exc)
    return _ctx


async def close() -> None:
    """Shut the browser down (used on reset and at shutdown)."""
    global _pw, _ctx
    try:
        if _ctx is not None:
            await _ctx.close()
    except Exception:
        pass
    try:
        if _pw is not None:
            await _pw.stop()
    except Exception:
        pass
    _pw, _ctx = None, None


async def reset_profile() -> None:
    """Forget the browser session entirely (forces a fresh cookie seed/login)."""
    import shutil
    await close()
    try:
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
    except Exception as exc:
        log.warning("IG browser: could not remove the profile: %s", exc)
    _state.update(status="logged_out", error="", username="")


# ── Session check ─────────────────────────────────────────────────────────────

async def _current_username(page) -> str:
    """Read the signed-in handle from the app's own bootstrap data."""
    for script in (
        "() => window._sharedData?.config?.viewer?.username || ''",
        "() => document.cookie.match(/ds_user_id=(\\d+)/) ? 'id:' + RegExp.$1 : ''",
    ):
        try:
            val = await page.evaluate(script)
            if val:
                return str(val)
        except Exception:
            continue
    # Fall back to the profile link in the nav bar
    try:
        href = await page.get_attribute('a[href^="/"][role="link"]:has(img[alt*="profile picture"])', "href")
        if href:
            return href.strip("/").split("/")[0]
    except Exception:
        pass
    return ""


async def check_session(settings: dict) -> dict:
    """Open Instagram and report whether the browser profile is signed in."""
    async with _lock:
        ctx = await _ensure_context(settings)
        if ctx is None:
            return {"ok": False, "error": _state.get("error") or "No browser", "username": ""}
        page = await ctx.new_page()
        try:
            await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=45000)
            await _human_pause(1.5, 2.5)
            url = page.url
            if "/accounts/login" in url or "/challenge" in url:
                reason = ("Instagram is showing a checkpoint in the browser — open it and complete the prompt"
                          if "/challenge" in url else
                          "The browser profile is not signed in — paste a fresh sessionid, or sign in in the window")
                _state.update(status="needs_login", error=reason, username="", last_check_at=_now_iso())
                return {"ok": False, "error": reason, "username": ""}
            name = await _current_username(page)
            _state.update(status="ok", error="", username=name, last_check_at=_now_iso())
            return {"ok": True, "error": "", "username": name}
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"[:300]
            _state.update(status="error", error=msg, last_check_at=_now_iso())
            return {"ok": False, "error": msg, "username": ""}
        finally:
            try:
                await page.close()
            except Exception:
                pass


# ── Images ────────────────────────────────────────────────────────────────────

async def _download(url: str) -> Optional[str]:
    """Local JPEG path for a URL (or a file:// path). None on failure."""
    url = (url or "").strip()
    if url.startswith("file://"):
        local = url[7:]
        return local if os.path.exists(local) else None
    if not url.startswith(("http://", "https://")):
        return None
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0",
                                               "Referer": "https://www.1688.com/"})
        if r.status_code != 200 or not r.content:
            return None
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(r.content))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        fd, path = tempfile.mkstemp(suffix=".jpg", prefix="igweb_")
        os.close(fd)
        img.save(path, format="JPEG", quality=92)
        img.close()
        return path
    except Exception as exc:
        log.warning("IG browser: image download failed %s: %s", url[:80], exc)
        return None


# ── The posting flow ──────────────────────────────────────────────────────────

async def _click_any(page, strategies: list, what: str, timeout: int = 12000) -> bool:
    """Try each locator strategy in turn; log which one worked.

    Strategies are (description, locator-factory) pairs so a UI redesign shows up
    in the log as "all strategies failed for X" instead of a bare timeout.
    """
    for desc, factory in strategies:
        try:
            loc = factory()
            await loc.wait_for(state="visible", timeout=timeout)
            await loc.click()
            log.info("IG browser: %s ← %s", what, desc)
            return True
        except Exception:
            continue
    log.warning("IG browser: could not find %s (Instagram may have changed the UI)", what)
    return False


async def _open_composer(page) -> bool:
    return await _click_any(page, [
        ('aria-label "New post"', lambda: page.locator('[aria-label="New post"]').first),
        ('svg aria-label "New post"', lambda: page.locator('svg[aria-label="New post"]').first),
        ('nav "Create"', lambda: page.get_by_role("link", name="Create").first),
        ('button "Create"', lambda: page.get_by_role("button", name="Create").first),
    ], "the Create button")


async def _next_step(page, step: str) -> bool:
    return await _click_any(page, [
        ('role=button "Next"', lambda: page.get_by_role("button", name="Next").first),
        ('text "Next"', lambda: page.locator('div[role="button"]:has-text("Next")').last),
    ], f"Next ({step})")


async def _fill_caption(page, caption: str) -> bool:
    for desc, factory in (
        ('aria-label "Write a caption..."', lambda: page.get_by_label("Write a caption...").first),
        ('textarea', lambda: page.locator('textarea').first),
        ('contenteditable', lambda: page.locator('div[contenteditable="true"]').first),
    ):
        try:
            box = factory()
            await box.wait_for(state="visible", timeout=8000)
            await box.click()
            # type() rather than fill(): the composer listens for real key events
            await box.type(caption, delay=random.uniform(4, 12))
            log.info("IG browser: caption written ← %s", desc)
            return True
        except Exception:
            continue
    log.warning("IG browser: could not find the caption box")
    return False


async def _latest_post_url(page, username: str) -> str:
    if not username or username.startswith("id:"):
        return ""
    try:
        await page.goto(f"https://www.instagram.com/{username}/", wait_until="domcontentloaded", timeout=30000)
        await _human_pause(1.5, 2.5)
        href = await page.get_attribute('a[href^="/p/"]', "href")
        if href:
            return f"https://www.instagram.com{href}"
    except Exception as exc:
        log.debug("IG browser: could not read the new post URL: %s", exc)
    return ""


async def post_photos(image_urls: list, caption: str, settings: dict) -> dict:
    """Publish one photo or a carousel through the web UI.

    Returns {"ok": bool, "url": str, "error": str} — the same shape as the
    private backend, so instagram.py can treat the two interchangeably.
    """
    paths = []
    for u in (image_urls or [])[:_MAX_IMAGES]:
        p = await _download(u)
        if p:
            paths.append(p)
    if not paths:
        return {"ok": False, "url": "", "error": "No image could be downloaded"}

    async with _lock:
        ctx = await _ensure_context(settings)
        if ctx is None:
            return {"ok": False, "url": "", "error": _state.get("error") or "No browser"}
        page = await ctx.new_page()
        try:
            await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=45000)
            await _human_pause(2, 3.5)
            if "/accounts/login" in page.url or "/challenge" in page.url:
                msg = "The browser profile is not signed in (Instagram showed a login or checkpoint page)"
                _state.update(status="needs_login", error=msg)
                return {"ok": False, "url": "", "error": msg}

            username = await _current_username(page)

            if not await _open_composer(page):
                return {"ok": False, "url": "", "error": "Could not open the Create dialog — Instagram's UI may have changed"}
            await _human_pause()

            # Feed the hidden input directly: no native file dialog to fight
            try:
                await page.set_input_files('input[type="file"]', paths, timeout=15000)
            except Exception as exc:
                return {"ok": False, "url": "", "error": f"Could not attach the images: {exc}"[:200]}
            await _human_pause(2, 3)

            if not await _next_step(page, "crop"):
                return {"ok": False, "url": "", "error": "Stuck on the crop step"}
            await _human_pause(1.2, 2)
            if not await _next_step(page, "filters"):
                return {"ok": False, "url": "", "error": "Stuck on the filter step"}
            await _human_pause(1.2, 2)

            if caption:
                await _fill_caption(page, caption)
                await _human_pause()

            shared = await _click_any(page, [
                ('role=button "Share"', lambda: page.get_by_role("button", name="Share").first),
                ('text "Share"', lambda: page.locator('div[role="button"]:has-text("Share")').last),
            ], "Share")
            if not shared:
                return {"ok": False, "url": "", "error": "Could not press Share"}

            # Instagram shows a confirmation panel once the upload completes
            confirmed = False
            for probe in ("text=Your post has been shared", "text=Post shared"):
                try:
                    await page.wait_for_selector(probe, timeout=90000)
                    confirmed = True
                    break
                except Exception:
                    continue
            if not confirmed:
                log.warning("IG browser: no confirmation panel — verifying on the profile instead")

            url = await _latest_post_url(page, username)
            _state.update(status="ok", error="", username=username, last_post_at=_now_iso())
            log.info("IG browser: posted %d image(s) as @%s → %s", len(paths), username or "?", url or "(url unknown)")
            return {"ok": True, "url": url, "error": ""}
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"[:300]
            log.error("IG browser: posting failed: %s", msg)
            _state["error"] = msg
            return {"ok": False, "url": "", "error": msg}
        finally:
            try:
                await page.close()
            except Exception:
                pass
            for p in paths:
                if os.path.basename(str(p)).startswith("igweb_"):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
