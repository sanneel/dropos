# Scraping on your PC for a hosted DropOS

You only need this when DropOS itself runs on a server that cannot scrape
(datacenter IP blocked by CSSBuy, no browser in the container…). If you run
DropOS on your own PC with `start.sh` / `start.bat`, scraping already happens
locally — skip this file.

## Hosted instance setup

In the hosted app's **Settings → CSSBuy scraper**:

- tick **Store data here, scrape locally only**
- set an **Ingest API token** (any private random string)

(or set the env vars `LOCAL_SCRAPING_ONLY=true` and `INGEST_API_TOKEN=…`).

With local-only mode on, `/api/scan` and the server scan loop are disabled. The
hosted app still filters, scores, enriches and shows the review queue.

## On your PC

From this repo:

```powershell
pip install -r backend/requirements.txt
python -m playwright install chromium

$env:WEBSITE_URL="https://your-hosted-dropos.example.com"
$env:INGEST_API_TOKEN="same-token-as-the-hosted-app"
$env:CSSBUY_USERNAME="your-cssbuy-email"
$env:CSSBUY_PASSWORD="your-cssbuy-password"
$env:SCAN_KEYWORDS="couple gifts,anniversary gifts"
$env:CSSBUY_SOURCE="1688"
$env:MAX_PER_KEYWORD="100"
python backend/local_scrape_upload.py
```

The script logs into CSSBuy (the browser window opens on a desktop so you can
pass the captcha on the first login; the session is saved afterwards), scrapes
each keyword and uploads the results to `/api/ingest/products` — one keyword at
a time. It runs once by default; set `SCRAPE_INTERVAL=3600` (or `--interval 3600`)
to keep looping.
