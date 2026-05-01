"""
Pipeline orchestrator.
Stages: scrape → raw store → filter → profit → dedup → rule-score → AI enrich → save
"""

import logging
from typing import Optional

from database import db
from enrichment import ai_enrich
from filter_engine import basic_filter, dedup, profit_filter
from scorer import score_product
import scraper_1688
import scraper_taobao
import scraper_cssbuy

log = logging.getLogger(__name__)

# Products scoring below this raw threshold are dropped before AI to save tokens.
_AI_PREFILTER_THRESHOLD = 40


async def run_pipeline(
    job_id: int,
    keywords: list,
    max_per_keyword: int = 50,
    settings: Optional[dict] = None,
) -> dict:
    """
    Full pipeline for one job. Returns summary dict.
    Safe to re-call; insert_product uses INSERT OR IGNORE on source_id.
    """
    if settings is None:
        settings = await db.get_settings()

    token: Optional[str] = settings.get("apify_token") or None

    await db.update_job(job_id, status="scraping", progress=5)

    # ── 1. Scrape ──────────────────────────────────────────────────────────────
    cssbuy_user = settings.get("cssbuy_username", "")
    cssbuy_pass = settings.get("cssbuy_password", "")
    captcha_key = settings.get("captcha_2captcha_key", "")
    use_cssbuy = bool(cssbuy_user and cssbuy_pass)

    if use_cssbuy:
        # CSSBuy is the real data source — skip 1688/Taobao to avoid mock pollution
        raw_1688 = []
        raw_taobao = []
        raw_cssbuy = await scraper_cssbuy.scrape(
            keywords, max_per_keyword,
            username=cssbuy_user, password=cssbuy_pass, captcha_key=captcha_key,
        )
    else:
        # Apify-based scrapers (return mock data when no token)
        raw_1688 = await scraper_1688.scrape(keywords, max_per_keyword, token)
        raw_taobao = await scraper_taobao.scrape(keywords, max_per_keyword, token)
        raw_cssbuy = []

    raw_all = raw_1688 + raw_taobao + raw_cssbuy

    log.info(
        "Job %d scraped %d products (1688: %d, taobao: %d, cssbuy: %d)",
        job_id, len(raw_all), len(raw_1688), len(raw_taobao), len(raw_cssbuy),
    )

    # ── 2. Store raw data ──────────────────────────────────────────────────────
    for p in raw_all:
        await db.insert_raw(p, job_id)

    await db.update_job(job_id, status="scraping", progress=20, scraped=len(raw_all))

    # ── 3. Basic filter (spam, orders, rating, images) ─────────────────────────
    filtered = basic_filter(raw_all, settings)
    await db.update_job(job_id, status="filtering", progress=35, after_basic=len(filtered))

    # ── 4. Profit filter (adds cost/sell/margin fields) ────────────────────────
    profitable = [p for p in filtered if profit_filter(p, settings)]
    await db.update_job(job_id, status="calculating", progress=50, after_profit=len(profitable))

    # ── 5. Dedup by first image ────────────────────────────────────────────────
    deduped = dedup(profitable)
    await db.update_job(job_id, status="deduping", progress=55, after_dedup=len(deduped))

    # ── 6. Rule-based scoring + pre-filter ────────────────────────────────────
    scored = [score_product(p) for p in deduped]
    candidates = [p for p in scored if p.get("raw_score", 0) >= _AI_PREFILTER_THRESHOLD]

    log.info(
        "Job %d: %d candidates after rule scoring (dropped %d LOW)",
        job_id, len(candidates), len(scored) - len(candidates),
    )

    # ── 7. AI enrichment ───────────────────────────────────────────────────────
    passed: list = []
    total = len(candidates)
    min_ai_score = float(settings.get("min_score", 7.0))

    for i, product in enumerate(candidates):
        enriched = await ai_enrich(product, settings)
        if enriched:
            ai_score = float(enriched.get("score", 0))
            if ai_score >= min_ai_score:
                product.update(enriched)
                passed.append(product)
            else:
                log.debug(
                    "AI rejected: score=%.1f reason=%s",
                    ai_score, enriched.get("rejection_reason", ""),
                )
        else:
            log.warning("Enrichment returned None for source_id=%s", product.get("source_id", "?"))

        if i % 5 == 0:
            progress = 55 + int((i / max(total, 1)) * 38)
            await db.update_job(job_id, status="ai_review", progress=progress, after_ai=len(passed))

    # ── 8. Save to review queue ────────────────────────────────────────────────
    await db.update_job(job_id, status="saving", progress=95, after_ai=len(passed))

    for product in passed:
        await db.insert_product(product, job_id)

    await db.update_job(job_id, status="done", progress=100, after_ai=len(passed))

    summary = {
        "job_id": job_id,
        "scraped": len(raw_all),
        "after_basic": len(filtered),
        "after_profit": len(profitable),
        "after_dedup": len(deduped),
        "after_score": len(candidates),
        "passed_ai": len(passed),
    }
    log.info("Job %d done: %s", job_id, summary)
    return summary
