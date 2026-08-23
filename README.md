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

1. **Settings → Connections** — paste a free Gemini key (aistudio.google.com). Without
   it products still flow, but every item lands in Review unscored.
2. **Settings → Connections → CSSBuy** — your CSSBuy login. On a desktop the browser window
   opens on first login so you can pass the captcha; the session is saved afterwards.
3. **Scans → New scan** — keywords, start. Scored products appear in **Review** (or skip it
   when Autopilot approves them).
4. **Settings → Connections → Instagram** — Page access token + business account ID to post
   for real (until then posting is simulated).
5. **Home → Autopilot ON.** From here on it scans, scores, approves, cleans and posts by
   itself; check *Needs you* once a day and fulfil orders from **Inbox**.

Everything you configure is stored in the database; `./data` is the whole installation
(back it up by copying the folder). Stop with `./stop.sh` / `stop.bat`.

### Optional `.env`

Copy `.env.example` to `.env` if you want to:

- keep using an external PostgreSQL (e.g. your existing Supabase DB) → `DATABASE_URL`
- re-host product photos on Supabase Storage (free) → `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
  *(recommended for Instagram — Meta must download images from a public URL; supplier CDN links
  usually work, Supabase always works)*
- pin the admin login / JWT secret / API keys via env instead of the UI

### Brands & the keyword lab

Create a **brand** per market (couple gifts, home decor, pets…). Each brand carries its own
AI persona — products scraped for it are scored against *that* niche — and its own keyword
pool. Every keyword's real results are tracked (products found → AI-approved → posted) and
combined into a performance score:

```
perf = approval_rate × 0.55 + post_rate × 0.25 + avg_AI_score/10 × 0.20   (needs ≥5 scored products)
```

Scans use ~2/3 proven winners + ~1/3 untested keywords; proven losers are skipped. When the
untested pool runs dry (or weekly), Gemini generates new keywords from the winning patterns.

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

## Autopilot — hands-off mode

Turn **Autopilot** on (Home page) and the whole flow runs by itself; you only step in
for what it cannot decide and for fulfilling orders:

| Stage | What runs automatically | Setting |
|-------|-------------------------|---------|
| Find products | rotates through your **brands**, scanning each one's best keywords every *N* hours | `auto_scan_enabled`, `scan_interval_hours` |
| Keyword lab | AI tops up each brand's keyword pool weekly (or when untested ones run out), copying the patterns of proven winners; losers are skipped | per-brand `auto_keywords_enabled` |
| AI scoring | Gemini vision scores every scraped product (always on) | Gemini key |
| Auto-approve | winners above the threshold skip the review queue | `auto_approve_min_score`, `auto_approve_verdicts` |
| Clean photos | Chinese text / watermarks removed with Clipdrop | `auto_clean_images` + Clipdrop key |
| Post to Instagram | best approved product posted at peak hours, daily cap | `post_schedule_enabled`, `post_times`, `max_posts_per_day` |
| Content writer | a second model (Claude / OpenAI) rewrites the caption right before each post — hook → desire → order CTA, fresh hashtags | `content_provider`, `content_rewrite_enabled` |
| Answer comments & DMs | keyword rules reply instantly; order intent lands in **Inbox** | `instagram_*_reply_enabled`, `lead_keywords` |

Everything Autopilot does is written to the activity feed on Home, and the
“Needs you” list shows the only things left for a human: borderline products,
photos that could not be cleaned, possible orders, and errors.

## Pages

| Page | What it does |
|------|--------------|
| **Home** | Autopilot master switch, per-stage status and toggles, needs-you list, today’s numbers, activity feed |
| **Review** | *Needs decision* (borderline products), *Text edit* (photos with Chinese text), *Rejected* — hotkeys `j` `k` `a` `r` `Enter` `Esc` |
| **Posts** | *Queue* (approved, best first — next up marked), *Posted* (with Instagram links), *All products* (search + inline edit) |
| **Inbox** | comments & DMs from the webhook, possible orders first, reply / mark done |
| **Brands** | one card per market: its persona (fed into the AI curator) and its keyword pool with real per-keyword results (found / approved / posted / performance score) |
| **Scans** | start a scan, see where every scraped product dropped out |
| **Analytics** | overview, real margins, deterministic insights on your decisions |
| **Assistant** | chat over the pipeline: review in bulk, find rejected gems |
| **Settings** | setup checklist → connections → curation → automation → advanced |

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
  autopilot.py          hands-off policy (what to approve/clean/scan/post) + Home status
  keyword_lab.py        per-brand keyword scoring, scan selection, AI generation
  content_ai.py         second-model content layer (Claude via official SDK / OpenAI / Gemini / Groq)
  activity.py           activity log writer
  frontend/             the SPA — core.js (router/shell), one file per page, styles.css
data/                   runtime data (created on first start, git-ignored)
```
