"""
Worker Service (DropOS)
----------------------
Handles the background processing pipeline for products.

"Blast Shield" pattern: the outermost try/except in each loop catches ALL
unexpected exceptions. On failure the loop logs the error, sleeps for
_ERROR_SLEEP seconds, then continues — so a bad product or API outage can
never permanently kill the background process.
"""

import asyncio
import logging
import json
from datetime import datetime, timezone

# ── Absolute imports (backend/ is on sys.path, NOT a package) ─────────────────
from config.runtime import merge_env_with_settings
from database import db
from models import ProductStage          # NOT from main — that causes a circular import
from services.images import process_image
import activity
import autopilot
import content_ai
import decision_memory
import instagram


log = logging.getLogger(__name__)

# How long to pause after an unexpected crash before retrying
_ERROR_SLEEP = 60
# Batch size for Vision AI collage; must match collage.py COLS*ROWS (2A-3 = 6)
_BATCH_SIZE = 6


async def run_worker_loop():
    """
    Continuously processes SCRAPED products in batches of 6.

    Pipeline per batch:
      1. Batch Vision AI via Gemini collage (The Curator)
      2. Deep text enrichment for winners (gpt-4o-mini caption)
      3. Image download + Supabase upload for winners
      4. DB update → ENRICHED  (winners) / REJECTED (losers)
    """
    log.info("Started autonomous worker loop (Batch Vision + Deep Enrichment).")

    while True:
        try:
            # ── Poll for SCRAPED products — one brand per batch, so every
            #    collage is judged with that brand's persona ──────────────────
            head = await db.get_products(stage=ProductStage.SCRAPED.value, limit=1, sort="created")
            if not head:
                await asyncio.sleep(10)
                continue
            batch_brand_id = head[0].get("brand_id")
            products = await db.get_products(
                stage=ProductStage.SCRAPED.value,
                limit=_BATCH_SIZE,
                sort="created",
                brand_id=batch_brand_id,
            ) if batch_brand_id else head

            settings = merge_env_with_settings(await db.get_settings())
            # Brand persona overrides the global store persona in the AI prompt
            if batch_brand_id:
                brand = await db.get_brand(batch_brand_id)
                if brand:
                    settings = {**settings,
                                "store_name": brand.get("name") or settings.get("store_name"),
                                "niche": brand.get("niche") or settings.get("niche"),
                                "target_audience": brand.get("target_audience") or settings.get("target_audience"),
                                "example_products": brand.get("example_products") or settings.get("example_products"),
                                "sell_price_min": brand.get("sell_price_min") or settings.get("sell_price_min"),
                                "sell_price_max": brand.get("sell_price_max") or settings.get("sell_price_max")}
            log.info("Worker: Running Batch Vision AI for %d products (brand=%s)...", len(products), batch_brand_id)

            # ── Decision-memory context injection (feature flag: ai_context_injection) ──
            # When OFF (default): context_snippet=None → Gemini call is byte-for-byte
            # identical to the pre-Phase-2 baseline.
            # When ON: a compact aggregate summary is appended to the system prompt.
            # Built once per batch iteration — one DB read, not one per product.
            flag_on: bool = bool(settings.get("ai_context_injection"))
            context_snippet: str | None = None
            skip_reason: str | None = None   # recorded in enrichment_log

            if flag_on:
                try:
                    summary = await decision_memory.build_summary(db)
                    context_snippet = decision_memory.build_context_snippet(summary)
                    if context_snippet:
                        log.debug("Worker: injecting decision-memory context (%d chars)", len(context_snippet))
                    else:
                        skip_reason = "insufficient_history"
                        log.debug("Worker: ai_context_injection ON but insufficient history — skipping")
                except Exception as exc:
                    skip_reason = "error"
                    # Never let a failed context build block enrichment.
                    log.warning("Worker: decision-memory context build failed (%s) — proceeding without it", exc)
                    context_snippet = None
            else:
                skip_reason = "flag_off"

            # Deferred import avoids circular dependency at module load time
            from enrichment import ai_enrich_batch, ai_configured
            batch_results = await ai_enrich_batch(products, settings, context_snippet)

            # ── AI outage guard ──────────────────────────────────────────────
            # If a real provider is configured but every result came from the
            # mock scorer, the AI is down (quota, network, bad key).  Do NOT
            # decide anything — leave the batch in SCRAPED and retry later.
            providers = {str(r.get("ai_provider") or "") for r in batch_results}
            if ai_configured(settings) and providers == {"mock"}:
                log.warning(
                    "Worker: AI provider configured but unavailable — batch of %d left in SCRAPED, retrying in %ds",
                    len(products), _ERROR_SLEEP,
                )
                await asyncio.sleep(_ERROR_SLEEP)
                continue

            ai_pass: list = []
            ai_reject: list = []

            for i, p in enumerate(products):
                pid = p["id"]
                source_id = p.get("source_id", str(pid))

                # Guard: truncated AI response
                if i >= len(batch_results):
                    log.warning("Worker: Missing AI result for pid=%d, rejecting.", pid)
                    await db.update_product_fields(pid, {
                        "stage": "REJECTED",
                        "rejection_reason": "Curator: No AI result returned",
                    })
                    continue

                res = batch_results[i]
                scores      = res.get("scores") or {}
                verdict     = res.get("verdict", "auto_reject")
                composite_s = float(res.get("composite_score") or res.get("score") or 0)
                provider    = str(res.get("ai_provider") or "")

                # pending_review products (≥6.0) go to review queue, not hard reject
                store_match = bool(res.get("store_match")) or verdict in (
                    "top_priority", "strong_candidate", "pending_review"
                )

                # Canonical per-dimension scores, using the store's vocabulary
                dim_updates = {
                    "score":           composite_s,
                    "composite_score": composite_s,
                    "cute_appeal":     float(scores.get("couple_angle") or res.get("couple_angle") or 0),
                    "niche_fit":       float(scores.get("emotional_trigger") or res.get("emotional_trigger") or res.get("niche_fit") or 0),
                    "visual_appeal":   float(scores.get("visual_score") or res.get("visual_score") or res.get("visual_appeal") or 0),
                    "trend_score":     float(scores.get("trend_alignment") or res.get("trend_alignment") or res.get("trend_score") or 0),
                    "giftability":     float(scores.get("demographic_fit") or res.get("demographic_fit") or 0),
                    "scores_json":     json.dumps({
                        "cute_appeal":      float(scores.get("couple_angle") or 0),
                        "romantic_trigger": float(scores.get("emotional_trigger") or 0),
                        "visual_score":     float(scores.get("visual_score") or 0),
                        "trend_fit":        float(scores.get("trend_alignment") or 0),
                        "giftability":      float(scores.get("demographic_fit") or 0),
                    }),
                    "verdict":         verdict,
                    "product_tier":    res.get("product_tier") or "",
                    "confidence":      float(res.get("confidence") or 0),
                    "viral_angle":     res.get("viral_angle") or "",
                    "emotional_hook":  res.get("emotional_hook") or "",
                    "ai_provider":     provider,
                }

                if not store_match:
                    # ── Hard rejection (auto_reject verdict or composite < 6.0) ─
                    reason = res.get("rejection_reason") or "Score below threshold"
                    await db.update_product_fields(pid, {
                        **dim_updates,
                        "stage":            "REJECTED",
                        "rejection_reason": f"Curator: {reason}",
                    })
                    ai_reject.append({**p, **dim_updates, "rejection_reason": f"Curator: {reason}"})
                    log.info("Worker: [REJECT] pid=%d score=%.2f verdict=%s → %s",
                             pid, composite_s, verdict, str(reason)[:60])
                    await activity.record("auto_rejected", f"AI rejected “{(p.get('title_translated') or p.get('title') or '')[:60]}” — {str(reason)[:80]}",
                                          product_id=pid, meta={"score": composite_s, "verdict": verdict})
                    continue

                # ── Winner: Deep Enrichment + Supabase Image Upload ───────────
                log.info("Worker: [WINNER] pid=%d score=%.2f verdict=%s provider=%s", pid, composite_s, verdict, provider)

                # b. Download + compress + upload to Supabase Storage
                images = p.get("images") or []
                raw_image_url = images[0] if images else p.get("image_url", "")

                try:
                    new_image_url = await process_image(raw_image_url, source_id=source_id)
                    if new_image_url and new_image_url != raw_image_url:
                        log.info("Worker: Image uploaded to Supabase for pid=%d", pid)
                except Exception as e:
                    log.error("Worker: Image pipeline failed for pid=%d: %s — using original URL", pid, e)
                    new_image_url = raw_image_url

                # c. Persist everything in one DB update
                updates = {
                    **dim_updates,
                    "caption":           res.get("caption") or p.get("caption") or "",
                    "hashtags_json":     json.dumps(res.get("hashtags") or p.get("hashtags") or []),
                    "product_name":      res.get("product_name") or p.get("product_name") or "",
                    "audience":          res.get("audience") or "",
                    "has_chinese_text":  1 if res.get("has_chinese_text") else 0,
                    "chinese_text_note": str(res.get("chinese_text_note") or ""),
                    "stage":             ProductStage.ENRICHED.value,
                }

                if new_image_url and images:
                    try:
                        images[0] = new_image_url
                        updates["images_json"] = json.dumps(images)
                    except Exception as e:
                        log.warning("Worker: Failed to update images array for pid=%d: %s", pid, e)

                await db.update_product_fields(pid, updates)
                ai_pass.append({**p, **dim_updates})
                log.info("Worker: pid=%d → ENRICHED.", pid)

                # ── Autopilot: approve winners without a human ───────────────
                name = (res.get("product_name") or p.get("title_translated") or p.get("title") or "")[:60]
                decision = autopilot.approval_decision(res, settings)
                if decision == "approve":
                    if res.get("has_chinese_text"):
                        if autopilot.should_auto_clean(settings):
                            from services.cleaning import clean_product_image
                            fresh = await db.get_product(pid)
                            outcome = await clean_product_image(fresh or p, settings)
                            if outcome.get("ok"):
                                await activity.record("image_cleaned", f"Cleaned Chinese text from “{name}” and approved it", product_id=pid)
                                await activity.record("auto_approved", f"Auto-approved “{name}” (score {composite_s:.1f}, {verdict.replace('_', ' ')})", product_id=pid,
                                                      meta={"score": composite_s, "verdict": verdict})
                            else:
                                await db.set_stage(pid, ProductStage.TEXT_REMOVAL.value)
                                await activity.record("image_clean_failed", f"Could not clean “{name}”: {outcome.get('error')} — waiting in Text edit", product_id=pid, level="warn")
                        else:
                            await db.set_stage(pid, ProductStage.TEXT_REMOVAL.value)
                            await activity.record("needs_review", f"“{name}” approved but its photo has Chinese text — needs cleaning", product_id=pid, level="warn")
                    else:
                        await db.set_stage(pid, ProductStage.REVIEWED.value)
                        await activity.record("auto_approved", f"Auto-approved “{name}” (score {composite_s:.1f}, {verdict.replace('_', ' ')})", product_id=pid,
                                              meta={"score": composite_s, "verdict": verdict})
                else:
                    await activity.record("needs_review", f"“{name}” scored {composite_s:.1f} ({verdict.replace('_', ' ')}) — waiting for your decision", product_id=pid,
                                          meta={"score": composite_s, "verdict": verdict, "provider": provider})

            # ── Scans page breakdown (grouped by originating job) ─────────────
            for stage_name, items in (("ai_pass", ai_pass), ("ai_reject", ai_reject)):
                by_job: dict = {}
                for it in items:
                    by_job.setdefault(it.get("job_id") or 0, []).append(it)
                for job_id, its in by_job.items():
                    await db.record_pipeline_stage(job_id, its, stage_name)

            # ── Observability: log batch metadata for injection comparison ─────
            # Fire-and-forget — a write failure must never block the worker loop.
            try:
                scores = [
                    r["score"] for r in batch_results
                    if isinstance(r.get("score"), (int, float))
                ]
                await db.log_enrichment_batch({
                    "flag_on":          int(flag_on),
                    "snippet_injected": int(bool(context_snippet)),
                    "snippet_length":   len(context_snippet) if context_snippet else 0,
                    "skip_reason":      skip_reason,
                    "batch_size":       len(products),
                    "accepted_count":   len(ai_pass),
                    "rejected_count":   len(ai_reject),
                    "avg_score":        round(sum(scores) / len(scores), 2) if scores else None,
                })
            except Exception as exc:
                log.warning("Worker: enrichment_log write failed (%s) — non-critical", exc)

            # Brief pause before next batch
            await asyncio.sleep(2)

        except asyncio.CancelledError:
            log.info("Autonomous worker loop cancelled.")
            break
        except Exception as e:
            # ── Blast Shield ──────────────────────────────────────────────────
            log.error(
                "Critical Worker Error (will retry in %ds): %s",
                _ERROR_SLEEP, e, exc_info=True,
            )
            await asyncio.sleep(_ERROR_SLEEP)


async def process_queued_items():
    """
    Continuously publishes QUEUED products to Instagram using the same
    settings-driven Graph API client the manual "Post" button uses.
    Polls every 60 s when idle, 5 s when actively draining the queue.
    """
    log.info("Started queued items publisher loop.")

    while True:
        try:
            products = await db.get_products(
                stage=ProductStage.QUEUED.value,
                limit=5,
                sort="created",
            )

            if products:
                settings = merge_env_with_settings(await db.get_settings())
                products = [await content_ai.maybe_rewrite_caption(db, p, settings) for p in products]
                results = await instagram.post_batch(products, settings)
                for p in products:
                    pid = p["id"]
                    name = (p.get("product_name") or p.get("title_translated") or "")[:60]
                    res = next((r for r in results if r.product_id == pid), None)
                    if res and res.status in ("posted", "mock"):
                        await db.update_product_fields(pid, {
                            "stage": ProductStage.LIVE.value,
                            "instagram_url": res.post_url or "",
                            "posted_at": datetime.now(timezone.utc).isoformat(),
                        })
                        await db.log_post(pid)
                        log.info("Publisher: pid=%d → LIVE (%s).", pid, res.post_url)
                        await activity.record("posted", f"Posted “{name}” to Instagram" + (" (simulated — no token)" if res.status == "mock" else ""),
                                              product_id=pid, meta={"url": res.post_url})
                    else:
                        err = (res.error if res else None) or "unknown error"
                        # Put it back in Approved so it is not retried in a tight loop
                        await db.set_stage(pid, ProductStage.REVIEWED.value)
                        await db.update_product_note(pid, f"Auto-post failed: {err}")
                        log.error("Publisher: Failed to publish pid=%d: %s", pid, err)
                        await activity.record("post_failed", f"Instagram post failed for “{name}”: {err}", product_id=pid, level="error")

            await asyncio.sleep(60 if not products else 5)

        except asyncio.CancelledError:
            log.info("Publisher loop cancelled.")
            break
        except Exception as e:
            # ── Blast Shield ──────────────────────────────────────────────────
            log.error(
                "Critical Publisher Error (will retry in %ds): %s",
                _ERROR_SLEEP, e, exc_info=True,
            )
            await asyncio.sleep(_ERROR_SLEEP)
