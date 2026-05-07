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

    async def connect(self):
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            log.critical(
                "\n"
                "╔══════════════════════════════════════════════════════════╗\n"
                "║  FATAL: DATABASE_URL environment variable is not set.   ║\n"
                "║                                                          ║\n"
                "║  Fix:  Railway Dashboard → Service → Variables → Add:   ║\n"
                "║        Use the Supabase SESSION POOLER connection string ║\n"
                "║        (Settings → Database → Connection pooling)        ║\n"
                "╚══════════════════════════════════════════════════════════╝"
            )
            sys.exit(1)

        last_exc = None
        for attempt in range(3):
            try:
                self._pool = await asyncpg.create_pool(
                    db_url,
                    ssl="require",
                    statement_cache_size=0,  # Required for PgBouncer/Supabase pooler
                    min_size=1,              # 1 warm connection — faster cold start
                    max_size=10,             # Allow up to 10 concurrent queries
                    command_timeout=30,      # Fail fast instead of hanging 60s+
                )
                log.info("Database pool created successfully (min=2, max=10).")
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
        await self.execute("""
            INSERT INTO products
            (job_id, source, source_id, title, title_translated, product_name,
             price_cny, cost_eur, sell_price_eur, margin_pct, orders, rating,
             images_json, url, category, keyword,
             score, niche_fit, visual_appeal, trend_score, competition_score,
             caption, description, hashtags_json, ai_provider, has_chinese_text,
             chinese_text_note, rejection_reason, stage, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30)
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
            _now()
        )

    async def get_products(self, stage: str = "SCRAPED", limit: int = 50, offset: int = 0, sort: str = "score") -> list:
        sort_map = {
            "score": "score DESC",
            "margin": "margin_pct DESC",
            "orders": "orders DESC",
            "created": "created_at DESC",
        }
        order = sort_map.get(sort, "score DESC")
        rows = await self.fetch(
            f"SELECT * FROM products WHERE stage=$1 ORDER BY {order} LIMIT $2 OFFSET $3",
            stage, limit, offset
        )
        return [_row_to_product(r) for r in rows]

    async def get_all_products(self, limit: int = 5000) -> list:
        rows = await self.fetch("SELECT * FROM products ORDER BY id DESC LIMIT $1", limit)
        return [_row_to_product(r) for r in rows]

    async def count_products(self, stage: str = "SCRAPED") -> int:
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
             stage=EXCLUDED.stage,
             rejection_reason=EXCLUDED.rejection_reason,
             review_note=EXCLUDED.review_note,
             approved_at=EXCLUDED.approved_at,
             rejected_at=EXCLUDED.rejected_at,
             posted_at=EXCLUDED.posted_at
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
            "ENRICHED": "approved_at",
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

    async def create_job(self, keywords: list) -> int:
        job_id = await self.fetchval("""
            INSERT INTO jobs (keywords_json, status, progress, scraped,
               after_basic, after_profit, after_dedup, after_ai, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            RETURNING id
        """, json.dumps(keywords), "queued", 0, 0, 0, 0, 0, 0, _now())
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

    async def get_stats(self) -> dict:
        stats: dict = {}
        for stage in ("SCRAPED", "REVIEWED", "ENRICHED", "LIVE", "REJECTED"):
            val = await self.fetchval("SELECT COUNT(*) FROM products WHERE stage=$1", stage)
            stats[stage] = val if val else 0

        val = await self.fetchval("SELECT COUNT(*) FROM jobs")
        stats["total_jobs"] = val if val else 0

        val = await self.fetchval("SELECT COUNT(*) FROM post_log WHERE posted_at::timestamp > (NOW() - INTERVAL '7 days')")
        stats["posted_7d"] = val if val else 0

        val = await self.fetchval("SELECT AVG(margin_pct) FROM products WHERE stage='SCRAPED'")
        stats["avg_margin_pending"] = round(val or 0, 1)

        val = await self.fetchval("SELECT AVG(score) FROM products WHERE stage='SCRAPED'")
        stats["avg_score_pending"] = round(val or 0, 1)

        total_reviewed = stats["REVIEWED"] + stats["ENRICHED"] + stats["REJECTED"]
        stats["approval_rate"] = (
            round((stats["REVIEWED"] + stats["ENRICHED"]) / total_reviewed * 100, 1) if total_reviewed else 0
        )

        return stats


# ── Helpers ───────────────────────────────────────────────────────────────────

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
                    CHECK (stage IN ('SCRAPED', 'ENRICHED', 'REVIEWED', 'QUEUED', 'LIVE', 'REJECTED'))
                )
            """)

            # Indexes — batched inside the same transaction
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_stage ON products(stage)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_source_id ON products(source_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_source_platform ON products(source)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_stage_created ON products(stage, created_at)")

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
            }
            for k, v in defaults.items():
                val = json.dumps(v) if not isinstance(v, str) else v
                await conn.execute("""
                    INSERT INTO settings (key, value) VALUES ($1, $2)
                    ON CONFLICT (key) DO NOTHING
                """, k, val)

    log.info("Database schema initialised.")
