"""One-click Instagram connect and the import routes, through the real app.

Instagram's servers are replaced by a stand-in that answers the way Meta's
documentation says they do; the database by a small in-memory one."""
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

import activity
import fx
import instagram
import instagram_oauth
import link_import
import main

APP_ID, APP_SECRET = "1234567890", "ig-app-secret"


class FakeDB:
    def __init__(self):
        self.settings = {}
        self.products = {}
        self.activity = []

    async def get_settings(self):
        return dict(self.settings)

    async def update_settings(self, data):
        self.settings.update(data)

    async def default_brand_id(self):
        return 7

    async def fetchval(self, query, *args):
        assert "FROM products WHERE source_id" in query
        return next((pid for pid, p in self.products.items() if p["source_id"] == args[0]), None)

    async def insert_product(self, product, job_id):
        pid = len(self.products) + 1
        self.products[pid] = {**product, "id": pid, "job_id": job_id}

    async def get_product(self, pid):
        return self.products.get(pid)

    async def log_activity(self, kind, message, **extra):
        self.activity.append((kind, message))


class Instagram:
    """Stand-in for api.instagram.com and graph.instagram.com."""

    def __init__(self):
        self.calls = []
        self.refresh_reply = (200, {"access_token": "LONG-2", "token_type": "bearer", "expires_in": 5184000})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url = request.url
        if url.host == "api.instagram.com" and url.path == "/oauth/access_token":
            return httpx.Response(200, json={"data": [{"access_token": "SHORT", "user_id": "111",
                                                       "permissions": ",".join(instagram_oauth.SCOPES)}]})
        if url.host == "graph.instagram.com" and url.path == "/access_token":
            return httpx.Response(200, json={"access_token": "LONG-1", "token_type": "bearer", "expires_in": 5184000})
        if url.host == "graph.instagram.com" and url.path == "/refresh_access_token":
            return httpx.Response(self.refresh_reply[0], json=self.refresh_reply[1])
        if url.host == "graph.instagram.com" and url.path.endswith("/me/subscribed_apps"):
            return httpx.Response(200, json={"success": True})
        if url.host == "graph.instagram.com" and url.path.endswith("/me"):
            return httpx.Response(200, json={"id": "scoped-1", "user_id": "17841400000000000", "username": "real.shop",
                                             "account_type": "BUSINESS", "followers_count": 321})
        return httpx.Response(400, json={"error": {"message": "unexpected call", "code": 1}})

    def find(self, path_end):
        return next(c for c in self.calls if c.url.path.endswith(path_end))

    def at(self, host, path):
        return next(c for c in self.calls if c.url.host == host and c.url.path == path)


@pytest.fixture
def app():
    db = FakeDB()
    ig = Instagram()
    saved = (main.db, main._db_ready, instagram_oauth._transport)
    main.db, main._db_ready = db, True
    activity.bind(db)
    instagram_oauth._transport = httpx.MockTransport(ig)
    # Fixed exchange rates, so no test depends on the National Bank's feed.
    fx._state.update(rates={"USD": 2.7, "EUR": 3.1}, date="2026-01-01", fetched_at=time.time(), approximate=False)
    main.limiter.reset()
    client = TestClient(main.app, base_url="https://dropos.test", follow_redirects=False)
    client.headers["Authorization"] = f"Bearer {main._issue_token(1)}"
    yield client, db, ig
    main.db, main._db_ready, instagram_oauth._transport = saved


def configure(db):
    db.settings.update(instagram_app_id=APP_ID, instagram_app_secret=APP_SECRET)


def connect(client):
    start = client.post("/api/instagram/oauth/start").json()["url"]
    state = parse_qs(urlsplit(start).query)["state"][0]
    return client.get("/api/instagram/oauth/callback", params={"code": "abc123#_", "state": state})


def signed(payload):
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(hmac.new(APP_SECRET.encode(), body.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{sig}.{body}"


# ── the Connect button ────────────────────────────────────────────────────────

def test_before_the_owner_setup_the_button_explains_what_is_missing(app):
    client, db, _ = app
    assert client.post("/api/instagram/oauth/start").status_code == 409
    status = client.get("/api/settings").json()["instagram_oauth"]
    assert status["ready"] is False and status["connected"] is False
    assert status["redirect_uri"] == "https://dropos.test/api/instagram/oauth/callback"


def test_connect_sends_the_merchant_to_instagram_with_the_right_request(app):
    client, db, _ = app
    configure(db)
    resp = client.post("/api/instagram/oauth/start")
    url = urlsplit(resp.json()["url"])
    query = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://www.instagram.com/oauth/authorize"
    assert query["client_id"] == [APP_ID]
    assert query["redirect_uri"] == ["https://dropos.test/api/instagram/oauth/callback"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == [",".join(instagram_oauth.SCOPES)]
    cookie = resp.headers["set-cookie"]
    assert "dropos_ig_state=" in cookie and "HttpOnly" in cookie and "Secure" in cookie
    assert APP_SECRET not in resp.text


def test_the_start_call_needs_a_signed_in_owner(app):
    client, db, _ = app
    configure(db)
    del client.headers["Authorization"]
    assert client.post("/api/instagram/oauth/start").status_code == 401
    assert client.post("/api/import/link", json={"text": "https://shop.example/x"}).status_code == 401
    assert client.get("/api/import/button").status_code == 401


def test_coming_back_from_instagram_connects_the_shop(app):
    client, db, ig = app
    configure(db)
    resp = connect(client)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/?ig=connected#settings/connections"

    exchange = parse_qs(ig.at("api.instagram.com", "/oauth/access_token").content.decode())
    assert exchange["code"] == ["abc123"], 'the "#_" Instagram appends is removed'
    assert exchange["grant_type"] == ["authorization_code"]
    assert exchange["redirect_uri"] == ["https://dropos.test/api/instagram/oauth/callback"]
    assert exchange["client_secret"] == [APP_SECRET]
    long_lived = ig.at("graph.instagram.com", "/access_token")
    assert long_lived.url.params["grant_type"] == "ig_exchange_token"
    assert ig.find("/me/subscribed_apps").url.params["subscribed_fields"] == "comments,messages"

    s = db.settings
    assert s["instagram_access_token"] == "LONG-1"
    assert s["instagram_user_id"] == "17841400000000000"
    assert s["instagram_username"] == "real.shop"
    assert s["instagram_backend"] == "graph"
    assert datetime.fromisoformat(s["instagram_token_expires_at"]) > datetime.now(timezone.utc) + timedelta(days=58)

    public = client.get("/api/settings").json()
    assert public["instagram_connected"] is True and public["instagram_mode"] == "graph"
    assert public["instagram_oauth"]["connected"] is True and public["instagram_oauth"]["username"] == "real.shop"
    assert "LONG-1" not in json.dumps(public), "the token never leaves the server"
    # Posting and replies now talk to Instagram's own host.
    assert instagram._graph(db.settings).startswith("https://graph.instagram.com/v")
    assert instagram._graph({}).startswith("https://graph.facebook.com/v")


def test_a_forged_stale_or_stolen_callback_is_refused(app):
    client, db, _ = app
    configure(db)
    start = client.post("/api/instagram/oauth/start").json()["url"]
    state = parse_qs(urlsplit(start).query)["state"][0]

    # another browser (no cookie) cannot finish someone else's connection
    other = TestClient(main.app, base_url="https://dropos.test", follow_redirects=False)
    assert other.get("/api/instagram/oauth/callback", params={"code": "x", "state": state}).headers["location"].startswith("/?ig=expired")
    # a made-up state
    assert client.get("/api/instagram/oauth/callback", params={"code": "x", "state": "nope"}).headers["location"].startswith("/?ig=expired")
    # a state signed for something else
    token = main._issue_token(1)
    assert client.get("/api/instagram/oauth/callback", params={"code": "x", "state": token}).headers["location"].startswith("/?ig=expired")
    assert "instagram_access_token" not in db.settings


def test_cancelling_on_instagram_changes_nothing(app):
    client, db, _ = app
    configure(db)
    resp = client.get("/api/instagram/oauth/callback", params={"error": "access_denied", "error_reason": "user_denied"})
    assert resp.headers["location"] == "/?ig=cancelled#settings/connections"
    assert "instagram_access_token" not in db.settings


def test_disconnect_forgets_the_token(app):
    client, db, _ = app
    configure(db)
    connect(client)
    assert client.post("/api/instagram/oauth/disconnect").json() == {"ok": True}
    assert db.settings["instagram_access_token"] == ""
    assert client.get("/api/settings").json()["instagram_oauth"]["connected"] is False
    assert instagram._graph(db.settings).startswith("https://graph.facebook.com/")


# ── the connection keeps itself alive ─────────────────────────────────────────

def test_a_fresh_token_is_left_alone_and_an_ageing_one_is_renewed(app):
    client, db, ig = app
    configure(db)
    connect(client)
    import asyncio
    assert asyncio.run(instagram_oauth.refresh_if_due(db, db.settings)) == "fresh"

    now = datetime.now(timezone.utc)
    db.settings.update(instagram_token_expires_at=(now + timedelta(days=10)).isoformat(),
                       instagram_token_refreshed_at=(now - timedelta(days=2)).isoformat())
    assert asyncio.run(instagram_oauth.refresh_if_due(db, db.settings)) == "renewed"
    assert db.settings["instagram_access_token"] == "LONG-2"
    refresh = ig.find("/refresh_access_token")
    assert refresh.url.params["grant_type"] == "ig_refresh_token" and refresh.url.params["access_token"] == "LONG-1"
    assert datetime.fromisoformat(db.settings["instagram_token_expires_at"]) > now + timedelta(days=58)


def test_when_instagram_withdraws_access_the_shop_is_asked_to_reconnect(app):
    client, db, ig = app
    configure(db)
    connect(client)
    now = datetime.now(timezone.utc)
    db.settings.update(instagram_token_expires_at=(now + timedelta(days=10)).isoformat(),
                       instagram_token_refreshed_at=(now - timedelta(days=2)).isoformat())
    ig.refresh_reply = (400, {"error": {"message": "Error validating access token", "type": "OAuthException", "code": 190}})
    import asyncio
    assert asyncio.run(instagram_oauth.refresh_if_due(db, db.settings)) == "revoked"
    status = client.get("/api/settings").json()["instagram_oauth"]
    assert status["connected"] is False and status["needs_reconnect"] is True
    # one press brings it back
    assert connect(client).headers["location"].startswith("/?ig=connected")
    assert client.get("/api/settings").json()["instagram_oauth"]["needs_reconnect"] is False


def test_a_network_hiccup_during_renewal_keeps_the_working_token(app):
    client, db, ig = app
    configure(db)
    connect(client)
    now = datetime.now(timezone.utc)
    db.settings.update(instagram_token_expires_at=(now + timedelta(days=10)).isoformat(),
                       instagram_token_refreshed_at=(now - timedelta(days=2)).isoformat())
    ig.refresh_reply = (500, {"error": {"message": "temporarily unavailable", "code": 2}})
    import asyncio
    assert asyncio.run(instagram_oauth.refresh_if_due(db, db.settings)) == "failed"
    assert db.settings["instagram_access_token"] == "LONG-1"


# ── calls Meta makes to us ────────────────────────────────────────────────────

def test_meta_callbacks_are_honoured_only_when_properly_signed(app):
    client, db, _ = app
    configure(db)
    connect(client)
    del client.headers["Authorization"]          # Meta does not log in

    assert client.post("/api/instagram/oauth/data-deletion", data={"signed_request": "AAAA.BBBB"}).status_code == 400
    assert db.settings["instagram_access_token"] == "LONG-1"

    # signed, but about some other Instagram account: acknowledged, nothing touched
    assert client.post("/api/instagram/oauth/deauthorize", data={"signed_request": signed({"user_id": "999"})}).status_code == 200
    assert db.settings["instagram_access_token"] == "LONG-1"

    assert client.post("/api/instagram/oauth/deauthorize", data={"signed_request": signed({"user_id": "scoped-1"})}).status_code == 200
    assert db.settings["instagram_access_token"] == "" and db.settings["instagram_needs_reconnect"] is True

    db.settings.update(instagram_user_id="17841400000000000")
    reply = client.post("/api/instagram/oauth/data-deletion", data={"signed_request": signed({"user_id": "17841400000000000"})}).json()
    assert reply["confirmation_code"] and reply["url"].startswith("https://dropos.test/")
    assert db.settings["instagram_username"] == ""


# ── add by link ───────────────────────────────────────────────────────────────

PRODUCT_PAGE = """<html><head><script type="application/ld+json">{"@type":"Product","name":"Ceramic Vase",
"image":["https://cdn.decor.example/1.jpg","https://cdn.decor.example/2.jpg"],
"offers":{"@type":"Offer","price":"149","priceCurrency":"GEL"}}</script></head></html>"""


@pytest.fixture
def shop_site(monkeypatch):
    def handler(request):
        if request.url.path == "/vase":
            return httpx.Response(200, html=PRODUCT_PAGE)
        if request.url.path == "/wall":
            return httpx.Response(403, html="<title>Access denied</title>")
        return httpx.Response(200, html="<title>About</title><h1>Our story</h1>")

    transport = httpx.MockTransport(handler)
    original = link_import.import_from_text

    async def through_fake_site(text, **_):
        return await original(text, allow_private=True, transport=transport)

    monkeypatch.setattr(link_import, "import_from_text", through_fake_site)


def test_a_pasted_link_becomes_a_product_waiting_for_its_caption(app, shop_site):
    client, db, _ = app
    res = client.post("/api/import/link", json={"text": "nice one https://decor.test/vase?utm_source=ig"}).json()
    assert res["ok"] is True and res["already"] is False
    p = res["product"]
    assert p["title"] == "Ceramic Vase" and p["source"] == "link" and p["stage"] == "SCRAPED"
    assert p["cost_eur"] == 149 and p["sell_price_eur"] > 149 and len(p["images"]) == 2
    assert p["brand_id"] == 7, "falls back to the default brand"
    assert res["cost"] == {"amount": 149, "currency": "GEL", "max": None} and res["missing"] == []
    assert db.activity[-1][0] == "needs_review"

    again = client.post("/api/import/link", json={"text": "https://decor.test/vase"}).json()
    assert again["already"] is True and again["product"]["id"] == p["id"] and len(db.products) == 1


def test_misses_come_back_as_a_reason_not_an_error(app, shop_site):
    client, db, _ = app
    assert client.post("/api/import/link", json={"text": "just words"}).json() == {
        "ok": False, "reason": "no_url", "url": None, "site": "", "shared_title": None}
    assert client.post("/api/import/link", json={"text": "https://decor.test/about"}).json()["reason"] == "not_product"
    blocked = client.post("/api/import/link", json={"text": "US $4.56 | Nordic Ceramic Vase Pot https://decor.test/wall"}).json()
    assert blocked["reason"] == "blocked" and blocked["shared_title"] == "Nordic Ceramic Vase Pot"
    assert db.products == {}


def test_the_browser_button_adds_a_product_from_another_site(app):
    client, db, _ = app
    button = client.get("/api/import/button").json()
    assert button["href"].startswith("javascript:") and button["base"] == "https://dropos.test"
    token = db.settings["import_button_token"]
    assert "import_button_token" not in client.get("/api/settings").json(), "the button token is not shown back"
    assert client.get("/api/import/button").json()["href"] == button["href"], "the button stays the same"

    snapshot = """<title>Woven Basket - Store</title><h1>Woven Basket</h1><span class="price" data-fs="28">$24.00</span>
      <img src="https://img.store.example/b1.jpg" width="1200" height="1200">"""
    outsider = TestClient(main.app, base_url="https://dropos.test", follow_redirects=False)   # no login, like a form post from the shop's page
    ok = outsider.post("/api/import/clip", data={"token": token, "url": "https://store.example/item/9", "html": snapshot})
    assert ok.status_code == 303 and ok.headers["location"] == "/?imported=1#review/queue"
    assert db.products[1]["title"] == "Woven Basket" and db.products[1]["source"] == "link"

    assert outsider.post("/api/import/clip", data={"token": "wrong", "url": "https://store.example/item/9", "html": snapshot}).status_code == 403
    assert outsider.post("/api/import/clip", data={"token": token, "url": "javascript:alert(1)", "html": snapshot}).status_code == 400
    empty = outsider.post("/api/import/clip", data={"token": token, "url": "https://store.example/about", "html": "<title>x</title>"})
    assert empty.headers["location"] == "/?imported=none#scans/link"
    assert len(db.products) == 1
