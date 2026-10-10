"""Click through every page of a running DropOS (AUTH_DISABLED=1, seeded with seed.py) and save
each GET /api response to demo/fixtures.json for the static demo.

    python demo/tools/record.py http://localhost:8000 [chromium-executable]
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from playwright.sync_api import sync_playwright

DEMO = Path(__file__).resolve().parent.parent
BASE = sys.argv[1].rstrip("/")
EXE = sys.argv[2] if len(sys.argv) > 2 else None

PAGES = [("home", None), ("review", "queue"), ("review", "textEdit"), ("review", "rejected"),
         ("posts", "queue"), ("posts", "posted"), ("posts", "all"), ("inbox", None), ("brands", None),
         ("scans", "new"), ("scans", "history"), ("analytics", "overview"), ("analytics", "margins"),
         ("analytics", "insights"), ("assistant", None), ("settings", "setup"), ("settings", "connections"),
         ("settings", "curation"), ("settings", "automation"), ("settings", "advanced")]

fixtures: dict[str, object] = {}


def key(url: str) -> str:
    u = urlsplit(url)
    return u.path + (f"?{u.query}" if u.query else "")


def on_response(resp):
    if resp.request.method != "GET" or "/api/" not in resp.url or "/api/image" in resp.url:
        return
    try:
        fixtures[key(resp.url)] = resp.json()
    except Exception:
        pass


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=EXE) if EXE else p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.on("response", on_response)
    page.route("**/demo-img/**", lambda r: r.fulfill(path=str(DEMO / "img" / Path(urlsplit(r.request.url).path).name)))
    page.goto(BASE + "/")
    page.wait_for_timeout(2500)
    for name, tab in PAGES:
        page.evaluate("([p, t]) => navigate(p, t)", [name, tab])
        page.wait_for_timeout(1500)
    browser.close()

# Detail views the pages open on click
extra = [f"/api/products/{i}" for i in range(1, 19)] + \
        [f"/api/jobs/{i}" for i in range(1, 5)] + [f"/api/jobs/{i}/pipeline" for i in range(1, 5)] + \
        [f"/api/brands/{i}/keywords" for i in (1, 2)] + ["/api/jobs", "/api/scheduler/status",
         "/api/instagram/reply-log", "/api/ai/recommendations", "/api/inbox?all=true", "/api/inbox?all=false"]
with httpx.Client(base_url=BASE, timeout=20) as c:
    for path in extra:
        r = c.get(path)
        if r.status_code == 200:
            fixtures.setdefault(path, r.json())

(DEMO / "fixtures.json").write_text(json.dumps(fixtures, ensure_ascii=False, indent=0), encoding="utf-8")
print(f"recorded {len(fixtures)} responses")
for k in sorted(fixtures):
    print(" ", k)
