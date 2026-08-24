# Improvement plan: scrape Taobao directly (instead of the CSSBuy agent)

Status: proposal, written 2026-08-24 by the scheduled DropOS task. Nothing here is
implemented yet.

## Why move off the agent

Today products come from CSSBuy's search proxy (`scraper_cssbuy.py` listens to
`getCrossKeywordSearch` / `taoBaoGoodsByKeyWord`). That works, but it is a
middleman view of Taobao:

- **Thin data.** The agent search returns title, price, image, orders. No seller
  rating, no review text, no review photos, no stock/variant availability.
- **Fragile.** CSSBuy login has a captcha + reCAPTCHA, blocks datacenter IPs, and
  any redesign of their site breaks us.
- **No availability signal.** We sometimes approve and post a product that is
  actually sold out or has awful reviews. Going to the source fixes both:
  the item page shows SKU-level stock, and reviews (with photos) tell us whether
  the product looks like its listing photo.

## What "direct Taobao" gives DropOS

1. **Review mining** — pull the top N reviews per candidate product, feed them to
   the content model: reject items with "quality is terrible" patterns, and reuse
   real buyer photos/phrases for captions ("customers say…" angles). This plugs
   straight into the existing enrichment scoring as a new input.
2. **Availability checks** — before posting (and periodically for the whole
   REVIEWED backlog), confirm the item is still purchasable and the price hasn't
   moved. Auto-park products that go out of stock instead of posting dead items.
3. **Better economics data** — real Taobao price + sales count beats the agent's
   converted price for margin math in `pricing.py`.

## Reality check: Taobao is the hardest target in this space

- Search and item pages sit behind heavy anti-bot (slide captchas, login walls
  for search, signed `mtop` API calls with `_m_h5_tk` tokens).
- Datacenter IPs are blocked quickly; residential IP (the user's home PC, where
  local scraping already runs) is the viable path — same pattern as the
  Instagram direct-login backend.
- A logged-in Taobao account improves access but risks that account.

So the plan is staged, with fallbacks, rather than a big-bang rewrite.

## Staged plan

### Stage 0 — keep CSSBuy for *discovery*, add Taobao for *depth* (recommended first step)
The agent search already yields Taobao item IDs (`num_iid`) for the Taobao tab
results. Keep discovery as-is and add a `taobao_item.py` module that, for
already-shortlisted products only (top_priority / strong_candidate — tens per
day, not thousands), fetches the item page + reviews:

- Playwright with the saved local browser profile (headed first run to pass the
  slide captcha once, session persisted like `cssbuy_session.json`).
- Parse: SKU stock/variants, current price, seller rating, review count,
  top ~20 reviews with photos.
- New DB fields: `tb_item_id`, `tb_in_stock`, `tb_price_cny`, `tb_review_score`,
  `tb_reviews_json`, `tb_checked_at`.
- Hook 1: enrichment adds a "review sentiment" adjustment to the composite score.
- Hook 2: `posting_scheduler` refuses to post anything whose availability check
  is stale (> 7 days) or failed; a small worker re-checks queued products.

Low volume = low ban risk, and it delivers the two things the user actually
wants (reviews + availability) without replacing discovery.

### Stage 1 — direct Taobao *search* behind the same interface
Add `scraper_taobao.py` with the same contract as `scraper_cssbuy.scrape()`
(keywords in → normalized product dicts out) so `worker.py` / `local_scrape_upload.py`
can switch source per Settings (`scan_source: cssbuy | taobao | both`):

- Runs only on the local PC (residential IP) — extend the existing
  `LOCAL_SCRAPING_ONLY` path; never from Railway.
- Response-listener strategy like the CSSBuy scraper: navigate
  `s.taobao.com/search?q=…`, buffer the `mtop.relationrecommend` /
  `h5api.m.taobao.com` search responses instead of parsing HTML.
- Login with a dedicated (burner) Taobao account, session persisted; 2captcha is
  already a dependency for slide-captcha fallback.
- Throttle hard: a few keywords per hour with jitter, quiet hours — reuse the
  pacing helpers pattern from `instagram_private.py`.

### Stage 2 — retire or demote CSSBuy
Once Stage 1 survives 2–3 weeks of daily runs, make Taobao the default source
and keep CSSBuy as fallback (`both` mode already dedupes by image hash).

### Alternative worth pricing before building Stage 1
Third-party Taobao data APIs (e.g. item + review endpoints from API vendors)
cost a few dollars per thousand calls and remove all captcha/ban work. For
DropOS volumes (hundreds of items/day, tens of deep-checks/day) this may be
cheaper than maintaining a scraper. Decision gate: if a vendor covers
search + item + reviews for < ~$20/month at our volume, buy instead of build for
Stage 1, and keep Stage 0's Playwright checker only as fallback.

## Suggested order of work

1. Stage 0 item-checker (biggest value / effort ratio, no discovery risk).
2. Availability gate in the posting scheduler + re-check worker.
3. Review sentiment into enrichment scoring.
4. Price a data-API vendor; then Stage 1 build-or-buy decision.
