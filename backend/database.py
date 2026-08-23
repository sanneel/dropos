import asyncio
import asyncpg
import json
import logging
import os
import sys

from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

class Database:
    def __init__(self):
        # Use a pool instead of a single connection so concurrent coroutines
        # (API handlers, worker loop, publisher loop) can each acquire their
        # own connection and never block each other.
        self._pool: Optional[asyncpg.Pool] = None
        self.embedded: bool = False  # True when running the bundled pgserver cluster

    # ── Thin helpers so all query sites stay identical ─────────────────────────

    async def execute(self, query: str, *args):
        async with self._pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args):
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def truncate_product_data(self):
        """DANGER: Erases all products, raw items, jobs, and logs."""
        tables = ["products", "products_raw", "pipeline_products", "jobs", "post_log"]
        for table in tables:
            await self.execute(f"TRUNCATE TABLE {table} CASCADE;")
        log.warning("Database: ALL PRODUCT DATA TRUNCATED.")

    async def connect(self):
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            db_url = await asyncio.to_thread(_start_embedded_postgres)
            if not db_url:
                log.critical(
                    "FATAL: no database. Either set DATABASE_URL (any PostgreSQL, e.g. the "
                    "Supabase SESSION POOLER string) or install the embedded database with "
                    "`pip install pgserver` — DropOS then runs a local Postgres in ./data/pg."
                )
                sys.exit(1)
            os.environ["DATABASE_URL"] = db_url
            self.embedded = True

        # SSL: hosted Postgres (Supabase/Railway) needs it; a local dev DB usually
        # has no TLS at all.  DATABASE_SSL=require|disable overrides auto-detect.
        ssl_mode = (os.getenv("DATABASE_SSL") or "").strip().lower()
        if ssl_mode in ("disable", "off", "false", "0"):
            ssl = False
        elif ssl_mode in ("require", "on", "true", "1"):
            ssl = "require"
        else:
            host = ""
            try:
                from urllib.parse import urlparse
                host = (urlparse(db_url).hostname or "").lower()
            except Exception:
                pass
            ssl = False if host in ("localhost", "127.0.0.1", "::1", "postgres", "db") else "require"

        last_exc = None
        for attempt in range(3):
            try:
                self._pool = await asyncpg.create_pool(
                    db_url,
                    ssl=ssl,
                    statement_cache_size=0,  # Required for PgBouncer/Supabase pooler
                    min_size=1,              # 1 warm connection — faster cold start
                    max_size=10,             # Allow up to 10 concurrent queries
                    command_timeout=30,      # Fail fast instead of hanging 60s+
                )
                log.info("Database pool created successfully (min=1, max=10, ssl=%s).", ssl)
                return
            except Exception as e:
                last_exc = e
                log.warning("DB pool attempt %d/3 failed: %s", attempt + 1, e)
                await asyncio.sleep(3 * (attempt + 1))

        log.critical(
            "Could not connect to the database after 3 attempts.\n"
            "Error: %s\n"
            "Check that DATABASE_URL uses the Supabase SESSION POOLER URL\n"
            "(Settings → Database → Connection pooling → Session mode, port 5432)",
            last_exc,
        )
        sys.exit(1)

    async def close(self):
        if self._pool:
            await self._pool.close()


    # ── Products ──────────────────────────────────────────────────────────────

    async def insert_product(self, p: dict, job_id: int):
        now = _now()
        await self.execute("""
            INSERT INTO products
            (job_id, source, source_id, title, title_translated, product_name,
             price_cny, cost_eur, sell_price_eur, margin_pct, orders, rating,
             images_json, url, category, keyword,
             score, niche_fit, visual_appeal, trend_score, competition_score,
             caption, description, hashtags_json, ai_provider, has_chinese_text,
             chinese_text_note, rejection_reason, stage, created_at, rejected_at, brand_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32)
            ON CONFLICT (source_id) DO NOTHING
        """,
            job_id,
            p.get("source", ""),
            p.get("source_id", ""),
            p.get("title", ""),
            p.get("title_translated", ""),
            p.get("product_name", ""),
            float(p.get("price_cny") or 0),
            float(p.get("cost_eur") or 0),
            float(p.get("sell_price_eur") or 0),
            float(p.get("margin_pct") or 0),
            int(p.get("orders") or 0),
            float(p.get("rating") or 0),
            json.dumps(p.get("images", [])),
            p.get("url", ""),
            p.get("category", ""),
            p.get("keyword", ""),
            float(p.get("score") or 0),
            float(p.get("niche_fit") or 0),
            float(p.get("visual_appeal") or 0),
            float(p.get("trend_score") or 0),
            float(p.get("competition_score") or 0),
            p.get("caption", ""),
            p.get("description", ""),
            json.dumps(p.get("hashtags", [])),
            p.get("ai_provider", ""),
            1 if p.get("has_chinese_text") else 0,
            p.get("chinese_text_note", ""),
            p.get("rejection_reason", ""),
            p.get("stage", "SCRAPED"),
            now,
            now if p.get("stage") == "REJECTED" else None,
            p.get("brand_id"),
        )

    async def get_products(self, stage: str = "SCRAPED", limit: int = 50, offset: int = 0, sort: str = "score", q: str = "", brand_id: int | None = None) -> list:
        sort_map = {
            "score": "score DESC",
            "margin": "margin_pct DESC",
            "orders": "orders DESC",
            "created": "created_at DESC",
        }
        order = sort_map.get(sort, "score DESC")
        where, args = "stage=$1", [stage]
        if brand_id:
            args.append(brand_id)
            where += f" AND brand_id=${len(args)}"
        if q:
            args.append(f"%{q.strip()}%")
            where += (f" AND (product_name ILIKE ${len(args)} OR title_translated ILIKE ${len(args)}"
                      f" OR title ILIKE ${len(args)} OR category ILIKE ${len(args)} OR caption ILIKE ${len(args)}"
                      f" OR keyword ILIKE ${len(args)})")
        args += [limit, offset]
        rows = await self.fetch(
            f"SELECT * FROM products WHERE {where} ORDER BY {order} LIMIT ${len(args)-1} OFFSET ${len(args)}",
            *args
        )
        return [_row_to_product(r) for r in rows]

    async def get_all_products(self, limit: int = 5000) -> list:
        rows = await self.fetch("SELECT * FROM products ORDER BY id DESC LIMIT $1", limit)
        return [_row_to_product(r) for r in rows]

    async def count_products(self, stage: str = "SCRAPED", q: str = "", brand_id: int | None = None) -> int:
        if brand_id:
            if q:
                like = f"%{q.strip()}%"
                val = await self.fetchval("""
                    SELECT COUNT(*) FROM products WHERE stage=$1 AND brand_id=$3 AND (
                        product_name ILIKE $2 OR title_translated ILIKE $2 OR title ILIKE $2
                        OR category ILIKE $2 OR caption ILIKE $2 OR keyword ILIKE $2)
                """, stage, like, brand_id)
            else:
                val = await self.fetchval("SELECT COUNT(*) FROM products WHERE stage=$1 AND brand_id=$2", stage, brand_id)
            return val if val else 0
        if q:
            like = f"%{q.strip()}%"
            val = await self.fetchval("""
                SELECT COUNT(*) FROM products WHERE stage=$1 AND (
                    product_name ILIKE $2 OR title_translated ILIKE $2 OR title ILIKE $2
                    OR category ILIKE $2 OR caption ILIKE $2 OR keyword ILIKE $2)
            """, stage, like)
        else:
            val = await self.fetchval("SELECT COUNT(*) FROM products WHERE stage=$1", stage)
        return val if val else 0

    async def get_product(self, pid: int) -> Optional[dict]:
        row = await self.fetchrow("SELECT * FROM products WHERE id=$1", pid)
        return _row_to_product(row) if row else None

    async def upsert_product_backup(self, p: dict) -> None:
        source_id = str(p.get("source_id") or "").strip()
        if not source_id:
            return
        await self.execute("""
            INSERT INTO products
            (job_id, source, source_id, title, title_translated, product_name,
             price_cny, cost_eur, sell_price_eur, margin_pct, orders, rating,
             images_json, url, category, keyword,
             score, niche_fit, visual_appeal, trend_score, competition_score,
             caption, description, hashtags_json, ai_provider, has_chinese_text, chinese_text_note,
             stage, rejection_reason, review_note,
             approved_at, rejected_at, posted_at, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32,$33,$34)
            ON CONFLICT (source_id) DO UPDATE SET
             job_id=EXCLUDED.job_id,
             source=EXCLUDED.source,
             title=EXCLUDED.title,
             title_translated=EXCLUDED.title_translated,
             product_name=EXCLUDED.product_name,
             price_cny=EXCLUDED.price_cny,
             cost_eur=EXCLUDED.cost_eur,
             sell_price_eur=EXCLUDED.sell_price_eur,
             margin_pct=EXCLUDED.margin_pct,
             orders=EXCLUDED.orders,
             rating=EXCLUDED.rating,
             images_json=EXCLUDED.images_json,
             url=EXCLUDED.url,
             category=EXCLUDED.category,
             keyword=EXCLUDED.keyword,
             score=EXCLUDED.score,
             niche_fit=EXCLUDED.niche_fit,
             visual_appeal=EXCLUDED.visual_appeal,
             trend_score=EXCLUDED.trend_score,
             competition_score=EXCLUDED.competition_score,
             caption=EXCLUDED.caption,
             description=EXCLUDED.description,
             hashtags_json=EXCLUDED.hashtags_json,
             ai_provider=EXCLUDED.ai_provider,
             has_chinese_text=EXCLUDED.has_chinese_text,
             chinese_text_note=EXCLUDED.chinese_text_note,
             stage=CASE
               WHEN products.stage IN ('ENRICHED','EXCEPTION','REVIEWED','QUEUED','LIVE') THEN products.stage
               ELSE EXCLUDED.stage
             END,
             rejection_reason=CASE
               WHEN products.stage IN ('ENRICHED','EXCEPTION','REVIEWED','QUEUED','LIVE') THEN products.rejection_reason
               ELSE EXCLUDED.rejection_reason
             END,
             review_note=CASE
               WHEN products.stage IN ('ENRICHED','EXCEPTION','REVIEWED','QUEUED','LIVE') THEN products.review_note
               ELSE EXCLUDED.review_note
             END,
             approved_at=CASE
               WHEN products.stage IN ('ENRICHED','EXCEPTION','REVIEWED','QUEUED','LIVE') THEN products.approved_at
               ELSE EXCLUDED.approved_at
             END,
             rejected_at=CASE
               WHEN products.stage IN ('ENRICHED','EXCEPTION','REVIEWED','QUEUED','LIVE') THEN products.rejected_at
               ELSE EXCLUDED.rejected_at
             END,
             posted_at=CASE
               WHEN products.stage IN ('ENRICHED','EXCEPTION','REVIEWED','QUEUED','LIVE') THEN products.posted_at
               ELSE EXCLUDED.posted_at
             END
        """,
            int(p.get("job_id") or 0),
            p.get("source", ""),
            source_id,
            p.get("title", ""),
            p.get("title_translated", ""),
            p.get("product_name", ""),
            float(p.get("price_cny") or 0),
            float(p.get("cost_eur") or 0),
            float(p.get("sell_price_eur") or 0),
            float(p.get("margin_pct") or 0),
            int(p.get("orders") or 0),
            float(p.get("rating") or 0),
            json.dumps(p.get("images", [])),
            p.get("url", ""),
            p.get("category", ""),
            p.get("keyword", ""),
            float(p.get("score") or 0),
            float(p.get("niche_fit") or 0),
            float(p.get("visual_appeal") or 0),
            float(p.get("trend_score") or 0),
            float(p.get("competition_score") or 0),
            p.get("caption", ""),
            p.get("description", ""),
            json.dumps(p.get("hashtags", [])),
            p.get("ai_provider", ""),
            1 if p.get("has_chinese_text") else 0,
            p.get("chinese_text_note", ""),
            p.get("stage", "SCRAPED"),
            p.get("rejection_reason"),
            p.get("review_note"),
            p.get("approved_at"),
            p.get("rejected_at"),
            p.get("posted_at"),
            p.get("created_at") or _now()
        )

    async def upsert_product_backups(self, products: list) -> int:
        count = 0
        for product in products or []:
            before = count
            await self.upsert_product_backup(product)
            if product.get("source_id") and count == before:
                count += 1
        return count

    async def set_stage(self, pid: int, stage: str, reason: str = None, note: str = None):
        ts_field = {
            "REVIEWED": "approved_at",
            "TEXT_REMOVAL": "approved_at",   # approved, just needs image cleanup first
            "REJECTED": "rejected_at",
            "LIVE": "posted_at",
        }.get(stage)

        updates: dict = {"stage": stage}
        if ts_field:
            updates[ts_field] = _now()
        if reason is not None:
            updates["rejection_reason"] = reason
        if note is not None:
            updates["review_note"] = note

        sets = ", ".join(f"{k}=${i+1}" for i, k in enumerate(updates))
        vals = list(updates.values()) + [pid]
        await self.execute(f"UPDATE products SET {sets} WHERE id=${len(vals)}", *vals)

    async def update_product_note(self, pid: int, note: str):
        await self.execute("UPDATE products SET review_note=$1 WHERE id=$2", note, pid)

    async def update_product_fields(self, pid: int, data: dict) -> Optional[dict]:
        allowed = {
            "product_name",
            "title_translated",
            "description",
            "sell_price_eur",
            "caption",
            "hashtags_json",
            "images_json",
            "category",
            "url",
            "has_chinese_text",
            "chinese_text_note",
            "stage",
            "rejection_reason",
            "audience",
            "instagram_url",
            # scoring fields — previously missing, causing silent zero-writes
            "score",
            "niche_fit",
            "visual_appeal",
            "trend_score",
            "composite_score",
            "verdict",
            "product_tier",
            "confidence",
            "viral_angle",
            "emotional_hook",
            "cute_appeal",
            "giftability",
            "scores_json",
            "posted_at",
            "ai_provider",
        }
        updates = {k: v for k, v in (data or {}).items() if k in allowed}
        if "sell_price_eur" in updates:
            product = await self.get_product(pid)
            cost = float(product.get("cost_eur") or 0) if product else 0
            sell = float(updates["sell_price_eur"] or 0)
            if sell > 0 and cost > 0:
                updates["margin_pct"] = round(((sell - cost) / sell) * 100, 1)
        if not updates:
            return await self.get_product(pid)
        sets = ", ".join(f"{k}=${i+1}" for i, k in enumerate(updates))
        vals = list(updates.values()) + [pid]
        await self.execute(f"UPDATE products SET {sets} WHERE id=${len(vals)}", *vals)
        return await self.get_product(pid)

    async def log_post(self, pid: int):
        await self.execute(
            "INSERT INTO post_log (product_id, posted_at) VALUES ($1,$2)", pid, _now()
        )

    async def bulk_insert_pipeline(self, records: list) -> None:
        for r in records:
            await self.execute("""
                INSERT INTO pipeline_products
                (job_id, source_id, title, product_name, image_url, url, price_cny,
                 cost_eur, sell_price_eur, orders, rating, margin_pct, raw_score,
                 filter_stage, filter_reason, ai_score, ai_niche_fit, ai_visual,
                 trend_score, competition_score, ai_provider, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22)
            """,
                int(r["job_id"]), str(r["source_id"]), str(r["title"]), str(r.get("product_name", "")),
                str(r["image_url"]), str(r.get("url", "")), float(r["price_cny"]),
                float(r.get("cost_eur", 0)), float(r.get("sell_price_eur", 0)),
                int(r["orders"]), float(r.get("rating", 0)), float(r["margin_pct"]), float(r.get("raw_score", 0)),
                str(r["filter_stage"]), str(r.get("filter_reason", "")),
                float(r.get("ai_score", 0)), float(r.get("ai_niche_fit", 0)), float(r.get("ai_visual", 0)),
                float(r.get("trend_score", 0)), float(r.get("competition_score", 0)),
                str(r.get("ai_provider", "")),
                _now()
            )

    async def record_pipeline_stage(self, job_id: int, products: list, stage: str, reason_key: str = "rejection_reason") -> None:
        """
        Persist a snapshot of *products* at a given filter stage so the Scans page
        can show where each item dropped out.  Never raises — the breakdown is
        observability, not a dependency of the pipeline.
        """
        if not job_id or not products:
            return
        records = []
        for p in products:
            images = p.get("images") or []
            records.append({
                "job_id": job_id,
                "source_id": p.get("source_id", ""),
                "title": (p.get("title_translated") or p.get("title") or "")[:200],
                "product_name": (p.get("product_name") or "")[:200],
                "image_url": images[0] if images else (p.get("image_url") or ""),
                "url": p.get("url", ""),
                "price_cny": p.get("price_cny") or 0,
                "cost_eur": p.get("cost_eur") or 0,
                "sell_price_eur": p.get("sell_price_eur") or 0,
                "orders": p.get("orders") or 0,
                "rating": p.get("rating") or 0,
                "margin_pct": p.get("margin_pct") or 0,
                "raw_score": p.get("raw_score") or 0,
                "filter_stage": stage,
                "filter_reason": (p.get(reason_key) or p.get("_bouncer_reason") or "")[:300],
                "ai_score": p.get("composite_score") or p.get("score") or 0,
                "ai_niche_fit": p.get("niche_fit") or 0,
                "ai_visual": p.get("visual_appeal") or 0,
                "trend_score": p.get("trend_score") or 0,
                "competition_score": 0,
                "ai_provider": p.get("ai_provider") or "",
            })
        try:
            await self.bulk_insert_pipeline(records)
        except Exception as exc:
            log.warning("record_pipeline_stage(%s) failed: %s", stage, exc)

    async def get_pipeline(self, job_id: int) -> dict:
        rows = await self.fetch("SELECT * FROM pipeline_products WHERE job_id=$1 ORDER BY filter_stage, id", job_id)
        stages = {}
        for row in rows:
            d = dict(row)
            s = d["filter_stage"]
            if s not in stages:
                stages[s] = []
            stages[s].append(d)
        return stages

    # ── Raw products ───────────────────────────────────────────────────────────

    async def insert_raw(self, p: dict, job_id: int) -> None:
        images = p.get("images") or []
        await self.execute("""
            INSERT INTO products_raw
            (job_id, source, source_id, product_name, price, image_url, merchant, raw_data, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (job_id, source_id) DO NOTHING
        """,
            int(job_id),
            str(p.get("source", "")),
            str(p.get("source_id", "")),
            str(p.get("title_translated") or p.get("title", "")),
            float(p.get("price_cny", 0)),
            images[0] if images else "",
            str(p.get("merchant", "")),
            json.dumps(p),
            _now()
        )

    async def count_raw(self, job_id: int) -> int:
        val = await self.fetchval("SELECT COUNT(*) FROM products_raw WHERE job_id=$1", job_id)
        return val if val else 0

    async def get_raw_products(self, job_id: int, limit: int = 2000) -> list:
        rows = await self.fetch("SELECT * FROM products_raw WHERE job_id=$1 ORDER BY id LIMIT $2", job_id, limit)
        products = []
        for row in rows:
            d = dict(row)
            try:
                raw = json.loads(d.get("raw_data") or "{}")
            except Exception:
                raw = {}
            products.append({
                "id": d.get("id"),
                "job_id": d.get("job_id"),
                "source": d.get("source", ""),
                "source_id": d.get("source_id", ""),
                "title": d.get("product_name", ""),
                "product_name": raw.get("product_name", "") or d.get("product_name", ""),
                "image_url": d.get("image_url", ""),
                "photo_link": d.get("image_url", ""),
                "price_cny": d.get("price", 0),
                "cost_eur": raw.get("cost_eur", 0),
                "sell_price_eur": raw.get("sell_price_eur", 0),
                "orders": raw.get("orders", 0),
                "rating": raw.get("rating", 0),
                "margin_pct": raw.get("margin_pct", 0),
                "raw_score": raw.get("raw_score", 0),
                "score": 0,
                "niche_fit": 0,
                "visual_appeal": 0,
                "trend_score": 0,
                "competition_score": 0,
                "filter_stage": "raw_fetch",
                "filter_reason": "",
                "ai_score": 0,
                "ai_niche_fit": 0,
                "ai_visual": 0,
                "ai_provider": "",
                "url": raw.get("url", ""),
                "link": raw.get("url", ""),
                "category": raw.get("category", ""),
                "keyword": raw.get("keyword", ""),
                "merchant": d.get("merchant", ""),
                "raw_data": raw,
                "created_at": d.get("created_at", ""),
            })
        return products

    async def get_scan_items(self, job_id: int, limit: int = 2000) -> list:
        raw_items = await self.get_raw_products(job_id, limit=limit)
        rows = await self.fetch("SELECT * FROM pipeline_products WHERE job_id=$1 ORDER BY id", job_id)
        pipeline = [dict(row) for row in rows]

        merged = []
        by_source_id = {}
        by_title = {}
        seen = set()
        for item in raw_items:
            key = item.get("source_id") or f"raw:{item.get('id')}"
            seen.add(key)
            row = dict(item)
            merged.append(row)
            if row.get("source_id"):
                by_source_id[str(row.get("source_id"))] = row
            if row.get("title"):
                by_title[str(row.get("title"))] = row

        for rec in pipeline:
            key = rec.get("source_id") or f"pipeline:{rec.get('id')}"
            item = by_source_id.get(str(rec.get("source_id") or "")) or by_title.get(str(rec.get("title") or ""))
            if item:
                item.update({
                    "filter_stage": rec.get("filter_stage", ""),
                    "filter_reason": rec.get("filter_reason", ""),
                    "ai_score": rec.get("ai_score", 0),
                    "ai_niche_fit": rec.get("ai_niche_fit", 0),
                    "ai_visual": rec.get("ai_visual", 0),
                    "score": rec.get("ai_score", 0),
                    "niche_fit": rec.get("ai_niche_fit", 0),
                    "visual_appeal": rec.get("ai_visual", 0),
                    "trend_score": rec.get("trend_score", 0),
                    "competition_score": rec.get("competition_score", 0),
                    "raw_score": rec.get("raw_score", item.get("raw_score", 0)),
                    "ai_provider": rec.get("ai_provider", ""),
                })
                continue
            if key in seen:
                continue
            seen.add(key)
            merged.append({
                **rec,
                "product_name": rec.get("product_name") or rec.get("title", ""),
                "photo_link": rec.get("image_url", ""),
                "link": rec.get("url", ""),
                "score": rec.get("ai_score", 0),
                "niche_fit": rec.get("ai_niche_fit", 0),
                "visual_appeal": rec.get("ai_visual", 0),
            })

        stage_rank = {
            "raw_fetch": 0,
            "basic_reject": 1,
            "profit_reject": 2,
            "dedup_reject": 3,
            "score_reject": 4,
            "ai_reject": 5,
            "ai_pass": 6,
        }
        return sorted(
            merged,
            key=lambda item: (stage_rank.get(item.get("filter_stage", "raw_fetch"), 0), item.get("id") or 0),
        )[:limit]

    # ── Jobs ──────────────────────────────────────────────────────────────────

    async def create_job(self, keywords: list, brand_id: int | None = None) -> int:
        job_id = await self.fetchval("""
            INSERT INTO jobs (keywords_json, status, progress, scraped,
               after_basic, after_profit, after_dedup, after_ai, created_at, brand_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            RETURNING id
        """, json.dumps(keywords), "queued", 0, 0, 0, 0, 0, 0, _now(), brand_id)
        return job_id

    async def update_job(self, job_id: int, **kwargs):
        sets = ", ".join(f"{k}=${i+1}" for i, k in enumerate(kwargs))
        vals = list(kwargs.values()) + [job_id]
        await self.execute(f"UPDATE jobs SET {sets} WHERE id=${len(vals)}", *vals)

    async def get_job(self, job_id: int) -> Optional[dict]:
        row = await self.fetchrow("SELECT * FROM jobs WHERE id=$1", job_id)
        return _row_to_job(row) if row else None

    async def get_jobs(self, limit: int = 10) -> list:
        rows = await self.fetch("SELECT * FROM jobs ORDER BY id DESC LIMIT $1", limit)
        return [_row_to_job(r) for r in rows]

    async def get_active_job(self) -> Optional[dict]:
        active_statuses = (
            "queued",
            "scraping",
            "filtering",
            "calculating",
            "deduping",
            "ai_review",
            "saving",
        )
        placeholders = ",".join(f"${i+1}" for i in range(len(active_statuses)))
        row = await self.fetchrow(
            f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY id DESC LIMIT 1",
            *active_statuses
        )
        return _row_to_job(row) if row else None

    async def mark_active_jobs_interrupted(self) -> int:
        active_statuses = (
            "queued",
            "scraping",
            "filtering",
            "calculating",
            "deduping",
            "ai_review",
            "saving",
        )
        placeholders = ",".join(f"${i+1}" for i in range(len(active_statuses)))
        status = await self.execute(
            f"UPDATE jobs SET status='interrupted' WHERE status IN ({placeholders})",
            *active_statuses
        )
        try:
            return int(status.split()[1])
        except Exception:
            return 0

    async def clear_scan_history(self) -> dict:
        counts = {}
        for table in ("pipeline_products", "products_raw", "jobs"):
            val = await self.fetchval(f"SELECT COUNT(*) FROM {table}")
            counts[table] = val if val else 0
            await self.execute(f"DELETE FROM {table}")
        return counts

    # ── Settings ──────────────────────────────────────────────────────────────

    async def get_settings(self) -> dict:
        rows = await self.fetch("SELECT key, value FROM settings")
        result = {}
        for row in rows:
            k, v = row[0], row[1]
            try:
                result[k] = json.loads(v)
            except Exception:
                result[k] = v
        return result

    async def update_settings(self, data: dict):
        for k, v in data.items():
            val = json.dumps(v) if not isinstance(v, str) else v
            await self.execute("""
                INSERT INTO settings (key, value) VALUES ($1,$2)
                ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value
            """, k, val)

    # ── Comment reply log ─────────────────────────────────────────────────────

    async def has_replied_to_comment(self, comment_id: str) -> bool:
        val = await self.fetchval("SELECT id FROM comment_reply_log WHERE comment_id=$1", comment_id)
        return val is not None

    async def log_comment_reply(self, comment_id: str, matched_rule: str, reply_type: str = "comment") -> None:
        await self.execute("""
            INSERT INTO comment_reply_log (comment_id, reply_type, replied_at, matched_rule)
            VALUES ($1,$2,$3,$4)
            ON CONFLICT (comment_id) DO NOTHING
        """, comment_id, reply_type, _now(), matched_rule)

    async def get_comment_reply_log(self, limit: int = 50) -> list:
        rows = await self.fetch("SELECT * FROM comment_reply_log ORDER BY id DESC LIMIT $1", limit)
        return [dict(r) for r in rows]

    # ── Stats ─────────────────────────────────────────────────────────────────

    async def get_analytics(self) -> dict:
        stages_raw = await self.fetch("SELECT stage, COUNT(*) as cnt FROM products GROUP BY stage")
        
        score_dist = await self.fetch("""
            SELECT
                CASE
                    WHEN score >= 9 THEN '9-10'
                    WHEN score >= 8 THEN '8-9'
                    WHEN score >= 7 THEN '7-8'
                    WHEN score >= 6 THEN '6-7'
                    ELSE 'under 6'
                END as bucket,
                COUNT(*) as cnt
            FROM products WHERE score IS NOT NULL
            GROUP BY bucket ORDER BY bucket DESC
        """)

        categories = await self.fetch("""
            SELECT category, COUNT(*) as cnt FROM products
            WHERE category IS NOT NULL AND category != ''
            GROUP BY category ORDER BY cnt DESC LIMIT 10
        """)

        rejections = await self.fetch("""
            SELECT rejection_reason, COUNT(*) as cnt FROM products
            WHERE stage = 'REJECTED' AND rejection_reason IS NOT NULL AND rejection_reason != ''
            GROUP BY rejection_reason ORDER BY cnt DESC LIMIT 8
        """)

        timeline = await self.fetch("""
            SELECT DATE(created_at) as day,
                   SUM(CASE WHEN stage IN ('REVIEWED','LIVE') THEN 1 ELSE 0 END) as approved,
                   SUM(CASE WHEN stage = 'REJECTED' THEN 1 ELSE 0 END) as rejected,
                   COUNT(*) as total
            FROM products
            WHERE created_at::timestamp >= NOW() - INTERVAL '30 days'
            GROUP BY day ORDER BY day
        """)

        keywords = await self.fetch("""
            SELECT keyword,
                   COUNT(*) as total,
                   SUM(CASE WHEN stage IN ('REVIEWED','LIVE') THEN 1 ELSE 0 END) as approved,
                   ROUND(AVG(score)::numeric, 1) as avg_score
            FROM products
            WHERE keyword IS NOT NULL AND keyword != ''
            GROUP BY keyword ORDER BY approved DESC, total DESC LIMIT 10
        """)

        providers = await self.fetch("""
            SELECT ai_provider, COUNT(*) as cnt FROM products
            WHERE ai_provider IS NOT NULL AND ai_provider != ''
            GROUP BY ai_provider ORDER BY cnt DESC
        """)

        return {
            "stages":            [{"stage": r[0], "cnt": r[1]} for r in stages_raw],
            "score_distribution":[{"bucket": r[0], "cnt": r[1]} for r in score_dist],
            "categories":        [{"category": r[0], "cnt": r[1]} for r in categories],
            "top_rejections":    [{"reason": r[0], "cnt": r[1]} for r in rejections],
            "timeline":          [{"day": str(r[0]), "approved": r[1], "rejected": r[2], "total": r[3]} for r in timeline],
            "keywords":          [{"keyword": r[0], "total": r[1], "approved": r[2], "avg_score": r[3]} for r in keywords],
            "ai_providers":      [{"provider": r[0], "cnt": r[1]} for r in providers],
        }

    async def get_rejected_sample(self, limit: int = 30) -> list:
        rows = await self.fetch("""
            SELECT id, title_translated, category, score, niche_fit, visual_appeal,
                   rejection_reason, keyword, orders, margin_pct
            FROM products
            WHERE stage = 'REJECTED'
            ORDER BY score DESC NULLS LAST
            LIMIT $1
        """, limit)
        return [
            {
                "id": r[0],
                "title": (r[1] or "")[:60],
                "category": r[2],
                "score": r[3],
                "niche_fit": r[4],
                "visual_appeal": r[5],
                "rejection_reason": r[6],
                "keyword": r[7],
                "orders": r[8],
                "margin_pct": r[9],
            }
            for r in rows
        ]

    async def get_products_compact(self, stage: str, limit: int = 25) -> list:
        """Compact product rows for AI context — fewer fields to reduce token usage."""
        rows = await self.fetch("""
            SELECT id, title_translated, product_name, category,
                   score, niche_fit, visual_appeal,
                   composite_score, verdict, product_tier, confidence,
                   keyword, sell_price_eur, margin_pct, orders,
                   rejection_reason, stage, images_json
            FROM products WHERE stage=$1 ORDER BY composite_score DESC NULLS LAST LIMIT $2
        """, stage, limit)
        result = []
        for r in rows:
            try:
                images = json.loads(r["images_json"] or "[]")
            except Exception:
                images = []
            result.append({
                "id": r["id"],
                "title_translated": (r["title_translated"] or r["product_name"] or "")[:60],
                "product_name": (r["product_name"] or "")[:60],
                "category": r["category"],
                "score": float(r["score"] or 0),
                "niche_fit": float(r["niche_fit"] or 0),
                "visual_appeal": float(r["visual_appeal"] or 0),
                "composite_score": float(r["composite_score"] or 0),
                "verdict": r["verdict"] or "",
                "product_tier": r["product_tier"] or "",
                "confidence": float(r["confidence"] or 0),
                "keyword": r["keyword"],
                "sell_price_eur": float(r["sell_price_eur"] or 0),
                "margin_pct": float(r["margin_pct"] or 0),
                "orders": r["orders"],
                "rejection_reason": r["rejection_reason"],
                "stage": r["stage"],
                "image_url": images[0] if images else "",
            })
        return result

    async def get_stats(self) -> dict:
        stats: dict = {}
        for stage in ("SCRAPED", "ENRICHED", "EXCEPTION", "TEXT_REMOVAL", "REVIEWED", "LIVE", "REJECTED"):
            val = await self.fetchval("SELECT COUNT(*) FROM products WHERE stage=$1", stage)
            stats[stage] = val if val else 0

        val = await self.fetchval("SELECT COUNT(*) FROM jobs")
        stats["total_jobs"] = val if val else 0

        val = await self.fetchval("SELECT COUNT(*) FROM post_log WHERE posted_at::timestamp > (NOW() - INTERVAL '7 days')")
        stats["posted_7d"] = val if val else 0

        # "pending" = the human review queue (ENRICHED), not the pre-AI SCRAPED stage
        val = await self.fetchval("SELECT AVG(margin_pct) FROM products WHERE stage='ENRICHED'")
        stats["avg_margin_pending"] = round(float(val or 0), 1)

        val = await self.fetchval("SELECT AVG(score) FROM products WHERE stage='ENRICHED'")
        stats["avg_score_pending"] = round(float(val or 0), 1)

        # Human approval rate: approved vs. rejected-by-a-person (automatic
        # Bouncer/Detective/Curator rejections are excluded so the number
        # reflects review decisions, not filter strictness).
        approved = stats["REVIEWED"] + stats["TEXT_REMOVAL"] + stats["LIVE"]
        human_rejected = await self.fetchval("""
            SELECT COUNT(*) FROM products
            WHERE stage='REJECTED'
              AND COALESCE(rejection_reason,'') NOT LIKE 'Bouncer:%'
              AND COALESCE(rejection_reason,'') NOT LIKE 'Detective:%'
              AND COALESCE(rejection_reason,'') NOT LIKE 'Curator:%'
              AND COALESCE(rejection_reason,'') NOT LIKE 'hard_reject%'
        """) or 0
        stats["human_rejected"] = human_rejected
        decided = approved + human_rejected
        stats["approval_rate"] = round(approved / decided * 100, 1) if decided else 0

        return stats

    # ── Brands (markets) ──────────────────────────────────────────────────────

    async def list_brands(self) -> list:
        rows = await self.fetch("SELECT * FROM brands ORDER BY id")
        return [dict(r) for r in rows]

    async def get_brand(self, brand_id: int):
        row = await self.fetchrow("SELECT * FROM brands WHERE id=$1", brand_id)
        return dict(row) if row else None

    async def default_brand_id(self) -> Optional[int]:
        return await self.fetchval("SELECT id FROM brands ORDER BY id LIMIT 1")

    async def create_brand(self, data: dict) -> int:
        slug_base = str(data.get("name") or "brand").strip().lower().replace(" ", "-")[:40]
        slug = f"{slug_base}-{int(datetime.now().timestamp()) % 100000}"
        return await self.fetchval("""
            INSERT INTO brands (name, slug, active, niche, target_audience, example_products,
                                sell_price_min, sell_price_max, auto_keywords_enabled, keywords_per_scan, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id
        """,
            str(data.get("name") or "New brand").strip(),
            slug,
            1 if data.get("active", True) else 0,
            str(data.get("niche") or ""), str(data.get("target_audience") or ""),
            str(data.get("example_products") or ""),
            float(data.get("sell_price_min") or 40), float(data.get("sell_price_max") or 119),
            1 if data.get("auto_keywords_enabled", True) else 0,
            int(data.get("keywords_per_scan") or 6),
            _now(),
        )

    async def update_brand(self, brand_id: int, data: dict) -> None:
        allowed = {"name", "active", "niche", "target_audience", "example_products",
                   "sell_price_min", "sell_price_max", "auto_keywords_enabled",
                   "keywords_per_scan", "last_keywords_generated_at"}
        updates = {k: v for k, v in (data or {}).items() if k in allowed}
        if not updates:
            return
        for k in ("active", "auto_keywords_enabled"):
            if k in updates:
                updates[k] = 1 if updates[k] else 0
        sets = ", ".join(f"{k}=${i+1}" for i, k in enumerate(updates))
        vals = list(updates.values()) + [brand_id]
        await self.execute(f"UPDATE brands SET {sets} WHERE id=${len(vals)}", *vals)

    async def delete_brand(self, brand_id: int) -> bool:
        n = await self.fetchval("SELECT COUNT(*) FROM products WHERE brand_id=$1", brand_id)
        total = await self.fetchval("SELECT COUNT(*) FROM brands")
        if n or total <= 1:
            return False  # keep brands that own products, never delete the last one
        await self.execute("DELETE FROM brand_keywords WHERE brand_id=$1", brand_id)
        await self.execute("DELETE FROM brands WHERE id=$1", brand_id)
        return True

    async def brand_product_counts(self) -> dict:
        rows = await self.fetch("""
            SELECT brand_id,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE stage='ENRICHED') AS in_review,
                   COUNT(*) FILTER (WHERE stage IN ('REVIEWED','TEXT_REMOVAL','QUEUED')) AS approved,
                   COUNT(*) FILTER (WHERE stage='LIVE') AS live
            FROM products WHERE brand_id IS NOT NULL GROUP BY brand_id
        """)
        return {int(r["brand_id"]): dict(r) for r in rows}

    # ── Brand keywords ────────────────────────────────────────────────────────

    async def add_keywords(self, brand_id: int, keywords: list, source: str = "manual") -> int:
        added = 0
        for kw in keywords:
            kw = str(kw).strip().lower()
            if not kw or len(kw) > 80:
                continue
            row = await self.fetchrow("""
                INSERT INTO brand_keywords (brand_id, keyword, source, status, created_at)
                VALUES ($1,$2,$3,'active',$4)
                ON CONFLICT (brand_id, keyword) DO NOTHING RETURNING id
            """, brand_id, kw, source, _now())
            if row:
                added += 1
        return added

    async def list_keywords(self, brand_id: int, include_retired: bool = True) -> list:
        sql = "SELECT * FROM brand_keywords WHERE brand_id=$1" + ("" if include_retired else " AND status != 'retired'") + " ORDER BY id"
        return [dict(r) for r in await self.fetch(sql, brand_id)]

    async def set_keyword_status(self, keyword_id: int, status: str) -> None:
        await self.execute("UPDATE brand_keywords SET status=$1 WHERE id=$2", status, keyword_id)

    async def delete_keyword(self, keyword_id: int) -> None:
        await self.execute("DELETE FROM brand_keywords WHERE id=$1", keyword_id)

    async def touch_keywords_scanned(self, brand_id: int, keywords: list) -> None:
        await self.execute("""
            UPDATE brand_keywords SET last_scanned_at=$1, scans=scans+1
            WHERE brand_id=$2 AND keyword = ANY($3::text[])
        """, _now(), brand_id, [str(k).lower() for k in keywords])

    async def keyword_performance(self, brand_id: int) -> dict:
        """Live aggregation over products: how each keyword actually performed."""
        rows = await self.fetch("""
            SELECT LOWER(keyword) AS kw,
                   COUNT(*) AS scraped,
                   COUNT(*) FILTER (WHERE ai_provider IS NOT NULL AND ai_provider NOT IN ('', 'mock')) AS scored,
                   COUNT(*) FILTER (WHERE stage IN ('REVIEWED','TEXT_REMOVAL','QUEUED','LIVE') OR approved_at IS NOT NULL) AS approved,
                   COUNT(*) FILTER (WHERE stage='LIVE') AS posted,
                   AVG(NULLIF(composite_score, 0)) AS avg_score
            FROM products
            WHERE brand_id=$1 AND keyword IS NOT NULL AND keyword != ''
            GROUP BY LOWER(keyword)
        """, brand_id)
        return {r["kw"]: {
            "scraped": int(r["scraped"] or 0),
            "scored": int(r["scored"] or 0),
            "approved": int(r["approved"] or 0),
            "posted": int(r["posted"] or 0),
            "avg_score": round(float(r["avg_score"] or 0), 2),
        } for r in rows}

    # ── Activity log ──────────────────────────────────────────────────────────

    async def log_activity(self, kind: str, message: str, product_id=None, level: str = "info", meta: dict | None = None) -> None:
        await self.execute(
            "INSERT INTO activity_log (ts, kind, level, message, product_id, meta) VALUES ($1,$2,$3,$4,$5,$6::jsonb)",
            _now(), kind, level, message[:500], product_id, json.dumps(meta or {}, default=str),
        )

    async def get_activity(self, limit: int = 50, since: str | None = None, kinds: list | None = None) -> list:
        where, args = [], []
        if since:
            args.append(since); where.append(f"ts >= ${len(args)}")
        if kinds:
            args.append(kinds); where.append(f"kind = ANY(${len(args)}::text[])")
        args.append(limit)
        sql = "SELECT * FROM activity_log" + (" WHERE " + " AND ".join(where) if where else "") + f" ORDER BY id DESC LIMIT ${len(args)}"
        rows = await self.fetch(sql, *args)
        out = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("meta"), str):
                try: d["meta"] = json.loads(d["meta"])
                except Exception: d["meta"] = {}
            out.append(d)
        return out

    async def activity_counts(self, since: str) -> dict:
        rows = await self.fetch("SELECT kind, COUNT(*) AS n FROM activity_log WHERE ts >= $1 GROUP BY kind", since)
        return {r["kind"]: int(r["n"]) for r in rows}

    async def last_activity(self, kind: str) -> Optional[dict]:
        row = await self.fetchrow("SELECT * FROM activity_log WHERE kind=$1 ORDER BY id DESC LIMIT 1", kind)
        return dict(row) if row else None

    async def prune_activity(self, keep: int = 5000) -> None:
        await self.execute("DELETE FROM activity_log WHERE id < (SELECT COALESCE(MAX(id),0) - $1 FROM activity_log)", keep)

    # ── Inbox (comments / DMs captured by the webhook) ────────────────────────

    async def inbox_add(self, external_id: str, kind: str, sender_id: str, sender_name: str, text: str,
                        media_id: str = "", is_lead: bool = False, auto_reply: str = "") -> Optional[int]:
        row = await self.fetchrow("""
            INSERT INTO inbox_messages (external_id, kind, sender_id, sender_name, text, media_id, is_lead, auto_reply, received_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (external_id) DO NOTHING
            RETURNING id
        """, external_id, kind, sender_id, sender_name, (text or "")[:2000], media_id, 1 if is_lead else 0, auto_reply or "", _now())
        return int(row["id"]) if row else None

    async def inbox_list(self, only_open: bool = True, limit: int = 100) -> list:
        sql = "SELECT * FROM inbox_messages" + (" WHERE handled=0" if only_open else "") + " ORDER BY is_lead DESC, id DESC LIMIT $1"
        rows = await self.fetch(sql, limit)
        return [dict(r) for r in rows]

    async def inbox_get(self, mid: int) -> Optional[dict]:
        row = await self.fetchrow("SELECT * FROM inbox_messages WHERE id=$1", mid)
        return dict(row) if row else None

    async def inbox_set_handled(self, mid: int, handled: bool = True) -> None:
        await self.execute("UPDATE inbox_messages SET handled=$1 WHERE id=$2", 1 if handled else 0, mid)

    async def inbox_counts(self) -> dict:
        row = await self.fetchrow("""
            SELECT COUNT(*) FILTER (WHERE handled=0) AS open,
                   COUNT(*) FILTER (WHERE handled=0 AND is_lead=1) AS leads,
                   COUNT(*) AS total
            FROM inbox_messages
        """)
        return {k: int(row[k] or 0) for k in ("open", "leads", "total")} if row else {"open": 0, "leads": 0, "total": 0}

    # ── Autopilot helpers ─────────────────────────────────────────────────────

    async def count_posts_since(self, since: str) -> int:
        return int(await self.fetchval("SELECT COUNT(*) FROM post_log WHERE posted_at >= $1", since) or 0)

    async def last_job_time(self) -> Optional[str]:
        return await self.fetchval("SELECT created_at FROM jobs ORDER BY id DESC LIMIT 1")

    async def count_stage_older_than(self, stage: str, before_iso: str) -> int:
        return int(await self.fetchval("SELECT COUNT(*) FROM products WHERE stage=$1 AND created_at < $2", stage, before_iso) or 0)

    async def reject_stage_older_than(self, stage: str, before_iso: str, reason: str) -> int:
        rows = await self.fetch(
            "UPDATE products SET stage='REJECTED', rejection_reason=$3, rejected_at=$4 WHERE stage=$1 AND created_at < $2 RETURNING id",
            stage, before_iso, reason, _now(),
        )
        return len(rows)

    async def count_admin_users(self) -> int:
        return int(await self.fetchval("SELECT COUNT(*) FROM admin_users") or 0)

    async def create_admin_user(self, email: str, password_hash: str) -> int:
        row = await self.fetchrow("""
            INSERT INTO admin_users (email, password_hash, created_at)
            VALUES ($1, $2, $3)
            ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash
            RETURNING id
        """, email.strip().lower(), password_hash, _now())
        return int(row["id"])

    async def get_admin_user(self, email: str) -> Optional[dict]:
        row = await self.fetchrow("SELECT * FROM admin_users WHERE email=$1", email.strip().lower())
        return dict(row) if row else None

    # ── AI Recommendations ────────────────────────────────────────────────────

    async def clear_active_recommendations(self) -> None:
        """Remove non-dismissed, non-applied recommendations before re-analysis."""
        await self.execute(
            "DELETE FROM ai_recommendations WHERE dismissed = 0 AND applied = 0"
        )

    async def save_recommendation(self, finding: dict) -> int:
        # asyncpg requires JSONB values to be passed as a JSON string; the driver
        # handles the cast to jsonb on the server side.
        row = await self.fetchrow("""
            INSERT INTO ai_recommendations (generated_at, analysis_type, headline, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            RETURNING id
        """, _now(), finding["type"], finding["headline"], json.dumps(finding))
        return row["id"]

    async def get_recommendations(self, include_dismissed: bool = False) -> list:
        if include_dismissed:
            rows = await self.fetch(
                "SELECT * FROM ai_recommendations ORDER BY id DESC"
            )
        else:
            rows = await self.fetch(
                "SELECT * FROM ai_recommendations WHERE dismissed = 0 ORDER BY id DESC"
            )
        # asyncpg decodes JSONB columns automatically into dicts; no json.loads needed.
        return [dict(r) for r in rows]

    async def dismiss_recommendation(self, rec_id: int) -> None:
        await self.execute(
            "UPDATE ai_recommendations SET dismissed = 1 WHERE id = $1", rec_id
        )

    # ── Enrichment observability log ──────────────────────────────────────────

    async def log_enrichment_batch(self, record: dict) -> None:
        """
        Write one row to enrichment_log after a worker batch completes.
        Fire-and-forget — callers must wrap this in try/except.
        """
        await self.execute("""
            INSERT INTO enrichment_log
                (ts, flag_on, snippet_injected, snippet_length,
                 skip_reason, batch_size, accepted_count, rejected_count, avg_score)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
            _now(),
            int(record.get("flag_on", 0)),
            int(record.get("snippet_injected", 0)),
            int(record.get("snippet_length", 0)),
            record.get("skip_reason"),          # TEXT or None
            int(record.get("batch_size", 0)),
            int(record.get("accepted_count", 0)),
            int(record.get("rejected_count", 0)),
            record.get("avg_score"),            # DOUBLE PRECISION or None
        )

    async def get_injection_stats(self) -> dict:
        """
        Aggregate comparison of batches scored with injection ON (snippet_injected=1)
        versus OFF (snippet_injected=0), plus a breakdown by skip_reason.
        """
        by_injected = await self.fetch("""
            SELECT
                snippet_injected,
                COUNT(*)                                                    AS batches,
                COALESCE(SUM(batch_size), 0)                               AS total_products,
                COALESCE(SUM(accepted_count), 0)                           AS accepted,
                COALESCE(SUM(rejected_count), 0)                           AS rejected,
                ROUND(
                    COALESCE(SUM(accepted_count), 0)::numeric
                    / NULLIF(SUM(batch_size), 0) * 100, 1
                )                                                           AS acceptance_rate,
                ROUND(AVG(avg_score)::numeric, 2)                          AS avg_score
            FROM enrichment_log
            GROUP BY snippet_injected
            ORDER BY snippet_injected
        """)

        by_reason = await self.fetch("""
            SELECT
                flag_on,
                snippet_injected,
                COALESCE(skip_reason, 'injected')                          AS skip_reason,
                COUNT(*)                                                    AS batches,
                COALESCE(SUM(batch_size), 0)                               AS total_products,
                COALESCE(SUM(accepted_count), 0)                           AS accepted,
                ROUND(
                    COALESCE(SUM(accepted_count), 0)::numeric
                    / NULLIF(SUM(batch_size), 0) * 100, 1
                )                                                           AS acceptance_rate,
                ROUND(AVG(avg_score)::numeric, 2)                          AS avg_score
            FROM enrichment_log
            GROUP BY flag_on, snippet_injected, skip_reason
            ORDER BY flag_on, snippet_injected
        """)

        totals = await self.fetchrow(
            "SELECT COUNT(*) AS batches, COALESCE(SUM(batch_size), 0) AS products FROM enrichment_log"
        )

        def _row(r: dict) -> dict:
            return {
                "batches":         r["batches"],
                "total_products":  r["total_products"],
                "accepted":        r["accepted"],
                "rejected":        r["rejected"],
                "acceptance_rate": float(r["acceptance_rate"]) if r["acceptance_rate"] is not None else None,
                "avg_score":       float(r["avg_score"]) if r["avg_score"] is not None else None,
            }

        injected_map = {r["snippet_injected"]: r for r in by_injected}
        on_row  = injected_map.get(1)
        off_row = injected_map.get(0)

        return {
            "total_batches":   int(totals["batches"]),
            "total_products":  int(totals["products"]),
            "with_injection":  _row(dict(on_row))  if on_row  else None,
            "without_injection": _row(dict(off_row)) if off_row else None,
            "by_skip_reason": [
                {
                    "flag_on":          r["flag_on"],
                    "snippet_injected": r["snippet_injected"],
                    "skip_reason":      r["skip_reason"],
                    "batches":          r["batches"],
                    "total_products":   r["total_products"],
                    "accepted":         r["accepted"],
                    "acceptance_rate":  float(r["acceptance_rate"]) if r["acceptance_rate"] is not None else None,
                    "avg_score":        float(r["avg_score"]) if r["avg_score"] is not None else None,
                }
                for r in by_reason
            ],
        }

    async def get_injection_log(self, limit: int = 50) -> list:
        """Recent enrichment batch records, newest first."""
        rows = await self.fetch("""
            SELECT id, ts, flag_on, snippet_injected, snippet_length,
                   skip_reason, batch_size, accepted_count, rejected_count, avg_score
            FROM enrichment_log
            ORDER BY id DESC
            LIMIT $1
        """, limit)
        return [dict(r) for r in rows]


# ── Helpers ───────────────────────────────────────────────────────────────────

_embedded_pg = None  # keep the pgserver handle alive for the life of the process


def _start_embedded_postgres() -> str | None:
    """
    Start (or attach to) an embedded PostgreSQL cluster in DATA_DIR/pg using the
    `pgserver` package. Returns a connection URI, or None if pgserver is missing.
    Used when DATABASE_URL is not set — i.e. the zero-config self-hosted mode.
    """
    global _embedded_pg
    try:
        import pgserver  # type: ignore
    except Exception:
        log.warning("DATABASE_URL not set and `pgserver` is not installed.")
        return None
    try:
        from config.paths import PG_DIR
        _embedded_pg = pgserver.get_server(str(PG_DIR))
        uri = _embedded_pg.get_uri()
        log.info("Embedded PostgreSQL started at %s (data dir %s)", uri.split("@")[-1], PG_DIR)
        return uri
    except Exception as exc:
        log.error("Embedded PostgreSQL failed to start: %s", exc)
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_job(row) -> dict:
    if row is None:
        return {}
    d = dict(row)
    if "keywords_json" in d:
        try:
            d["keywords"] = json.loads(d["keywords_json"]) if d["keywords_json"] else []
        except Exception:
            d["keywords"] = []
        del d["keywords_json"]
    return d


def _row_to_product(row) -> dict:
    if row is None:
        return {}
    d = dict(row)
    for k in ("images_json", "hashtags_json"):
        if k in d:
            try:
                d[k.replace("_json", "")] = json.loads(d[k]) if d[k] else []
            except Exception:
                d[k.replace("_json", "")] = []
            del d[k]
    if "has_chinese_text" in d:
        d["has_chinese_text"] = bool(d["has_chinese_text"])
    # Canonical per-dimension AI scores (stored by worker.py as JSON text)
    scores = {}
    raw_scores = d.pop("scores_json", None)
    if raw_scores:
        try:
            scores = json.loads(raw_scores) or {}
        except Exception:
            scores = {}
    d["scores"] = scores
    return d

# ── Singleton ─────────────────────────────────────────────────────────────────

db = Database()


async def init_db():
    await db.connect()
    # Wrap ALL schema DDL in a single transaction on a single connection.
    # Each CREATE TABLE / INDEX / INSERT would otherwise be a separate network
    # round-trip to Supabase (~100 ms each). Batching ~40 statements this way
    # reduces startup time from ~4 s to under 1 s.
    async with db._pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id                SERIAL PRIMARY KEY,
                    job_id            INTEGER,
                    source            TEXT,
                    source_id         TEXT UNIQUE,
                    title             TEXT,
                    title_translated  TEXT,
                    product_name      TEXT,
                    price_cny         DOUBLE PRECISION,
                    cost_eur          DOUBLE PRECISION,
                    sell_price_eur    DOUBLE PRECISION,
                    margin_pct        DOUBLE PRECISION,
                    orders            INTEGER,
                    rating            DOUBLE PRECISION,
                    images_json       TEXT,
                    url               TEXT,
                    category          TEXT,
                    keyword           TEXT,
                    score             DOUBLE PRECISION,
                    niche_fit         DOUBLE PRECISION,
                    visual_appeal     DOUBLE PRECISION,
                    trend_score       DOUBLE PRECISION,
                    competition_score DOUBLE PRECISION DEFAULT 0,
                    caption           TEXT,
                    description       TEXT DEFAULT '',
                    hashtags_json     TEXT,
                    ai_provider       TEXT DEFAULT '',
                    has_chinese_text  INTEGER DEFAULT 0,
                    chinese_text_note TEXT DEFAULT '',
                    stage             TEXT DEFAULT 'SCRAPED',
                    rejection_reason  TEXT,
                    review_note       TEXT,
                    approved_at       TEXT,
                    rejected_at       TEXT,
                    posted_at         TEXT,
                    created_at        TEXT,
                    audience          TEXT DEFAULT '',
                    instagram_url     TEXT DEFAULT '',
                    CHECK (stage IN ('SCRAPED', 'ENRICHED', 'TEXT_REMOVAL', 'REVIEWED', 'QUEUED', 'LIVE', 'REJECTED', 'EXCEPTION'))
                )
            """)

            # Indexes — batched inside the same transaction
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_stage ON products(stage)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_source_id ON products(source_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_source_platform ON products(source)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_stage_created ON products(stage, created_at)")

            # ── Migrations for existing DBs ────────────────────────────────
            for col, definition in [
                ("audience", "TEXT DEFAULT ''"),
                ("instagram_url", "TEXT DEFAULT ''"),
                # AI scoring v2 — written by worker.py, read by the review UI.
                # These were missing from the schema, so every worker batch failed
                # with "column composite_score does not exist" on a fresh DB.
                ("composite_score", "DOUBLE PRECISION DEFAULT 0"),
                ("verdict", "TEXT DEFAULT ''"),
                ("product_tier", "TEXT DEFAULT ''"),
                ("confidence", "DOUBLE PRECISION DEFAULT 0"),
                ("viral_angle", "TEXT DEFAULT ''"),
                ("emotional_hook", "TEXT DEFAULT ''"),
                # The two scoring dimensions that were computed but never persisted.
                ("cute_appeal", "DOUBLE PRECISION DEFAULT 0"),
                ("giftability", "DOUBLE PRECISION DEFAULT 0"),
                ("scores_json", "TEXT DEFAULT ''"),
            ]:
                try:
                    await conn.execute(f"ALTER TABLE products ADD COLUMN IF NOT EXISTS {col} {definition}")
                except Exception:
                    pass

            try:
                await conn.execute("ALTER TABLE products DROP CONSTRAINT IF EXISTS products_stage_check")
                await conn.execute("""
                    ALTER TABLE products
                    ADD CONSTRAINT products_stage_check
                    CHECK (stage IN ('SCRAPED', 'ENRICHED', 'TEXT_REMOVAL', 'REVIEWED', 'QUEUED', 'LIVE', 'REJECTED', 'EXCEPTION'))
                    NOT VALID
                """)
            except Exception as exc:
                log.warning("Could not refresh products stage check constraint: %s", exc)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id            SERIAL PRIMARY KEY,
                    keywords_json TEXT,
                    status        TEXT,
                    progress      INTEGER DEFAULT 0,
                    scraped       INTEGER DEFAULT 0,
                    after_basic   INTEGER DEFAULT 0,
                    after_profit  INTEGER DEFAULT 0,
                    after_dedup   INTEGER DEFAULT 0,
                    after_ai      INTEGER DEFAULT 0,
                    created_at    TEXT
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS products_raw (
                    id           SERIAL PRIMARY KEY,
                    job_id       INTEGER,
                    source       TEXT,
                    source_id    TEXT,
                    product_name TEXT,
                    price        DOUBLE PRECISION,
                    image_url    TEXT,
                    merchant     TEXT,
                    raw_data     TEXT,
                    created_at   TEXT,
                    UNIQUE(job_id, source_id)
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS post_log (
                    id         SERIAL PRIMARY KEY,
                    product_id INTEGER,
                    posted_at  TEXT
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_products (
                    id                SERIAL PRIMARY KEY,
                    job_id            INTEGER,
                    source_id         TEXT,
                    title             TEXT,
                    product_name      TEXT DEFAULT '',
                    image_url         TEXT,
                    url               TEXT DEFAULT '',
                    price_cny         DOUBLE PRECISION DEFAULT 0,
                    cost_eur          DOUBLE PRECISION DEFAULT 0,
                    sell_price_eur    DOUBLE PRECISION DEFAULT 0,
                    orders            INTEGER DEFAULT 0,
                    rating            DOUBLE PRECISION DEFAULT 0,
                    margin_pct        DOUBLE PRECISION DEFAULT 0,
                    raw_score         DOUBLE PRECISION DEFAULT 0,
                    filter_stage      TEXT,
                    filter_reason     TEXT DEFAULT '',
                    ai_score          DOUBLE PRECISION DEFAULT 0,
                    ai_niche_fit      DOUBLE PRECISION DEFAULT 0,
                    ai_visual         DOUBLE PRECISION DEFAULT 0,
                    trend_score       DOUBLE PRECISION DEFAULT 0,
                    competition_score DOUBLE PRECISION DEFAULT 0,
                    ai_provider       TEXT DEFAULT '',
                    created_at        TEXT
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS comment_reply_log (
                    id           SERIAL PRIMARY KEY,
                    comment_id   TEXT UNIQUE,
                    reply_type   TEXT DEFAULT 'comment',
                    replied_at   TEXT,
                    matched_rule TEXT
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS admin_users (
                    id            SERIAL PRIMARY KEY,
                    email         TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at    TEXT
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_recommendations (
                    id             SERIAL PRIMARY KEY,
                    generated_at   TEXT NOT NULL,
                    analysis_type  TEXT NOT NULL,
                    headline       TEXT NOT NULL,
                    payload        JSONB NOT NULL,
                    applied        INTEGER DEFAULT 0,
                    dismissed      INTEGER DEFAULT 0
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_rec_dismissed ON ai_recommendations(dismissed)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_rec_type ON ai_recommendations(analysis_type)"
            )
            # Migration: convert existing TEXT payload column to JSONB if it exists as TEXT.
            # Safe no-op if the column is already JSONB or the table was just created.
            try:
                await conn.execute("""
                    ALTER TABLE ai_recommendations
                    ALTER COLUMN payload TYPE JSONB USING payload::jsonb
                """)
            except Exception:
                pass  # Already JSONB or table just created — either way correct

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS brands (
                    id                SERIAL PRIMARY KEY,
                    name              TEXT NOT NULL,
                    slug              TEXT UNIQUE,
                    active            INTEGER DEFAULT 1,
                    niche             TEXT DEFAULT '',
                    target_audience   TEXT DEFAULT '',
                    example_products  TEXT DEFAULT '',
                    sell_price_min    DOUBLE PRECISION DEFAULT 40,
                    sell_price_max    DOUBLE PRECISION DEFAULT 119,
                    auto_keywords_enabled INTEGER DEFAULT 1,
                    keywords_per_scan INTEGER DEFAULT 6,
                    last_keywords_generated_at TEXT,
                    created_at        TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS brand_keywords (
                    id              SERIAL PRIMARY KEY,
                    brand_id        INTEGER NOT NULL,
                    keyword         TEXT NOT NULL,
                    source          TEXT DEFAULT 'manual',   -- manual | ai
                    status          TEXT DEFAULT 'active',   -- active | paused | retired
                    created_at      TEXT,
                    last_scanned_at TEXT,
                    scans           INTEGER DEFAULT 0,
                    UNIQUE(brand_id, keyword)
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_bkw_brand ON brand_keywords(brand_id, status)")
            await conn.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS brand_id INTEGER")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand_id)")
            await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS brand_id INTEGER")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    id         SERIAL PRIMARY KEY,
                    ts         TEXT NOT NULL,
                    kind       TEXT NOT NULL,
                    level      TEXT NOT NULL DEFAULT 'info',
                    message    TEXT NOT NULL,
                    product_id INTEGER,
                    meta       JSONB
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_log(ts)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_kind ON activity_log(kind)")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS inbox_messages (
                    id          SERIAL PRIMARY KEY,
                    external_id TEXT UNIQUE,
                    kind        TEXT NOT NULL,              -- comment | dm
                    sender_id   TEXT,
                    sender_name TEXT,
                    text        TEXT,
                    media_id    TEXT,
                    is_lead     INTEGER DEFAULT 0,
                    auto_reply  TEXT,
                    handled     INTEGER DEFAULT 0,
                    received_at TEXT NOT NULL
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_inbox_handled ON inbox_messages(handled)")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS enrichment_log (
                    id               SERIAL PRIMARY KEY,
                    ts               TEXT NOT NULL,
                    flag_on          INTEGER NOT NULL DEFAULT 0,
                    snippet_injected INTEGER NOT NULL DEFAULT 0,
                    snippet_length   INTEGER NOT NULL DEFAULT 0,
                    skip_reason      TEXT,
                    batch_size       INTEGER NOT NULL DEFAULT 0,
                    accepted_count   INTEGER NOT NULL DEFAULT 0,
                    rejected_count   INTEGER NOT NULL DEFAULT 0,
                    avg_score        DOUBLE PRECISION
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_enr_log_ts ON enrichment_log(ts)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_enr_log_injected ON enrichment_log(snippet_injected)"
            )

            defaults = {
                "instagram_auto_reply_enabled": False,
                "instagram_reply_rules": [],
                "instagram_dm_reply_enabled": False,
                "instagram_dm_rules": [],
                "instagram_webhook_token": "dropos_webhook_secret",
                "niche": "couple gifts & romantic products",
                "min_margin": 60.0,
                "min_score": 6.0,
                "min_orders": 100,
                "min_rating": 4.5,
                "sell_markup_low": 3.5,
                "sell_markup_mid": 2.8,
                "sell_markup_high": 2.2,
                "exchange_rate": 0.353,
                "apify_token": "",
                "anthropic_key": "",
                "gemini_key": "",
                "instagram_username": "",
                "scan_keywords": ["couple gifts", "romantic gifts for her", "gifts for boyfriend", "gifts for girlfriend", "anniversary gifts"],
                "google_sheets_id": "",
                "google_sheets_credentials": "",
                "public_base_url": "",
                "cssbuy_username": "",
                "cssbuy_password": "",
                "cssbuy_source": "1688",
                "captcha_2captcha_key": "",
                "ingest_api_token": "",
                "local_scraping_only": False,
                "gemini_model": "gemini-2.5-flash-lite",
                "target_audience": "couples and people buying gifts for partners, ages 18-35",
                "sell_price_min": 15,
                "sell_price_max": 80,
                "example_products": "matching couple bracelets, personalised photo frames, couple card games, romantic candle sets, love letter boxes, matching phone cases",
                # Phase 2 — decision-memory context injection (default OFF)
                # When true, a compact aggregate summary of past accepted/rejected decisions
                # is appended to the Gemini system prompt at enrichment time.
                # No behavior change when false — identical to production baseline.
                "ai_context_injection": False,
                # Peak-hour Instagram auto-posting (Settings → Posting schedule)
                # Content writer (second model next to Gemini)
                "content_provider": "auto",
                "content_rewrite_enabled": True,
                "anthropic_model": "claude-opus-5",
                "openai_model": "gpt-5-mini",
                "post_schedule_enabled": False,
                "post_times": ["19:00", "21:00"],
                "post_timezone": "Asia/Tbilisi",
                "posts_per_slot": 1,
                "store_name": "Tskvili",
                # ── Autopilot (hands-off mode) ───────────────────────────
                "autopilot_enabled": False,          # master switch
                "auto_scan_enabled": True,           # scheduled scans with scan_keywords
                "scan_interval_hours": 12,
                "auto_approve_enabled": True,        # approve winners without a human
                "auto_approve_min_score": 7.0,       # composite threshold
                "auto_approve_verdicts": ["top_priority", "strong_candidate"],
                "auto_clean_images": True,           # Clipdrop for has_chinese_text (needs key)
                "auto_reject_pending_days": 0,       # 0 = keep pending items forever
                "max_posts_per_day": 2,
                "lead_keywords": ["order", "buy", "price", "how much", "want", "ship", "delivery",
                                  "ფასი", "შეკვეთა", "მინდა", "რა ღირს", "ვიყიდი", "მიწოდება"],
            }
            for k, v in defaults.items():
                val = json.dumps(v) if not isinstance(v, str) else v
                await conn.execute("""
                    INSERT INTO settings (key, value) VALUES ($1, $2)
                    ON CONFLICT (key) DO NOTHING
                """, k, val)

            # Seed default admin user if environment variables are set
            admin_email = os.getenv("ADMIN_EMAIL")
            admin_pass_hash = os.getenv("ADMIN_PASSWORD_HASH")
            if admin_email and admin_pass_hash:
                await conn.execute("""
                    INSERT INTO admin_users (email, password_hash, created_at)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (email) DO UPDATE 
                    SET password_hash = EXCLUDED.password_hash
                """, admin_email.strip().lower(), admin_pass_hash, _now())

    # ── Default brand: created from the store persona on first boot ─────────
    async with db._pool.acquire() as conn:
        if not await conn.fetchval("SELECT COUNT(*) FROM brands"):
            def _sv(key, default=""):
                return None  # placeholder, replaced below
            rows = await conn.fetch("SELECT key, value FROM settings")
            sv = {}
            for r in rows:
                try:
                    sv[r["key"]] = json.loads(r["value"])
                except Exception:
                    sv[r["key"]] = r["value"]
            brand_id = await conn.fetchval("""
                INSERT INTO brands (name, slug, niche, target_audience, example_products,
                                    sell_price_min, sell_price_max, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id
            """,
                str(sv.get("store_name") or "Tskvili"), "default",
                str(sv.get("niche") or ""), str(sv.get("target_audience") or ""),
                str(sv.get("example_products") or ""),
                float(sv.get("sell_price_min") or 40), float(sv.get("sell_price_max") or 119),
                _now(),
            )
            for kw in (sv.get("scan_keywords") or []):
                kw = str(kw).strip()
                if kw:
                    await conn.execute("""
                        INSERT INTO brand_keywords (brand_id, keyword, source, status, created_at)
                        VALUES ($1,$2,'manual','active',$3) ON CONFLICT (brand_id, keyword) DO NOTHING
                    """, brand_id, kw, _now())
            log.info("Seeded default brand #%s from store settings", brand_id)
        # Orphan products/jobs (pre-brands data) belong to the default brand
        default_id = await conn.fetchval("SELECT id FROM brands ORDER BY id LIMIT 1")
        if default_id:
            await conn.execute("UPDATE products SET brand_id=$1 WHERE brand_id IS NULL", default_id)
            await conn.execute("UPDATE jobs SET brand_id=$1 WHERE brand_id IS NULL", default_id)

    log.info("Database schema initialised.")
