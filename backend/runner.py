"""
Pipeline orchestrator.
Stages: scrape → raw store → filter → profit → dedup → rule-score → AI enrich → save
"""

import logging
from typing import Optional

import asyncio

from database import db
from enrichment import ai_enrich
from filter_engine import basic_filter, dedup, profit_filter
from scorer import score_product
import scraper_1688
import scraper_taobao
import scraper_cssbuy
import scraper_superbuy

log = logging.getLogger(__name__)

# Products scoring below this raw threshold are dropped before AI to save tokens.
_AI_PREFILTER_THRESHOLD = 40


def _pipeline_rec(job_id: int, product: dict, stage: str, reason: str = "", ai_score: float = 0, ai_niche_fit: float = 0, ai_visual: float = 0) -> dict:
    img = (product.get("images") or [""])[0]
    return {
        "job_id":       job_id,
        "source_id":    product.get("source_id", ""),
        "title":        (product.get("title_translated") or product.get("title", ""))[:120],
        "image_url":    img,
        "price_cny":    float(product.get("price_cny", 0)),
        "orders":       int(product.get("orders", 0)),
        "margin_pct":   float(product.get("margin_pct", 0)),
        "filter_stage": stage,
        "filter_reason": reason,
        "ai_score":     ai_score,
        "ai_niche_fit": ai_niche_fit,
        "ai_visual":    ai_visual,
    }


async def run_pipeline(
    job_id: int,
    keywords: list,
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

    token: Optional[str] = settings.get("apify_token") or None

    await db.update_job(job_id, status="scraping", progress=5)

    # ── 1. Scrape ──────────────────────────────────────────────────────────────
    cssbuy_user = settings.get("cssbuy_username", "")
    cssbuy_pass = settings.get("cssbuy_password", "")
    captcha_key = settings.get("captcha_2captcha_key", "")
    scan_source = source or str(settings.get("cssbuy_source", "1688"))

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

    # ── 2. Store raw data ──────────────────────────────────────────────────────
    for p in raw_all:
        await db.insert_raw(p, job_id)

    await db.update_job(job_id, status="scraping", progress=20, scraped=len(raw_all))

    # ── 3. Basic filter (spam, orders, rating, images) ─────────────────────────
    filtered = basic_filter(raw_all, settings)
    await db.update_job(job_id, status="filtering", progress=35, after_basic=len(filtered))

    filtered_ids = {p.get("source_id") for p in filtered if p.get("source_id")}
    pipeline_recs = [_pipeline_rec(job_id, p, "basic_reject", "spam/no-image/low-orders") for p in raw_all if p.get("source_id") not in filtered_ids]

    # ── 4. Profit filter (adds cost/sell/margin fields) ────────────────────────
    profitable = [p for p in filtered if profit_filter(p, settings)]
    await db.update_job(job_id, status="calculating", progress=50, after_profit=len(profitable))

    profitable_ids = {p.get("source_id") for p in profitable if p.get("source_id")}
    pipeline_recs += [_pipeline_rec(job_id, p, "profit_reject", "margin too low") for p in filtered if p.get("source_id") not in profitable_ids]

    # ── 5. Dedup by first image ────────────────────────────────────────────────
    deduped = dedup(profitable)
    await db.update_job(job_id, status="deduping", progress=55, after_dedup=len(deduped))

    deduped_ids = {p.get("source_id") for p in deduped if p.get("source_id")}
    pipeline_recs += [_pipeline_rec(job_id, p, "dedup_reject", "duplicate product") for p in profitable if p.get("source_id") not in deduped_ids]

    # ── 6. Rule-based scoring + pre-filter ────────────────────────────────────
    scored = [score_product(p) for p in deduped]
    candidates = [p for p in scored if p.get("raw_score", 0) >= _AI_PREFILTER_THRESHOLD]

    log.info(
        "Job %d: %d candidates after rule scoring (dropped %d LOW)",
        job_id, len(candidates), len(scored) - len(candidates),
    )

    candidates_ids = {p.get("source_id") for p in candidates if p.get("source_id")}
    pipeline_recs += [_pipeline_rec(job_id, p, "score_reject", f"raw score {p.get('raw_score',0):.0f} < {_AI_PREFILTER_THRESHOLD}") for p in scored if p.get("source_id") not in candidates_ids]

    # ── 7. AI enrichment ───────────────────────────────────────────────────────
    passed: list = []
    total = len(candidates)
    min_ai_score = float(settings.get("min_score", 7.0))
    if settings.get("gemini_key"):
        scorer_name = "gemini-2.0-flash"
    elif settings.get("groq_key"):
        scorer_name = "groq/llama-3.3-70b"
    elif settings.get("anthropic_key"):
        scorer_name = "claude-haiku-4-5"
    else:
        scorer_name = "mock/rule-based"
    log.info(
        "Job %d: enriching %d candidates (scorer=%s, min_score=%.1f)",
        job_id, total, scorer_name, min_ai_score,
    )

    use_gemini = bool(settings.get("gemini_key"))

    for i, product in enumerate(candidates):
        # Gemini 2.0 Flash: 15 RPM free — 10s gap = 6 RPM, well under limit
        if use_gemini and i > 0:
            await asyncio.sleep(10)

        try:
            enriched = await ai_enrich(product, settings)
        except Exception as exc:
            log.warning("Enrichment exception for source_id=%s: %s", product.get("source_id", "?"), exc)
            enriched = None

        if enriched:
            ai_score = float(enriched.get("score", 0))
            title = (product.get("title_translated") or product.get("title", "?"))[:40]
            if ai_score >= min_ai_score:
                product.update(enriched)
                passed.append(product)
                pipeline_recs.append(_pipeline_rec(job_id, product, "ai_pass", "", ai_score, float(enriched.get("niche_fit", 0)), float(enriched.get("visual_appeal", 0))))
                log.info("  [PASS] %.1f  visual=%.1f  %s", ai_score, float(enriched.get("visual_appeal", 0)), title)
            else:
                pipeline_recs.append(_pipeline_rec(job_id, product, "ai_reject", enriched.get("rejection_reason", ""), ai_score, float(enriched.get("niche_fit", 0)), float(enriched.get("visual_appeal", 0))))
                log.info("  [FAIL] %.1f  %s  (%s)", ai_score, title, enriched.get("rejection_reason", ""))
        else:
            log.warning("Enrichment returned None for source_id=%s", product.get("source_id", "?"))

        if i % 5 == 0:
            progress = 55 + int((i / max(total, 1)) * 38)
            await db.update_job(job_id, status="ai_review", progress=progress, after_ai=len(passed))

    # ── 8. Save to review queue ────────────────────────────────────────────────
    await db.update_job(job_id, status="saving", progress=95, after_ai=len(passed))

    for product in passed:
        await db.insert_product(product, job_id)

    try:
        await db.bulk_insert_pipeline(pipeline_recs)
    except Exception as exc:
        log.warning("Job %d: pipeline records save failed: %s", job_id, exc)

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
