# Local Scraping Mode

Use this when the website should only store/process data, while CSSBuy scraping runs on your PC.

## Website setup

Set these in the hosted app settings or environment:

- `LOCAL_SCRAPING_ONLY=true`
- `INGEST_API_TOKEN=<a private random token>`

When local-only mode is enabled, `/api/scan` and scheduled server-side scans are disabled. The website still stores raw products, runs filters/scoring/AI enrichment, and shows the review queue.

## Local run

From this repo on your PC:

```powershell
$env:WEBSITE_URL="https://your-website.example.com"
$env:INGEST_API_TOKEN="same-token-as-hosted-site"
$env:CSSBUY_USERNAME="your-cssbuy-email"
$env:CSSBUY_PASSWORD="your-cssbuy-password"
$env:SCAN_KEYWORDS="couple gifts,anniversary gifts"
$env:CSSBUY_SOURCE="1688"
$env:MAX_PER_KEYWORD="100"
$env:PLAYWRIGHT_HEADED="1"
python backend/local_scrape_upload.py
```

The script logs into CSSBuy locally, scrapes results, and uploads them to `/api/ingest/products`.
`PLAYWRIGHT_HEADED=1` is useful for the first run if you need to solve a login captcha manually.
