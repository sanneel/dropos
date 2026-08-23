"""
Keyword Lab — per-brand keyword intelligence.

Three jobs:
  1. score()   — turn raw per-keyword results into one performance number
  2. select()  — pick which keywords the next scan should use
                 (exploit proven winners, explore untested ones)
  3. generate() — ask Gemini for new keywords, feeding it the brand persona and
                 the current winners so it can copy the *patterns* that work
                 ("formulas": e.g. "matching <item> couple", "<occasion> gift
                 for girlfriend") and retire-worthy losers to avoid.

Performance formula (per keyword, needs >= MIN_SAMPLE scored products):
    approval_rate = approved / scored
    post_rate     = posted   / max(approved, 1)
    score = approval_rate * 0.55 + post_rate * 0.25 + (avg_ai_score / 10) * 0.20
Untested keywords have score None — they are explored, not ranked.
"""

import json
import logging
import re
from datetime import datetime, timezone

import httpx

from config.runtime import get_config

log = logging.getLogger(__name__)

MIN_SAMPLE = 5          # scored products needed before the formula judges a keyword
EXPLORE_RATIO = 0.34    # ~1/3 of every scan slot goes to untested keywords
LOSER_SCORE = 0.08      # below this (with enough sample) a keyword is a proven loser
GENERATE_BATCH = 10     # keywords per AI generation run


# ── 1. Performance ────────────────────────────────────────────────────────────

def score(perf: dict) -> float | None:
    """perf = {"scraped","scored","approved","posted","avg_score"} → 0..1 or None."""
    scored = perf.get("scored", 0)
    if scored < MIN_SAMPLE:
        return None
    approval_rate = perf.get("approved", 0) / scored
    post_rate = perf.get("posted", 0) / max(perf.get("approved", 0), 1)
    avg = (perf.get("avg_score") or 0) / 10
    return round(approval_rate * 0.55 + post_rate * 0.25 + avg * 0.20, 3)


def annotate(keywords: list, perf_map: dict) -> list:
    """Attach performance + score to keyword rows (keyword rows from brand_keywords)."""
    out = []
    for k in keywords:
        p = perf_map.get(str(k["keyword"]).lower(), {"scraped": 0, "scored": 0, "approved": 0, "posted": 0, "avg_score": 0})
        s = score(p)
        out.append({**k, **p, "perf_score": s,
                    "tested": p["scored"] >= MIN_SAMPLE,
                    "loser": s is not None and s < LOSER_SCORE})
    return out


# ── 2. Selection for the next scan ────────────────────────────────────────────

def select(keywords: list, perf_map: dict, limit: int) -> list:
    """
    Pick up to `limit` active keywords for a scan:
      - winners first (highest perf score, least recently scanned)
      - ~1/3 of slots for untested keywords (newest first — AI candidates get tried)
      - proven losers are skipped entirely
    Returns keyword strings.
    """
    rows = [k for k in annotate(keywords, perf_map) if k.get("status") == "active"]
    if not rows:
        return []
    explore_slots = max(1, round(limit * EXPLORE_RATIO)) if len(rows) > limit else limit
    untested = sorted([k for k in rows if not k["tested"]], key=lambda k: k.get("id", 0), reverse=True)
    winners = sorted([k for k in rows if k["tested"] and not k["loser"]],
                     key=lambda k: (-(k["perf_score"] or 0), str(k.get("last_scanned_at") or "")))
    picked, seen = [], set()

    def take(pool, n):
        for k in pool:
            if len(picked) >= limit or n <= 0:
                return
            kw = str(k["keyword"]).lower()
            if kw in seen:
                continue
            seen.add(kw)
            picked.append(kw)
            n -= 1

    take(untested, explore_slots)
    take(winners, limit - len(picked))
    take(untested, limit - len(picked))   # fill leftovers with more untested
    return picked


# ── 3. AI generation ──────────────────────────────────────────────────────────

_GEN_PROMPT = """You generate product-search keywords for sourcing products on 1688 / Taobao
(through the CSSBuy agent). Keywords are typed into a product search box, so they must be
plain product searches in ENGLISH: 2–5 words, lowercase, no brand names, no hashtags,
no adjectives-only phrases. Good: "matching couple bracelet", "star projector lamp".
Bad: "romantic vibes", "gifts", "Tskvili necklace".

BRAND / MARKET:
- Name: {name}
- Niche: {niche}
- Audience: {audience}
- Sell price range: {price_min}–{price_max} GEL (source cost must be far below this)
- Example products that fit: {examples}

WHAT ALREADY WORKS — keywords ranked by real results (approval rate of scraped products,
how many got posted). Study the *patterns* (item types, "matching/couple/for girlfriend/for
boyfriend" formulas, occasions) and generate more keywords that follow the same formulas:
{winners}

WHAT FAILED — do not generate anything similar to these:
{losers}

ALREADY IN THE POOL — never repeat any of these (or trivial variations):
{existing}

Generate exactly {n} NEW keywords: ~70% following the winning formulas with new item types
or occasions, ~30% exploring adjacent product ideas that fit the niche.
Return ONLY a JSON array of strings."""

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


async def generate(brand: dict, keywords: list, perf_map: dict, settings: dict, n: int = GENERATE_BATCH) -> list:
    """Ask the content model for new keywords. Returns new keyword strings (not yet saved)."""
    import content_ai
    if not content_ai.content_ready(settings):
        return []
    rows = annotate(keywords, perf_map)
    winners = sorted([k for k in rows if k["tested"] and not k["loser"]], key=lambda k: -(k["perf_score"] or 0))[:8]
    losers = [k for k in rows if k["loser"]][:8]
    existing = [str(k["keyword"]) for k in rows]

    def fmt(k):
        ar = f"{k['approved']}/{k['scored']} approved" if k["scored"] else "untested"
        return f"- \"{k['keyword']}\" ({ar}, {k['posted']} posted, avg score {k['avg_score']})"

    prompt = _GEN_PROMPT.format(
        name=brand.get("name") or "", niche=brand.get("niche") or "", audience=brand.get("target_audience") or "",
        price_min=int(brand.get("sell_price_min") or 40), price_max=int(brand.get("sell_price_max") or 119),
        examples=(brand.get("example_products") or "")[:400],
        winners="\n".join(fmt(k) for k in winners) or "(no tested winners yet — rely on the niche and examples)",
        losers="\n".join(f"- \"{k['keyword']}\"" for k in losers) or "(none yet)",
        existing=", ".join(existing[:120]) or "(none)",
        n=n,
    )
    import content_ai
    try:
        raw = await content_ai.complete_json("You generate product-sourcing search keywords.", prompt, settings, max_tokens=800)
        if isinstance(raw, dict):   # some models wrap the array: {"keywords": [...]}
            raw = raw.get("keywords") or next((v for v in raw.values() if isinstance(v, list)), None)
        if not isinstance(raw, list):
            return []
        seen = {e.lower() for e in existing}
        out = []
        for kw in raw:
            kw = re.sub(r"[^a-z0-9 \-]", "", str(kw).strip().lower())
            kw = re.sub(r"\s+", " ", kw).strip()
            if kw and 2 <= len(kw.split()) <= 6 and kw not in seen:
                seen.add(kw)
                out.append(kw)
        return out[:n]
    except Exception as exc:
        log.warning("keyword generation failed: %s", exc)
        return []


def generation_due(brand: dict, keywords: list, perf_map: dict) -> bool:
    """Autopilot: generate when the untested pool runs dry or weekly refresh is due."""
    if not brand.get("auto_keywords_enabled", 1):
        return False
    rows = [k for k in annotate(keywords, perf_map) if k.get("status") == "active"]
    untested = sum(1 for k in rows if not k["tested"])
    if untested >= 3:
        # still enough to explore — only refresh weekly
        last = brand.get("last_keywords_generated_at")
        if not last:
            return False
        try:
            last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - last_dt).days >= 7
        except Exception:
            return False
    return True
