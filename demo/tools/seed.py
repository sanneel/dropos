"""Fill an empty DropOS database with presentation data and write the product images.

    DATABASE_URL=postgresql://... python demo/tools/seed.py

Only for building the static demo (see demo/README.md) — never run it against a real install.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMO.parent / "backend"))

from database import db, init_db  # noqa: E402

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


# name, emoji, two gradient colours, keyword, price CNY, sell EUR, score, stage
PRODUCTS = [
    ("Heart-handle couple mugs", "☕", "#ff9a9e", "#fad0c4", "couple mugs", 18, 39, 9.1, "LIVE"),
    ("Custom photo moon lamp", "🌙", "#a18cd1", "#fbc2eb", "moon lamp gift", 32, 59, 8.9, "LIVE"),
    ("Rose in a glass dome", "🌹", "#f5576c", "#f093fb", "eternal rose", 26, 49, 8.7, "LIVE"),
    ("Matching magnetic bracelets", "💞", "#fbc2eb", "#a6c1ee", "couple bracelets", 9, 29, 8.6, "LIVE"),
    ("Long-distance touch lamps", "💡", "#f6d365", "#fda085", "long distance gift", 58, 89, 9.3, "REVIEWED"),
    ("Starry night map frame", "🌌", "#30cfd0", "#330867", "star map", 22, 45, 8.8, "REVIEWED"),
    ("Engraved heart necklace", "💎", "#e0c3fc", "#8ec5fc", "engraved necklace", 15, 35, 8.5, "REVIEWED"),
    ("Love letters in a jar", "💌", "#ffecd2", "#fcb69f", "love jar", 12, 29, 8.2, "REVIEWED"),
    ("Couple puzzle keychains", "🔑", "#84fab0", "#8fd3f4", "couple keychain", 6, 19, 7.9, "REVIEWED"),
    ("Giant teddy with heart", "🧸", "#fccb90", "#d57eeb", "teddy bear gift", 40, 69, 7.4, "ENRICHED"),
    ("Polaroid memory album", "📸", "#fdfbfb", "#ebedee", "photo album couple", 20, 39, 7.1, "ENRICHED"),
    ("Heart scented candle set", "🕯️", "#ff9a9e", "#fecfef", "scented candle", 14, 29, 6.9, "ENRICHED"),
    ("His & hers wine glasses", "🥂", "#cfd9df", "#e2ebf0", "wine glasses couple", 25, 45, 6.6, "ENRICHED"),
    ("Matching couple hoodies", "👕", "#a1c4fd", "#c2e9fb", "couple hoodies", 48, 79, 7.6, "TEXT_REMOVAL"),
    ("Couple phone cases", "📱", "#d4fc79", "#96e6a1", "couple phone case", 8, 22, 7.2, "TEXT_REMOVAL"),
    ("Fuzzy couple socks", "🧦", "#e6dee9", "#bdc2e8", "couple socks", 5, 15, 4.8, "REJECTED"),
    ("Plastic heart balloons", "🎈", "#f43b47", "#453a94", "romantic decor", 3, 12, 3.9, "REJECTED"),
    ("Couple watch gift box", "⌚", "#c79081", "#dfa579", "couple watch", 65, 99, 8.0, "ENRICHED"),
]

VERDICT = lambda s: "STRONG_BUY" if s >= 8.5 else "BUY" if s >= 7 else "MAYBE" if s >= 5.5 else "SKIP"


def svg(emoji: str, c1: str, c2: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 600" width="600" height="600">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient>
<radialGradient id="s" cx=".5" cy=".85" r=".35"><stop offset="0" stop-color="#000" stop-opacity=".18"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient></defs>
<rect width="600" height="600" fill="url(#g)"/><ellipse cx="300" cy="470" rx="190" ry="40" fill="url(#s)"/>
<text x="300" y="350" font-size="260" text-anchor="middle" dominant-baseline="middle">{emoji}</text>
</svg>"""


async def main():
    await init_db()
    for t in ("products", "jobs", "pipeline_products", "brands", "brand_keywords", "activity_log",
              "inbox_messages", "post_log", "products_raw", "comment_reply_log", "ai_recommendations"):
        await db.execute(f"TRUNCATE {t} RESTART IDENTITY CASCADE")

    couple = await db.fetchval(
        """INSERT INTO brands (name, slug, niche, target_audience, example_products, created_at)
           VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
        "Tskvili — couple gifts", "tskvili",
        "Romantic gifts for couples: anniversaries, Valentine's, long-distance love",
        "Couples 18–35 in Georgia shopping for a meaningful gift",
        "moon lamps, couple mugs, star maps, eternal roses", ago(days=40))
    home = await db.fetchval(
        """INSERT INTO brands (name, slug, niche, target_audience, example_products, created_at)
           VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
        "Cozy home", "cozy-home", "Warm, aesthetic home decor under €60",
        "Young renters decorating their first flat", "candles, lamps, blankets", ago(days=12))

    keywords = sorted({p[4] for p in PRODUCTS})
    for i, kw in enumerate(keywords):
        await db.execute(
            """INSERT INTO brand_keywords (brand_id, keyword, source, status, created_at, last_scanned_at, scans)
               VALUES ($1,$2,$3,'active',$4,$5,$6)""",
            couple, kw, "ai" if i % 3 == 0 else "manual", ago(days=30 - i), ago(hours=3 + i * 5), 2 + i % 5)
    for kw in ("aesthetic lamp", "knit blanket", "ceramic vase", "candle holder"):
        await db.execute(
            "INSERT INTO brand_keywords (brand_id, keyword, source, created_at, scans) VALUES ($1,$2,'ai',$3,1)",
            home, kw, ago(days=10))

    jobs = []
    for i, (scraped, basic, profit, dedup, ai) in enumerate([(86, 61, 44, 39, 14), (72, 50, 37, 30, 11),
                                                            (95, 70, 52, 45, 17), (64, 48, 33, 29, 9)]):
        jid = await db.fetchval(
            """INSERT INTO jobs (keywords_json, status, progress, scraped, after_basic, after_profit, after_dedup,
                                 after_ai, created_at, brand_id)
               VALUES ($1,'DONE',100,$2,$3,$4,$5,$6,$7,$8) RETURNING id""",
            json.dumps(keywords[i * 3:i * 3 + 4]), scraped, basic, profit, dedup, ai, ago(hours=2 + i * 26), couple)
        jobs.append(jid)

    for n, (name, emoji, c1, c2, kw, cny, sell, score, stage) in enumerate(PRODUCTS, 1):
        (DEMO / "img" / f"p{n}.svg").write_text(svg(emoji, c1, c2), encoding="utf-8")
        cost = round(cny * 0.13 + 4.5, 2)
        margin = round((sell - cost) / sell * 100, 1)
        created = ago(hours=n * 7)
        caption = (f"{emoji} {name} — the gift that says it without words. "
                   f"Order in DM 💌 Delivery all over Georgia 🇬🇪")
        await db.execute(
            """INSERT INTO products (job_id, source, source_id, title, title_translated, product_name, price_cny,
                 cost_eur, sell_price_eur, margin_pct, orders, rating, images_json, url, category, keyword, score,
                 niche_fit, visual_appeal, trend_score, competition_score, caption, description, hashtags_json,
                 ai_provider, has_chinese_text, chinese_text_note, stage, rejection_reason, approved_at, rejected_at,
                 posted_at, created_at, audience, instagram_url, composite_score, verdict, product_tier, confidence,
                 viral_angle, emotional_hook, cute_appeal, giftability, brand_id)
               VALUES ($1,'1688',$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'couple gifts',$14,$15,$16,$17,$18,$19,$20,
                 $21,$22,'gemini',$23,$24,$25,$26,$27,$28,$29,$30,'couples',$31,$32,$33,$34,$35,$36,$37,$38,$39,$40)""",
            jobs[n % 4], f"demo-{n}", name, name, name, float(cny), cost, float(sell), margin,
            300 + n * 137 % 2400, round(4.5 + (n % 5) / 10, 1), json.dumps([f"/demo-img/p{n}.svg"]),
            f"https://detail.1688.com/offer/demo{n}.html", kw, score,
            min(10, score + 0.4), min(10, score + 0.2), round(score - 0.6, 1), round(10 - score, 1),
            caption, f"{name}. A best-selling gift for couples, packed in a gift box.",
            json.dumps(["#tskvili", "#couplegifts", "#giftideas", "#love", "#georgia"]),
            1 if stage == "TEXT_REMOVAL" else 0,
            "Chinese brand text on the packaging" if stage == "TEXT_REMOVAL" else "",
            stage, "Low perceived value — looks cheap in photos" if stage == "REJECTED" else None,
            ago(hours=n * 5) if stage in ("REVIEWED", "LIVE") else None,
            ago(hours=n * 4) if stage == "REJECTED" else None,
            ago(hours=n * 9) if stage == "LIVE" else None, created,
            f"https://www.instagram.com/p/demo{n}/" if stage == "LIVE" else "",
            score, VERDICT(score), "hero" if score >= 8.5 else "core", 0.82,
            "Before/after reaction video of the partner opening it", "Shows you remembered the little things",
            min(10, score + 0.3), min(10, score + 0.5), couple)
        if stage == "LIVE":
            await db.execute("INSERT INTO post_log (product_id, posted_at) VALUES ($1,$2)", n, ago(hours=n * 9))

    stages = ["ai_pass"] * 5 + ["ai_reject"] * 3 + ["score_reject"] * 2 + ["dedup_reject"] * 2 + \
             ["profit_reject"] * 3 + ["basic_reject"] * 3
    reasons = {"ai_reject": "AI: weak gift appeal", "score_reject": "Rule score below 5",
               "dedup_reject": "Already in catalogue", "profit_reject": "Margin under 45%",
               "basic_reject": "Fewer than 50 orders"}
    for i, st in enumerate(stages):
        p = PRODUCTS[i % len(PRODUCTS)]
        await db.execute(
            """INSERT INTO pipeline_products (job_id, source_id, title, product_name, image_url, price_cny, cost_eur,
                 sell_price_eur, orders, rating, margin_pct, raw_score, filter_stage, filter_reason, ai_score,
                 ai_provider, created_at)
               VALUES ($1,$2,$3,$3,$4,$5,$6,$7,$8,4.7,$9,$10,$11,$12,$13,'gemini',$14)""",
            jobs[0], f"pipe-{i}", p[0], f"/demo-img/p{i % len(PRODUCTS) + 1}.svg", float(p[5]),
            round(p[5] * 0.13 + 4.5, 2), float(p[6]), 200 + i * 41, 62.0 - i, 7.5 - i * 0.2, st,
            reasons.get(st, ""), p[7] if st.startswith("ai") else 0.0, ago(hours=2))

    events = [
        ("posted", "Posted “Heart-handle couple mugs” to Instagram", 1, dict(minutes=12)),
        ("lead_received", "Possible order from @nino.k: “how much is the moon lamp? 😍”", 2, dict(minutes=25)),
        ("reply_sent", "Auto-replied to @giorgi_b with price and delivery info", None, dict(minutes=26)),
        ("auto_approved", "Auto-approved “Long-distance touch lamps” (9.3 · STRONG_BUY)", 5, dict(minutes=48)),
        ("image_cleaned", "Removed Chinese text from “Starry night map frame”", 6, dict(hours=1)),
        ("needs_review", "“Giant teddy with heart” needs your decision (7.4)", 10, dict(hours=1, minutes=10)),
        ("scan_done", "Scan finished: 86 found → 14 passed AI curation", None, dict(hours=2)),
        ("scan_started", "Scan started for Tskvili — couple gifts (4 keywords)", None, dict(hours=2, minutes=6)),
        ("auto_rejected", "Auto-rejected “Plastic heart balloons” (3.9)", 17, dict(hours=3)),
        ("posted", "Posted “Custom photo moon lamp” to Instagram", 2, dict(hours=18)),
        ("keywords_generated", "AI added 6 new keywords to Tskvili from winning patterns", None, dict(days=1)),
        ("image_clean_failed", "Couldn't clean the photos of “Couple phone cases” — check manually", 15, dict(days=1, hours=2)),
    ]
    for kind, msg, pid, delta in events:
        level = "error" if "failed" in kind else "info"
        await db.execute("INSERT INTO activity_log (ts, kind, level, message, product_id) VALUES ($1,$2,$3,$4,$5)",
                         ago(**delta), kind, level, msg, pid)

    inbox = [
        ("comment", "nino.k", "რა ღირს მთვარის ლამპა? 😍", 1, "Hi! It's 59 € with delivery 💌 We sent you a DM", dict(minutes=25)),
        ("dm", "giorgi_b", "Can I order the touch lamps for Saturday?", 1, None, dict(minutes=40)),
        ("dm", "mariam.gelashvili", "ფოტოს დაბეჭდვაც შეიძლება ლამპაზე?", 1, None, dict(hours=2)),
        ("comment", "luka_tb", "So cute 😍😍", 0, "Thank you! ❤️", dict(hours=3)),
        ("comment", "ana.tskhovrebova", "Do you deliver to Batumi?", 1, "Yes — all over Georgia in 2–3 days 🚚", dict(hours=5)),
        ("comment", "dato.m", "🔥🔥", 0, None, dict(hours=8)),
    ]
    for i, (kind, who, text, lead, reply, delta) in enumerate(inbox):
        await db.execute(
            """INSERT INTO inbox_messages (external_id, kind, sender_id, sender_name, text, media_id, is_lead,
                 auto_reply, handled, received_at) VALUES ($1,$2,$3,$4,$5,'m1',$6,$7,$8,$9)""",
            f"demo-{i}", kind, who, who, text, lead, reply, 1 if i >= 4 else 0, ago(**delta))

    await db.update_settings({
        "autopilot_enabled": True, "auto_scan_enabled": True, "post_schedule_enabled": True,
        "auto_clean_images": True, "auto_approve_min_score": 8.5, "max_posts_per_day": 3,
        "post_times": ["12:30", "19:00", "21:30"], "gemini_key": "demo-key-not-real",
        "clipdrop_key": "demo-key-not-real", "instagram_access_token": "demo-token-not-real",
        "instagram_user_id": "17841400000000000", "scan_keywords": keywords[:6],
        "cssbuy_username": "tskvili.shop", "cssbuy_password": "demo-not-real",
        "public_base_url": "https://tskvili.example", "instagram_auto_reply_enabled": True,
        "instagram_dm_reply_enabled": True,
        "instagram_reply_rules": [{"keywords": ["price", "ფასი", "რა ღირს"], "reply": "Sent you the price in DM 💌"},
                                  {"keywords": ["delivery", "მიწოდება"], "reply": "We deliver all over Georgia in 2–3 days 🚚"}],
        "instagram_dm_rules": [{"keywords": ["order", "შეკვეთა"], "reply": "Great choice! Send your address and phone 📦"}],
    })
    await db.close()
    print(f"seeded {len(PRODUCTS)} products, images in {DEMO / 'img'}")


asyncio.run(main())
