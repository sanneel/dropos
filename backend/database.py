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
             caption, hashtags_json, stage, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            json.dumps(p.get("hashtags", [])),
            "pending",
            _now(),
        ))
        await self._db.commit()

    async def get_products(
        self, stage: str = "pending", limit: int = 50, offset: int = 0, sort: str = "score"
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

    async def count_products(self, stage: str = "pending") -> int:
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

    async def set_stage(self, pid: int, stage: str, reason: str = None, note: str = None):
        ts_field = {
            "approved": "approved_at",
            "rejected": "rejected_at",
            "posted": "posted_at",
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
                (job_id, source_id, title, image_url, price_cny, orders, margin_pct,
                 filter_stage, filter_reason, ai_score, ai_niche_fit, ai_visual, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                r["job_id"], r["source_id"], r["title"], r["image_url"],
                r["price_cny"], r["orders"], r["margin_pct"],
                r["filter_stage"], r.get("filter_reason", ""),
                r.get("ai_score", 0), r.get("ai_niche_fit", 0), r.get("ai_visual", 0),
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

    async def get_stats(self) -> dict:
        stats: dict = {}
        for stage in ("pending", "approved", "posted", "rejected"):
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
            "SELECT AVG(margin_pct) FROM products WHERE stage='pending'"
        ) as cur:
            row = await cur.fetchone()
        stats["avg_margin_pending"] = round(row[0] or 0, 1)

        async with self._db.execute(
            "SELECT AVG(score) FROM products WHERE stage='pending'"
        ) as cur:
            row = await cur.fetchone()
        stats["avg_score_pending"] = round(row[0] or 0, 1)

        total_reviewed = stats["approved"] + stats["rejected"]
        stats["approval_rate"] = (
            round(stats["approved"] / total_reviewed * 100, 1) if total_reviewed else 0
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
            hashtags_json     TEXT,
            stage             TEXT DEFAULT 'pending',
            rejection_reason  TEXT,
            review_note       TEXT,
            approved_at       TEXT,
            rejected_at       TEXT,
            posted_at         TEXT,
            created_at        TEXT
        )
    """)

    # Safe migration for existing databases
    await _add_columns_if_missing(conn, "products", [
        ("competition_score", "REAL DEFAULT 0"),
        ("rejection_reason", "TEXT"),
        ("review_note", "TEXT"),
        ("approved_at", "TEXT"),
        ("rejected_at", "TEXT"),
        ("posted_at", "TEXT"),
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
            source_id    TEXT UNIQUE,
            product_name TEXT,
            price        REAL,
            image_url    TEXT,
            merchant     TEXT,
            raw_data     TEXT,
            created_at   TEXT
        )
    """)

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
            image_url    TEXT,
            price_cny    REAL DEFAULT 0,
            orders       INTEGER DEFAULT 0,
            margin_pct   REAL DEFAULT 0,
            filter_stage TEXT,
            filter_reason TEXT DEFAULT '',
            ai_score     REAL DEFAULT 0,
            ai_niche_fit REAL DEFAULT 0,
            ai_visual    REAL DEFAULT 0,
            created_at   TEXT
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
        "cssbuy_username": "",
        "cssbuy_password": "",
        "cssbuy_source": "1688",
        "captcha_2captcha_key": "",
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
