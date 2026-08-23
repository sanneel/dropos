# DropOS — product sourcing backoffice for Tskvili / Cute Couple Gifts

DropOS finds couple-gift products on 1688 / Taobao (via CSSBuy), scores them with
Gemini vision, and gives you a one-screen review queue. Approved products are
posted to Instagram (single image, carousel, or a multi-product collage) and
can be published to the website catalog.

```
scrape (CSSBuy, local or server) ─► filters (spam / margin / dedup / rule score)
      ─► AI curator (Gemini collage batch → Groq text fallback → rule score)
      ─► Review queue ─► Approved ─► Instagram / website ─► Posted
                     └► Text edit (Clipdrop watermark removal) ─► Approved
```

## Stack

- **Backend** — FastAPI + asyncpg (PostgreSQL), background worker loops (`backend/`)
- **Frontend** — single-page vanilla JS app served by the backend (`backend/frontend/`)
- **Storage** — Supabase Storage for product images (optional; falls back to source URLs)
- **AI** — Gemini (image + text, primary), Groq Llama (text-only fallback), rule-based last resort
- **Deploy** — Railway (Nixpacks, `railway.toml` / `nixpacks.toml`) or Docker (`docker-compose.yml`)

## Run locally

1. Python 3.11+, a PostgreSQL database (Docker: `docker compose up postgres`).
2. `cp .env.example .env` and fill in at least `DATABASE_URL`, `JWT_SECRET`, `ADMIN_EMAIL`,
   `ADMIN_PASSWORD_HASH` (bcrypt — `python -c "import bcrypt;print(bcrypt.hashpw(b'yourpass',bcrypt.gensalt()).decode())"`).
3. `pip install -r backend/requirements.txt`
4. `./start.sh` (or `start.bat` on Windows) — opens <http://localhost:8000>.

Sign in with the admin e-mail / password. Everything else (AI keys, CSSBuy login,
Instagram token, posting schedule) is configured in **Settings** and stored in the DB;
env vars of the same name override DB values (see `backend/config/runtime.py`).

## Deploy (Railway)

1. Create a Railway service from this repo (root directory = repo root). The Nixpacks
   config installs Playwright/Chromium for server-side scraping.
2. Set the variables from `.env.example`. Use the Supabase **session pooler** connection
   string for `DATABASE_URL`; `DATABASE_SSL` defaults to `require` for non-local hosts.
3. Set `FRONTEND_DOMAIN` and `PUBLIC_BASE_URL` to the public URL (used for CORS and as
   the image proxy Instagram fetches from).
4. Push to `main` — Railway builds and restarts. `/health` is the health check.

First boot creates the schema, seeds default settings and the admin user.

## Scraping options

- **Server-side** — put CSSBuy credentials in Settings; scans run from the Scan page or on
  the `SCRAPE_INTERVAL` loop.
- **Local-only** (recommended when CSSBuy blocks datacenter IPs) — enable *local scraping
  only* + set an *Ingest API token* in Settings, then run the scraper on your PC:
  see [LOCAL_SCRAPING.md](LOCAL_SCRAPING.md).

## Review workflow

| Page | What it does |
|------|--------------|
| **Today** | counts, approval rate, last scan funnel |
| **Pipeline → Review** | AI-scored products; approve / reject (hotkeys `j` `k` `a` `r` `Enter`) |
| **Text edit** | approved products whose photo has Chinese text — Clipdrop clean-up |
| **Approved** | post to Instagram (single / carousel / collage), or publish to website only |
| **Posted / Rejected / Catalog** | history, reconsider, inline edits |
| **Scan / Scan log** | start a server scan, see where each scraped product dropped out |
| **Analytics** | overview, real margins, deterministic insights on your decisions |
| **Settings** | store persona for the AI prompt, thresholds, markups, keys, schedules |

## Repo layout

```
backend/
  main.py              API routes, auth, lifespan (worker + schedulers)
  worker.py            AI scoring loop + QUEUED publisher loop
  runner.py            scrape → filter → score → hand-off
  enrichment.py        Gemini / Groq / mock curator + prompt template
  filter_engine.py     bouncer filters, pricing, dedup
  scorer.py            rule-based pre-score
  instagram.py         Graph API posting (single / carousel)
  posting_scheduler.py peak-hour auto-posting (APScheduler)
  scraper_cssbuy.py    Playwright CSSBuy scraper
  local_scrape_upload.py  run the scraper on your PC and upload results
  database.py          schema, migrations, queries
  frontend/            the SPA (index.html, assets/app.js, assets/styles.css)
```
