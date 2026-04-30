import aiosqlite
import json
from datetime import datetime
from typing import Optional

DB_PATH = "dropship.db"

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
             score, niche_fit, visual_appeal, trend_score,
             caption, hashtags_json, stage, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            p.get("caption", ""),
            json.dumps(p.get("hashtags", [])),
            "pending",
            datetime.utcnow().isoformat(),
        ))
        await self._db.commit()

    async def get_products(self, stage: str = "pending", limit: int = 50, offset: int = 0):
        async with self._db.execute(
            "SELECT * FROM products WHERE stage=? ORDER BY score DESC LIMIT ? OFFSET ?",
            (stage, limit, offset)
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_product(r) for r in rows]

    async def count_products(self, stage: str = "pending"):
        async with self._db.execute(
            "SELECT COUNT(*) FROM products WHERE stage=?", (stage,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    async def get_product(self, pid: int):
        async with self._db.execute(
            "SELECT * FROM products WHERE id=?", (pid,)
        ) as cur:
            row = await cur.fetchone()
        return _row_to_product(row) if row else None

    async def set_stage(self, pid: int, stage: str):
        await self._db.execute(
            "UPDATE products SET stage=? WHERE id=?", (stage, pid)
        )
        await self._db.commit()

    async def log_post(self, pid: int):
        await self._db.execute(
            "INSERT INTO post_log (product_id, posted_at) VALUES (?,?)",
            (pid, datetime.utcnow().isoformat())
        )
        await self._db.commit()

    # ── Jobs ──────────────────────────────────────────────────────────────────
    async def create_job(self, keywords: list) -> int:
        async with self._db.execute(
            """INSERT INTO jobs (keywords_json, status, progress, scraped,
               after_basic, after_profit, after_dedup, after_ai, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (json.dumps(keywords), "queued", 0, 0, 0, 0, 0, 0,
             datetime.utcnow().isoformat())
        ) as cur:
            job_id = cur.lastrowid
        await self._db.commit()
        return job_id

    async def update_job(self, job_id: int, **kwargs):
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [job_id]
        await self._db.execute(f"UPDATE jobs SET {sets} WHERE id=?", vals)
        await self._db.commit()

    async def get_job(self, job_id: int):
        async with self._db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)) as cur:
            row = await cur.fetchone()
        return _row_to_dict(row) if row else None

    async def get_jobs(self, limit: int = 10):
        async with self._db.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]

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
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                (k, val)
            )
        await self._db.commit()

    # ── Stats ─────────────────────────────────────────────────────────────────
    async def get_stats(self) -> dict:
        stats = {}
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
        stats["avg_margin"] = round(row[0] or 0, 1)

        return stats


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    d = dict(row)
    for k in ("keywords_json",):
        if k in d and d[k]:
            try:
                d[k.replace("_json", "")] = json.loads(d[k])
            except Exception:
                pass
    return d


def _row_to_product(row) -> dict:
    if row is None:
        return {}
    d = dict(row)
    for k in ("images_json", "hashtags_json"):
        if k in d and d[k]:
            try:
                d[k.replace("_json", "")] = json.loads(d[k])
                del d[k]
            except Exception:
                d[k.replace("_json", "")] = []
    return d


# Singleton
db = Database()


async def init_db():
    await db.connect()
    await db._db.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            source TEXT,
            source_id TEXT UNIQUE,
            title TEXT,
            title_translated TEXT,
            product_name TEXT,
            price_cny REAL,
            cost_eur REAL,
            sell_price_eur REAL,
            margin_pct REAL,
            orders INTEGER,
            rating REAL,
            images_json TEXT,
            url TEXT,
            category TEXT,
            keyword TEXT,
            score REAL,
            niche_fit REAL,
            visual_appeal REAL,
            trend_score REAL,
            caption TEXT,
            hashtags_json TEXT,
            stage TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)
    await db._db.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keywords_json TEXT,
            status TEXT,
            progress INTEGER DEFAULT 0,
            scraped INTEGER DEFAULT 0,
            after_basic INTEGER DEFAULT 0,
            after_profit INTEGER DEFAULT 0,
            after_dedup INTEGER DEFAULT 0,
            after_ai INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    await db._db.execute("""
        CREATE TABLE IF NOT EXISTS post_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            posted_at TEXT
        )
    """)
    await db._db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    # Default settings
    defaults = {
        "niche": "aesthetic lifestyle & home decor",
        "min_margin": 60.0,
        "min_score": 7.0,
        "min_orders": 100,
        "min_rating": 4.5,
        "sell_markup_low": 3.5,
        "sell_markup_mid": 2.8,
        "sell_markup_high": 2.2,
        "exchange_rate": 0.13,
        "apify_token": "",
        "anthropic_key": "",
        "instagram_username": "",
    }
    for k, v in defaults.items():
        await db._db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)",
            (k, json.dumps(v) if not isinstance(v, str) else v)
        )
    await db._db.commit()
