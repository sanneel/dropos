# DropOS — product sourcing backoffice for Tskvili / Cute Couple Gifts

DropOS finds couple-gift products on 1688 / Taobao (via CSSBuy), scores them with
Gemini vision, and gives you a one-screen review queue. Approved products are
posted to Instagram (single image, carousel, or a multi-product collage).
It is a single-user tool that **runs on your own PC — no hosting required**.

```
scrape (CSSBuy, Playwright) ─► filters (spam / margin / dedup / rule score)
      ─► AI curator (Gemini collage batch → Groq text fallback → rule score)
      ─► Review queue ─► Approved ─► Instagram (now / scheduled / collage) ─► Posted
                     └► Text edit (Clipdrop watermark removal) ─► Approved
```

## Run it (Windows / macOS / Linux)

Requirements: Python 3.10+ and an internet connection. Nothing else.

```bash
git clone https://github.com/sanneel/dropos && cd dropos
./start.sh        # Windows: start.bat
```

The first start installs the Python packages and Chromium (a few minutes), starts an
**embedded PostgreSQL** in `./data/pg`, and opens <http://localhost:8000>, where you
create your admin account. After that:

1. **Settings → AI & API keys** — paste a free Gemini key (aistudio.google.com). Without
   it products still flow, but every item lands in Review unscored.
2. **Settings → CSSBuy scraper** — your CSSBuy login. On a desktop the browser window
   opens on first login so you can pass the captcha; the session is saved afterwards.
3. **Pipeline → + Scan** — enter keywords, start. Scored products appear in **Review**.
4. **Settings → Instagram** — Page access token + business account ID to post for real
   (until then posting is simulated).

Everything you configure is stored in the database; `./data` is the whole installation
(back it up by copying the folder). Stop with `./stop.sh` / `stop.bat`.

### Optional `.env`

Copy `.env.example` to `.env` if you want to:

- keep using an external PostgreSQL (e.g. your existing Supabase DB) → `DATABASE_URL`
- re-host product photos on Supabase Storage (free) → `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
  *(recommended for Instagram — Meta must download images from a public URL; supplier CDN links
  usually work, Supabase always works)*
- pin the admin login / JWT secret / API keys via env instead of the UI

### What needs the internet to reach *you*

Only two optional things: the **comment/DM auto-reply webhook** and the **image proxy**.
On a PC those need a tunnel (Cloudflare Tunnel, ngrok) — set the tunnel URL as
*Public app URL* in Settings. Scraping, scoring, reviewing and posting do **not**.

## Deploy on a server instead (optional)

```bash
docker compose up -d --build      # app + Postgres, data in named volumes
```

The image is based on Microsoft's Playwright image, so scraping works in the container.
Set `APP_ENV=production` (done in compose), put it behind HTTPS, and set
`PUBLIC_BASE_URL`. `railway.toml` / `nixpacks.toml` are kept for Railway-style hosts.
If the host blocks scraping (datacenter IP / no browser), run the scraper on your PC with
[LOCAL_SCRAPING.md](LOCAL_SCRAPING.md) and upload into the hosted app.

## Review workflow

| Page | What it does |
|------|--------------|
| **Today** | counts, approval rate, last scan funnel |
| **Pipeline → Review** | AI-scored products; approve / reject (hotkeys `j` `k` `a` `r` `Enter` `Esc`) |
| **Text edit** | approved products whose photo has Chinese text — Clipdrop clean-up |
| **Approved** | post to Instagram (single / carousel / collage), or mark live without posting |
| **Posted / Rejected / Catalog** | history, reconsider, inline edits, search |
| **+ Scan / Scan log** | start a scan, see where each scraped product dropped out |
| **Analytics** | overview, real margins, deterministic insights on your decisions |
| **AI** | chat over the pipeline: review pending, find rejected gems, bulk approve |
| **Settings** | store persona for the AI prompt, thresholds, markups, keys, posting schedule, auto-reply rules |

## Repo layout

```
backend/
  main.py               API routes, auth + first-run setup, lifespan (worker + schedulers)
  worker.py             AI scoring loop + QUEUED publisher loop
  runner.py             scrape → filter → score → hand-off
  enrichment.py         Gemini / Groq / mock curator + prompt template
  filter_engine.py      bouncer filters, pricing, dedup
  scorer.py             rule-based pre-score
  instagram.py          Graph API posting (single / carousel)
  instagram_replies.py  comment / DM auto-reply engine (webhook)
  posting_scheduler.py  peak-hour auto-posting (APScheduler)
  scraper_cssbuy.py     Playwright CSSBuy scraper
  local_scrape_upload.py  run the scraper on a PC and upload to a hosted instance
  database.py           schema, migrations, queries, embedded Postgres bootstrap
  config/paths.py       data directory layout
  frontend/             the SPA (index.html, assets/app.js, assets/styles.css)
data/                   runtime data (created on first start, git-ignored)
```
