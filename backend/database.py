import aiosqlite
import json
import os
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "dropship.db")


class Database:
    def __init__(self):
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self._db = await aiosqlite.connect(DB_PATH)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute("PRAGMA synchronous=NORMAL;")

    async def close(self):
        if self._db:
            await self._db.close()

    # ── Products ──────────────────────────────────────────────────────────────

    async def insert_product(self, p: dict, job_id: int):
        await self._db.execute("""
            INSERT OR IGNORE INTO products
            (job_id, source, source_id, title, title_translated, product_name,
             price_cny, cost_eur, sell_price_eur, margin_pct, orders, rating,
             images_json, url, category, keyword,
             score, niche_fit, visual_appeal, trend_score, competition_score,
             caption, description, hashtags_json, ai_provider, has_chinese_text,
             chinese_text_note, stage, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            job_id,
            p.get("source", ""),
            p.get("source_id", ""),
            p.get("title", ""),
            p.get("title_translated", ""),
            p.get("product_name", ""),
            p.get("price_cny", 0),
            p.get("cost_eur", 0),
            p.get("sell_price_eur", 0),
            p.get("margin_pct", 0),
            p.get("orders", 0),
            p.get("rating", 0),
            json.dumps(p.get("images", [])),
            p.get("url", ""),
            p.get("category", ""),
            p.get("keyword", ""),
            p.get("score", 0),
            p.get("niche_fit", 0),
            p.get("visual_appeal", 0),
            p.get("trend_score", 0),
            p.get("competition_score", 0),
            p.get("caption", ""),
            p.get("description", ""),
            json.dumps(p.get("hashtags", [])),
            p.get("ai_provider", ""),
            1 if p.get("has_chinese_text") else 0,
            p.get("chinese_text_note", ""),
            "SCRAPED",
            _now(),
        ))
        await self._db.commit()

    async def get_products(
        self, stage: str = "SCRAPED", limit: int = 50, offset: int = 0, sort: str = "score"
    ) -> list:
        sort_map = {
            "score": "score DESC",
            "margin": "margin_pct DESC",
            "orders": "orders DESC",
            "created": "created_at DESC",
        }
        order = sort_map.get(sort, "score DESC")
        async with self._db.execute(
            f"SELECT * FROM products WHERE stage=? ORDER BY {order} LIMIT ? OFFSET ?",
            (stage, limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_product(r) for r in rows]

    async def get_all_products(self, limit: int = 5000) -> list:
        async with self._db.execute(
            "SELECT * FROM products ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_product(r) for r in rows]

    async def count_products(self, stage: str = "SCRAPED") -> int:
        async with self._db.execute(
            "SELECT COUNT(*) FROM products WHERE stage=?", (stage,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    async def get_product(self, pid: int) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM products WHERE id=?", (pid,)
        ) as cur:
            row = await cur.fetchone()
        return _row_to_product(row) if row else None

    async def upsert_product_backup(self, p: dict) -> None:
        source_id = str(p.get("source_id") or "").strip()
        if not source_id:
            return
        await self._db.execute("""
            INSERT INTO products
            (job_id, source, source_id, title, title_translated, product_name,
             price_cny, cost_eur, sell_price_eur, margin_pct, orders, rating,
             images_json, url, category, keyword,
             score, niche_fit, visual_appeal, trend_score, competition_score,
             caption, description, hashtags_json, ai_provider, has_chinese_text, chinese_text_note,
             stage, rejection_reason, review_note,
             approved_at, rejected_at, posted_at, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_id) DO UPDATE SET
             job_id=excluded.job_id,
             source=excluded.source,
             title=excluded.title,
             title_translated=excluded.title_translated,
             product_name=excluded.product_name,
             price_cny=excluded.price_cny,
             cost_eur=excluded.cost_eur,
             sell_price_eur=excluded.sell_price_eur,
             margin_pct=excluded.margin_pct,
             orders=excluded.orders,
             rating=excluded.rating,
             images_json=excluded.images_json,
             url=excluded.url,
             category=excluded.category,
             keyword=excluded.keyword,
             score=excluded.score,
             niche_fit=excluded.niche_fit,
             visual_appeal=excluded.visual_appeal,
             trend_score=excluded.trend_score,
             competition_score=excluded.competition_score,
             caption=excluded.caption,
             description=excluded.description,
             hashtags_json=excluded.hashtags_json,
             ai_provider=excluded.ai_provider,
             has_chinese_text=excluded.has_chinese_text,
             chinese_text_note=excluded.chinese_text_note,
             stage=excluded.stage,
             rejection_reason=excluded.rejection_reason,
             review_note=excluded.review_note,
             approved_at=excluded.approved_at,
             rejected_at=excluded.rejected_at,
             posted_at=excluded.posted_at
        """, (
            p.get("job_id", 0),
            p.get("source", ""),
            source_id,
            p.get("title", ""),
            p.get("title_translated", ""),
            p.get("product_name", ""),
            p.get("price_cny", 0),
            p.get("cost_eur", 0),
            p.get("sell_price_eur", 0),
            p.get("margin_pct", 0),
            p.get("orders", 0),
            p.get("rating", 0),
            json.dumps(p.get("images", [])),
            p.get("url", ""),
            p.get("category", ""),
            p.get("keyword", ""),
            p.get("score", 0),
            p.get("niche_fit", 0),
            p.get("visual_appeal", 0),
            p.get("trend_score", 0),
            p.get("competition_score", 0),
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
            p.get("created_at") or _now(),
        ))
        await self._db.commit()

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

        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [pid]
        await self._db.execute(f"UPDATE products SET {sets} WHERE id=?", vals)
        await self._db.commit()

    async def update_product_note(self, pid: int, note: str):
        await self._db.execute(
            "UPDATE products SET review_note=? WHERE id=?", (note, pid)
        )
        await self._db.commit()

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
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [pid]
        await self._db.execute(f"UPDATE products SET {sets} WHERE id=?", vals)
        await self._db.commit()
        return await self.get_product(pid)

    async def log_post(self, pid: int):
        await self._db.execute(
            "INSERT INTO post_log (product_id, posted_at) VALUES (?,?)",
            (pid, _now()),
        )
        await self._db.commit()

    async def bulk_insert_pipeline(self, records: list) -> None:
        """Bulk insert pipeline tracking records."""
        for r in records:
            await self._db.execute("""
                INSERT INTO pipeline_products
                (job_id, source_id, title, product_name, image_url, url, price_cny,
                 cost_eur, sell_price_eur, orders, rating, margin_pct, raw_score,
                 filter_stage, filter_reason, ai_score, ai_niche_fit, ai_visual,
                 trend_score, competition_score, ai_provider, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                r["job_id"], r["source_id"], r["title"], r.get("product_name", ""),
                r["image_url"], r.get("url", ""), r["price_cny"],
                r.get("cost_eur", 0), r.get("sell_price_eur", 0),
                r["orders"], r.get("rating", 0), r["margin_pct"], r.get("raw_score", 0),
                r["filter_stage"], r.get("filter_reason", ""),
                r.get("ai_score", 0), r.get("ai_niche_fit", 0), r.get("ai_visual", 0),
                r.get("trend_score", 0), r.get("competition_score", 0),
                r.get("ai_provider", ""),
                _now(),
            ))
        await self._db.commit()

    async def get_pipeline(self, job_id: int) -> dict:
        """Return pipeline breakdown for a job."""
        async with self._db.execute(
            "SELECT * FROM pipeline_products WHERE job_id=? ORDER BY filter_stage, id",
            (job_id,)
        ) as cur:
            rows = await cur.fetchall()

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
        await self._db.execute("""
            INSERT OR IGNORE INTO products_raw
            (job_id, source, source_id, product_name, price, image_url, merchant, raw_data, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            job_id,
            p.get("source", ""),
            p.get("source_id", ""),
            p.get("title_translated") or p.get("title", ""),
            p.get("price_cny", 0),
            images[0] if images else "",
            p.get("merchant", ""),
            json.dumps(p),
            _now(),
        ))
        await self._db.commit()

    async def count_raw(self, job_id: int) -> int:
        async with self._db.execute(
            "SELECT COUNT(*) FROM products_raw WHERE job_id=?", (job_id,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    async def get_raw_products(self, job_id: int, limit: int = 2000) -> list:
        async with self._db.execute(
            "SELECT * FROM products_raw WHERE job_id=? ORDER BY id LIMIT ?",
            (job_id, limit),
        ) as cur:
            rows = await cur.fetchall()

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
        pipeline = []
        async with self._db.execute(
            "SELECT * FROM pipeline_products WHERE job_id=? ORDER BY id",
            (job_id,),
        ) as cur:
            pipeline = [dict(row) for row in await cur.fetchall()]

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
        async with self._db.execute(
            """INSERT INTO jobs (keywords_json, status, progress, scraped,
               after_basic, after_profit, after_dedup, after_ai, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (json.dumps(keywords), "queued", 0, 0, 0, 0, 0, 0, _now()),
        ) as cur:
            job_id = cur.lastrowid
        await self._db.commit()
        return job_id

    async def update_job(self, job_id: int, **kwargs):
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [job_id]
        await self._db.execute(f"UPDATE jobs SET {sets} WHERE id=?", vals)
        await self._db.commit()

    async def get_job(self, job_id: int) -> Optional[dict]:
        async with self._db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)) as cur:
            row = await cur.fetchone()
        return _row_to_job(row) if row else None

    async def get_jobs(self, limit: int = 10) -> list:
        async with self._db.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
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
        placeholders = ",".join("?" for _ in active_statuses)
        async with self._db.execute(
            f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY id DESC LIMIT 1",
            active_statuses,
        ) as cur:
            row = await cur.fetchone()
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
        placeholders = ",".join("?" for _ in active_statuses)
        cur = await self._db.execute(
            f"UPDATE jobs SET status='interrupted' WHERE status IN ({placeholders})",
            active_statuses,
        )
        await self._db.commit()
        return cur.rowcount or 0

    async def clear_scan_history(self) -> dict:
        counts = {}
        for table in ("pipeline_products", "products_raw", "jobs"):
            async with self._db.execute(f"SELECT COUNT(*) FROM {table}") as cur:
                row = await cur.fetchone()
            counts[table] = row[0] if row else 0
            await self._db.execute(f"DELETE FROM {table}")
        await self._db.commit()
        return counts

    # ── Settings ──────────────────────────────────────────────────────────────

    async def get_settings(self) -> dict:
        async with self._db.execute("SELECT key, value FROM settings") as cur:
            rows = await cur.fetchall()
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
            await self._db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (k, val)
            )
        await self._db.commit()

    # ── Comment reply log ─────────────────────────────────────────────────────

    async def has_replied_to_comment(self, comment_id: str) -> bool:
        async with self._db.execute(
            "SELECT id FROM comment_reply_log WHERE comment_id=?", (comment_id,)
        ) as cur:
            return await cur.fetchone() is not None

    async def log_comment_reply(self, comment_id: str, matched_rule: str, reply_type: str = "comment") -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO comment_reply_log (comment_id, reply_type, replied_at, matched_rule) VALUES (?,?,?,?)",
            (comment_id, reply_type, _now(), matched_rule),
        )
        await self._db.commit()

    async def get_comment_reply_log(self, limit: int = 50) -> list:
        async with self._db.execute(
            "SELECT * FROM comment_reply_log ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ── Stats ─────────────────────────────────────────────────────────────────


    async def get_analytics(self) -> dict:
        """Return analytics data for the analytics dashboard."""
        conn = self._db

        async with conn.execute("""
            SELECT stage, COUNT(*) as cnt FROM products GROUP BY stage
        """) as cur:
            stages_raw = await cur.fetchall()

        async with conn.execute("""
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
        """) as cur:
            score_dist = await cur.fetchall()

        async with conn.execute("""
            SELECT category, COUNT(*) as cnt FROM products
            WHERE category IS NOT NULL AND category != ''
            GROUP BY category ORDER BY cnt DESC LIMIT 10
        """) as cur:
            categories = await cur.fetchall()

        async with conn.execute("""
            SELECT rejection_reason, COUNT(*) as cnt FROM products
            WHERE stage = 'REJECTED' AND rejection_reason IS NOT NULL AND rejection_reason != ''
            GROUP BY rejection_reason ORDER BY cnt DESC LIMIT 8
        """) as cur:
            rejections = await cur.fetchall()

        async with conn.execute("""
            SELECT DATE(created_at) as day,
                   SUM(CASE WHEN stage IN ('REVIEWED','LIVE') THEN 1 ELSE 0 END) as approved,
                   SUM(CASE WHEN stage = 'REJECTED' THEN 1 ELSE 0 END) as rejected,
                   COUNT(*) as total
            FROM products
            WHERE created_at >= datetime('now', '-30 days')
            GROUP BY day ORDER BY day
        """) as cur:
            timeline = await cur.fetchall()

        async with conn.execute("""
            SELECT keyword,
                   COUNT(*) as total,
                   SUM(CASE WHEN stage IN ('REVIEWED','LIVE') THEN 1 ELSE 0 END) as approved,
                   ROUND(AVG(score), 1) as avg_score
            FROM products
            WHERE keyword IS NOT NULL AND keyword != ''
            GROUP BY keyword ORDER BY approved DESC, total DESC LIMIT 10
        """) as cur:
            keywords = await cur.fetchall()

        async with conn.execute("""
            SELECT ai_provider, COUNT(*) as cnt FROM products
            WHERE ai_provider IS NOT NULL AND ai_provider != ''
            GROUP BY ai_provider ORDER BY cnt DESC
        """) as cur:
            providers = await cur.fetchall()

        return {
            "stages":            [{"stage": r[0], "cnt": r[1]} for r in stages_raw],
            "score_distribution":[{"bucket": r[0], "cnt": r[1]} for r in score_dist],
            "categories":        [{"category": r[0], "cnt": r[1]} for r in categories],
            "top_rejections":    [{"reason": r[0], "cnt": r[1]} for r in rejections],
            "timeline":          [{"day": r[0], "approved": r[1], "rejected": r[2], "total": r[3]} for r in timeline],
            "keywords":          [{"keyword": r[0], "total": r[1], "approved": r[2], "avg_score": r[3]} for r in keywords],
            "ai_providers":      [{"provider": r[0], "cnt": r[1]} for r in providers],
        }

    async def get_rejected_sample(self, limit: int = 30) -> list:
        """Return a compact sample of rejected products for AI assistant context."""
        conn = self._db
        async with conn.execute("""
            SELECT id, title_translated, category, score, niche_fit, visual_appeal,
                   rejection_reason, keyword, orders, margin_pct
            FROM products
            WHERE stage = 'REJECTED'
            ORDER BY score DESC NULLS LAST
            LIMIT ?
        """, (limit,)) as cur:
            rows = await cur.fetchall()
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
            async with self._db.execute(
                "SELECT COUNT(*) FROM products WHERE stage=?", (stage,)
            ) as cur:
                row = await cur.fetchone()
            stats[stage] = row[0] if row else 0

        async with self._db.execute("SELECT COUNT(*) FROM jobs") as cur:
            row = await cur.fetchone()
        stats["total_jobs"] = row[0] if row else 0

        async with self._db.execute(
            "SELECT COUNT(*) FROM post_log WHERE posted_at > datetime('now','-7 days')"
        ) as cur:
            row = await cur.fetchone()
        stats["posted_7d"] = row[0] if row else 0

        async with self._db.execute(
            "SELECT AVG(margin_pct) FROM products WHERE stage='SCRAPED'"
        ) as cur:
            row = await cur.fetchone()
        stats["avg_margin_pending"] = round(row[0] or 0, 1)

        async with self._db.execute(
            "SELECT AVG(score) FROM products WHERE stage='SCRAPED'"
        ) as cur:
            row = await cur.fetchone()
        stats["avg_score_pending"] = round(row[0] or 0, 1)

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
    conn = db._db
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA cache_size=-64000")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id            INTEGER,
            source            TEXT,
            source_id         TEXT UNIQUE,
            title             TEXT,
            title_translated  TEXT,
            product_name      TEXT,
            price_cny         REAL,
            cost_eur          REAL,
            sell_price_eur    REAL,
            margin_pct        REAL,
            orders            INTEGER,
            rating            REAL,
            images_json       TEXT,
            url               TEXT,
            category          TEXT,
            keyword           TEXT,
            score             REAL,
            niche_fit         REAL,
            visual_appeal     REAL,
            trend_score       REAL,
            competition_score REAL DEFAULT 0,
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

    await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_stage ON products(stage)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)")

    # Safe migration for existing databases
    await _add_columns_if_missing(conn, "products", [
        ("competition_score", "REAL DEFAULT 0"),
        ("rejection_reason", "TEXT"),
        ("review_note", "TEXT"),
        ("approved_at", "TEXT"),
        ("rejected_at", "TEXT"),
        ("posted_at", "TEXT"),
        ("ai_provider", "TEXT DEFAULT ''"),
        ("description", "TEXT DEFAULT ''"),
        ("has_chinese_text", "INTEGER DEFAULT 0"),
        ("chinese_text_note", "TEXT DEFAULT ''"),
    ])

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            keywords_json TEXT,
            status       TEXT,
            progress     INTEGER DEFAULT 0,
            scraped      INTEGER DEFAULT 0,
            after_basic  INTEGER DEFAULT 0,
            after_profit INTEGER DEFAULT 0,
            after_dedup  INTEGER DEFAULT 0,
            after_ai     INTEGER DEFAULT 0,
            created_at   TEXT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS products_raw (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id       INTEGER,
            source       TEXT,
            source_id    TEXT,
            product_name TEXT,
            price        REAL,
            image_url    TEXT,
            merchant     TEXT,
            raw_data     TEXT,
            created_at   TEXT
        )
    """)
    await _migrate_products_raw_unique_per_job(conn)
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_products_raw_job_source ON products_raw(job_id, source_id) WHERE source_id <> ''"
    )

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS post_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            posted_at  TEXT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_products (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id       INTEGER,
            source_id    TEXT,
            title        TEXT,
            product_name TEXT DEFAULT '',
            image_url    TEXT,
            url          TEXT DEFAULT '',
            price_cny    REAL DEFAULT 0,
            cost_eur     REAL DEFAULT 0,
            sell_price_eur REAL DEFAULT 0,
            orders       INTEGER DEFAULT 0,
            rating       REAL DEFAULT 0,
            margin_pct   REAL DEFAULT 0,
            raw_score    REAL DEFAULT 0,
            filter_stage TEXT,
            filter_reason TEXT DEFAULT '',
            ai_score     REAL DEFAULT 0,
            ai_niche_fit REAL DEFAULT 0,
            ai_visual    REAL DEFAULT 0,
            trend_score  REAL DEFAULT 0,
            competition_score REAL DEFAULT 0,
            ai_provider  TEXT DEFAULT '',
            created_at   TEXT
        )
    """)
    await _add_columns_if_missing(conn, "pipeline_products", [
        ("product_name", "TEXT DEFAULT ''"),
        ("url", "TEXT DEFAULT ''"),
        ("cost_eur", "REAL DEFAULT 0"),
        ("sell_price_eur", "REAL DEFAULT 0"),
        ("rating", "REAL DEFAULT 0"),
        ("raw_score", "REAL DEFAULT 0"),
        ("trend_score", "REAL DEFAULT 0"),
        ("competition_score", "REAL DEFAULT 0"),
        ("ai_provider", "TEXT DEFAULT ''"),
    ])

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS comment_reply_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            comment_id   TEXT UNIQUE,
            reply_type   TEXT DEFAULT 'comment',
            replied_at   TEXT,
            matched_rule TEXT
        )
    """)
    await _add_columns_if_missing(conn, "comment_reply_log", [
        ("reply_type", "TEXT DEFAULT 'comment'"),
    ])

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
        await conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)",
            (k, json.dumps(v) if not isinstance(v, str) else v),
        )
    await conn.commit()


async def _add_columns_if_missing(conn, table: str, columns: list):
    async with conn.execute(f"PRAGMA table_info({table})") as cur:
        existing = {row[1] for row in await cur.fetchall()}
    for col_name, col_def in columns:
        if col_name not in existing:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
    await conn.commit()


async def _migrate_products_raw_unique_per_job(conn) -> None:
    async with conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='products_raw'"
    ) as cur:
        row = await cur.fetchone()
    table_sql = (row[0] if row else "") or ""
    if "source_id    TEXT UNIQUE" not in table_sql and "source_id TEXT UNIQUE" not in table_sql:
        return

    await conn.execute("ALTER TABLE products_raw RENAME TO products_raw_old")
    await conn.execute("""
        CREATE TABLE products_raw (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id       INTEGER,
            source       TEXT,
            source_id    TEXT,
            product_name TEXT,
            price        REAL,
            image_url    TEXT,
            merchant     TEXT,
            raw_data     TEXT,
            created_at   TEXT
        )
    """)
    await conn.execute("""
        INSERT OR IGNORE INTO products_raw
        (id, job_id, source, source_id, product_name, price, image_url, merchant, raw_data, created_at)
        SELECT id, job_id, source, source_id, product_name, price, image_url, merchant, raw_data, created_at
        FROM products_raw_old
    """)
    await conn.execute("DROP TABLE products_raw_old")
    await conn.commit()
