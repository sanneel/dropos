"""
Taobao scraper — uses Apify taobao-scraper actor when token is provided,
falls back to a realistic mock dataset otherwise.
"""

import asyncio
import hashlib
import logging
import random
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_MOCK_PRODUCTS = [
    {"title_translated": "Crystal Glass Vase Nordic Minimalist Home Decor", "price_cny": 32, "orders": 5210, "rating": 4.8, "category": "Home Decor"},
    {"title_translated": "Aesthetic Marble Print Phone Case Protective", "price_cny": 9, "orders": 11200, "rating": 4.6, "category": "Phone Cases"},
    {"title_translated": "Scented Soy Wax Candle Gift Set Lavender Rose", "price_cny": 42, "orders": 3150, "rating": 4.9, "category": "Home Fragrance"},
    {"title_translated": "Women Shoulder Bag Woven Straw Beach Tote", "price_cny": 55, "orders": 2100, "rating": 4.7, "category": "Bags"},
    {"title_translated": "LED Fairy String Lights Bedroom Wall Decoration", "price_cny": 19, "orders": 9800, "rating": 4.7, "category": "Home Decor"},
    {"title_translated": "Minimalist Silent Wall Clock Living Room Decor", "price_cny": 48, "orders": 4320, "rating": 4.8, "category": "Home Decor"},
    {"title_translated": "Acrylic Makeup Organizer Cosmetic Storage Box", "price_cny": 28, "orders": 6700, "rating": 4.6, "category": "Home"},
    {"title_translated": "Cute Animal Plush Keychain Soft Toy Pendant", "price_cny": 7, "orders": 15000, "rating": 4.5, "category": "Accessories"},
    {"title_translated": "Gold Foil Luxury Greeting Card Birthday Wedding", "price_cny": 5, "orders": 22000, "rating": 4.9, "category": "Stationery"},
    {"title_translated": "Plant Propagation Station Glass Vase Boho Decor", "price_cny": 36, "orders": 1900, "rating": 4.8, "category": "Home Decor"},
    {"title_translated": "A5 Hardcover Dotted Notebook Bullet Journal Planner", "price_cny": 22, "orders": 8400, "rating": 4.7, "category": "Stationery"},
    {"title_translated": "Portable Bluetooth Mini Speaker Waterproof Outdoor", "price_cny": 65, "orders": 3800, "rating": 4.6, "category": "Electronics"},
    {"title_translated": "Macrame Wall Hanging Boho Bedroom Art Decor", "price_cny": 38, "orders": 2900, "rating": 4.8, "category": "Home Decor"},
    {"title_translated": "Ceramic Abstract Succulent Planter Pot Mini", "price_cny": 16, "orders": 7200, "rating": 4.7, "category": "Home Decor"},
]


async def scrape(keywords: list, max_per_keyword: int, token: Optional[str] = None) -> list:
    if token:
        return await _scrape_apify(keywords, max_per_keyword, token)
    return _mock(keywords, min(max_per_keyword, len(_MOCK_PRODUCTS)))


async def _scrape_apify(keywords: list, max_per_keyword: int, token: str) -> list:
    all_products: list = []
    async with httpx.AsyncClient(timeout=120) as client:
        for keyword in keywords:
            try:
                resp = await client.post(
                    "https://api.apify.com/v2/acts/apify~taobao-scraper/runs",
                    params={"token": token},
                    json={"keyword": keyword, "maxItems": max_per_keyword},
                )
                if resp.status_code != 201:
                    log.warning("Taobao Apify start failed '%s': %d — using mock", keyword, resp.status_code)
                    all_products.extend(_mock([keyword], max_per_keyword))
                    continue

                run_id = resp.json()["data"]["id"]
                for _ in range(60):
                    await asyncio.sleep(5)
                    sr = await client.get(
                        f"https://api.apify.com/v2/actor-runs/{run_id}",
                        params={"token": token},
                    )
                    status = sr.json()["data"]["status"]
                    if status == "SUCCEEDED":
                        break
                    if status in ("FAILED", "ABORTED"):
                        log.warning("Taobao run %s %s for '%s' — using mock", run_id, status, keyword)
                        all_products.extend(_mock([keyword], max_per_keyword))
                        break
                else:
                    log.warning("Taobao run timed out for '%s' — using mock", keyword)
                    all_products.extend(_mock([keyword], max_per_keyword))
                    continue

                items_resp = await client.get(
                    f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items",
                    params={"token": token, "limit": max_per_keyword},
                )
                for item in items_resp.json():
                    all_products.append({
                        "source": "taobao",
                        "source_id": "tb_" + str(item.get("itemId", "")),
                        "title": item.get("title", ""),
                        "title_translated": item.get("title", ""),
                        "price_cny": float(item.get("price", 0) or 0),
                        "orders": int(item.get("sold", 0) or 0),
                        "rating": float(item.get("rating", 4.5) or 4.5),
                        "images": [item["mainImage"]] if item.get("mainImage") else [],
                        "url": item.get("itemUrl", ""),
                        "category": item.get("category", ""),
                        "keyword": keyword,
                        "merchant": item.get("shopName", ""),
                    })
            except Exception as e:
                log.warning("Taobao scrape failed for '%s': %s — using mock", keyword, e)
                all_products.extend(_mock([keyword], max_per_keyword))

    return all_products


def _mock(keywords: list, count: int) -> list:
    out: list = []
    for kw in keywords:
        sample = random.sample(_MOCK_PRODUCTS, min(count, len(_MOCK_PRODUCTS)))
        for s in sample:
            p = dict(s)
            p["title"] = p["title_translated"]
            p.update({
                "source": "taobao_mock",
                "source_id": "tb_" + hashlib.md5(f"{kw}{s['title_translated']}".encode()).hexdigest()[:10],
                "images": [
                    f"https://picsum.photos/seed/tb{hashlib.md5(s['title_translated'].encode()).hexdigest()[:6]}/600/800"
                ],
                "url": "https://taobao.com",
                "keyword": kw,
                "merchant": "Mock Store",
            })
            out.append(p)
    return out
