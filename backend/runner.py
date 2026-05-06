"""
Pipeline orchestrator.
Stages: scrape → raw store → filter → profit → dedup → rule-score → hand-off to worker
"""

import logging
from typing import Optional

from config.runtime import merge_env_with_settings
from database import db
from filter_engine import basic_filter, dedup, profit_filter
from scorer import score_product
import scraper_cssbuy

log = logging.getLogger(__name__)

# Products scoring below this raw threshold are dropped before AI to save tokens.
_AI_PREFILTER_THRESHOLD = 40


async def run_pipeline(
    job_id: Optional[int] = None,
    keywords: Optional[list] = None,
    max_per_keyword: int = 50,
    settings: Optional[dict] = None,
    source: Optional[str] = None,
) -> dict:
    """
    Full pipeline for one job. Returns summary dict.
    Safe to re-call; insert_product uses INSERT OR IGNORE on source_id.
    """
    if settings is None:
        settings = await db.get_settings()
    settings = merge_env_with_settings(settings)

    if keywords is None:
        from config.runtime import get_config
        raw_kw = get_config("SCAN_KEYWORDS", settings.get("scan_keywords", ["aesthetic home decor"]))
        keywords = raw_kw if isinstance(raw_kw, list) else [raw_kw]
    if not keywords:
        keywords = ["aesthetic home decor"]
    if job_id is None:
        job_id = await db.create_job(keywords=keywords)

    await db.update_job(job_id, status="scraping", progress=5)

    # ── 1. Scrape ──────────────────────────────────────────────────────────────
    from config.runtime import get_config
    cssbuy_user = get_config("CSSBUY_USERNAME", settings.get("cssbuy_username", ""))
    cssbuy_pass = get_config("CSSBUY_PASSWORD", settings.get("cssbuy_password", ""))
    captcha_key = get_config("CAPTCHA_2CAPTCHA_KEY", settings.get("captcha_2captcha_key", ""))
    scan_source = source or str(get_config("CSSBUY_SOURCE", settings.get("cssbuy_source", "1688")))

    if cssbuy_user and cssbuy_pass:
        raw_all = await scraper_cssbuy.scrape(
            keywords, max_per_keyword,
            username=cssbuy_user, password=cssbuy_pass,
            captcha_key=captcha_key, source=scan_source,
        )
    else:
        log.warning("Job %d: no scraper credentials configured", job_id)
        raw_all = []

    log.info("Job %d scraped %d products (source=%s)", job_id, len(raw_all), scan_source)

    return await process_scraped_products(job_id, raw_all, settings)


async def process_scraped_products(job_id: int, raw_all: list, settings: Optional[dict] = None) -> dict:
    """
    Process products that were scraped outside this server.
    """
    if settings is None:
        settings = await db.get_settings()
    settings = merge_env_with_settings(settings)

    # ── 2. Store raw data ──────────────────────────────────────────────────────
    for p in raw_all:
        await db.insert_raw(p, job_id)

    await db.update_job(job_id, status="scraping", progress=20, scraped=len(raw_all))

    # ── 3. Basic filter (spam, orders, rating, images) ─────────────────────────
    filtered = basic_filter(raw_all, settings)
    await db.update_job(job_id, status="filtering", progress=35, after_basic=len(filtered))

    filtered_ids = {p.get("source_id") for p in filtered if p.get("source_id")}
    for p in raw_all:
        if p.get("source_id") not in filtered_ids:
            p["stage"] = "REJECTED"
            p["rejection_reason"] = "Bouncer: spam/no-image/low-orders"
            await db.insert_product(p, job_id)

    # ── 4. Profit filter (adds cost/sell/margin fields) ────────────────────────
    profitable = [p for p in filtered if profit_filter(p, settings)]
    await db.update_job(job_id, status="calculating", progress=50, after_profit=len(profitable))

    profitable_ids = {p.get("source_id") for p in profitable if p.get("source_id")}
    for p in filtered:
        if p.get("source_id") not in profitable_ids:
            p["stage"] = "REJECTED"
            p["rejection_reason"] = f"Bouncer: Low Margin ({p.get('margin_pct', 0)}%)"
            await db.insert_product(p, job_id)

    # ── 5. Dedup by first image ────────────────────────────────────────────────
    deduped = dedup(profitable)
    await db.update_job(job_id, status="deduping", progress=55, after_dedup=len(deduped))

    deduped_ids = {p.get("source_id") for p in deduped if p.get("source_id")}
    for p in profitable:
        if p.get("source_id") not in deduped_ids:
            p["stage"] = "REJECTED"
            p["rejection_reason"] = "Bouncer: Duplicate product"
            await db.insert_product(p, job_id)

    # ── 6. Rule-based scoring + pre-filter ────────────────────────────────────
    scored = [score_product(p) for p in deduped]
    candidates = [p for p in scored if p.get("raw_score", 0) >= _AI_PREFILTER_THRESHOLD]

    log.info(
        "Job %d: %d candidates after rule scoring (dropped %d LOW)",
        job_id, len(candidates), len(scored) - len(candidates),
    )

    candidates_ids = {p.get("source_id") for p in candidates if p.get("source_id")}
    for p in scored:
        if p.get("source_id") not in candidates_ids:
            p["stage"] = "REJECTED"
            p["rejection_reason"] = f"Detective: Low raw score ({p.get('raw_score',0):.0f})"
            await db.insert_product(p, job_id)

    # ── 7. Save surviving candidates as SCRAPED for the Worker to pick up ─────
    await db.update_job(job_id, status="saving", progress=95, after_ai=len(candidates))

    for product in candidates:
        product["stage"] = "SCRAPED"
        await db.insert_product(product, job_id)

    await db.update_job(job_id, status="done", progress=100, after_ai=len(candidates))

    summary = {
        "job_id": job_id,
        "scraped": len(raw_all),
        "after_basic": len(filtered),
        "after_profit": len(profitable),
        "after_dedup": len(deduped),
        "after_score": len(candidates),
    }
    log.info("Job %d done: %s", job_id, summary)
    return summary
