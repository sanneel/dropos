"""
Alibaba 1688 scraper — uses Apify 1688-scraper actor when token is provided,
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
    {"title_translated": "Wireless Bluetooth Earphones 5.0 Noise Cancel Long Battery", "price_cny": 28, "orders": 4521, "rating": 4.7, "category": "Electronics"},
    {"title_translated": "Magnetic Phone Stand Desktop Lazy Adjustable Holder", "price_cny": 12, "orders": 8234, "rating": 4.8, "category": "Phone Accessories"},
    {"title_translated": "Minimalist Ceramic Coffee Mug with Lid and Straw", "price_cny": 18, "orders": 3102, "rating": 4.9, "category": "Home"},
    {"title_translated": "LED USB Ambient Desk Night Light Touch Dimmer", "price_cny": 22, "orders": 6780, "rating": 4.6, "category": "Home Decor"},
    {"title_translated": "Vintage Leather Notebook Journal Diary Planner", "price_cny": 35, "orders": 2890, "rating": 4.8, "category": "Stationery"},
    {"title_translated": "Multi-Compartment Desktop Storage Box Organizer", "price_cny": 25, "orders": 5430, "rating": 4.7, "category": "Home"},
    {"title_translated": "Clear Silicone Phone Case Anti-drop Protective", "price_cny": 8, "orders": 12000, "rating": 4.5, "category": "Phone Cases"},
    {"title_translated": "Hand-Woven Cotton Tote Bag Women Shoulder Bag", "price_cny": 45, "orders": 1890, "rating": 4.8, "category": "Bags"},
    {"title_translated": "Luxury Aromatherapy Candle Gift Box Scented Set", "price_cny": 38, "orders": 3210, "rating": 4.9, "category": "Home Fragrance"},
    {"title_translated": "Dried Flower Shadow Box Photo Frame Wall Art", "price_cny": 42, "orders": 2100, "rating": 4.7, "category": "Home Decor"},
    {"title_translated": "Lightweight Foldable Travel Packing Cube Organizer", "price_cny": 15, "orders": 7650, "rating": 4.6, "category": "Travel"},
    {"title_translated": "Handcrafted Wooden Desktop Sculpture Art Decor", "price_cny": 29, "orders": 4320, "rating": 4.8, "category": "Home Decor"},
    {"title_translated": "Portable UV Sterilizer Box Phone Jewelry Cleaner", "price_cny": 58, "orders": 1750, "rating": 4.7, "category": "Electronics"},
    {"title_translated": "Boho Rattan Lampshade Pendant Light Bedroom Decor", "price_cny": 72, "orders": 980, "rating": 4.8, "category": "Home Decor"},
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
                    "https://api.apify.com/v2/acts/apify~1688-scraper/runs",
                    params={"token": token},
                    json={"keywords": [keyword], "maxResults": max_per_keyword},
                )
                if resp.status_code != 201:
                    log.warning("1688 Apify start failed '%s': %d — using mock", keyword, resp.status_code)
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
                        log.warning("1688 run %s %s for '%s' — using mock", run_id, status, keyword)
                        all_products.extend(_mock([keyword], max_per_keyword))
                        break
                else:
                    log.warning("1688 run timed out for '%s' — using mock", keyword)
                    all_products.extend(_mock([keyword], max_per_keyword))
                    continue

                items_resp = await client.get(
                    f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items",
                    params={"token": token, "limit": max_per_keyword},
                )
                for item in items_resp.json():
                    all_products.append({
                        "source": "1688",
                        "source_id": str(item.get("offerId", "")),
                        "title": item.get("title", ""),
                        "title_translated": item.get("titleEnglish", item.get("title", "")),
                        "price_cny": float(item.get("priceMin", item.get("price", 0)) or 0),
                        "orders": int(item.get("tradeCount", 0) or 0),
                        "rating": float(item.get("repurchaseRate", 4.5) or 4.5),
                        "images": item.get("images", []),
                        "url": item.get("productUrl", ""),
                        "category": item.get("category", ""),
                        "keyword": keyword,
                        "merchant": item.get("companyName", ""),
                    })
            except Exception as e:
                log.warning("1688 scrape failed for '%s': %s — using mock", keyword, e)
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
                "source": "1688_mock",
                "source_id": hashlib.md5(f"{kw}{s['title_translated']}".encode()).hexdigest()[:12],
                "images": [
                    f"https://picsum.photos/seed/{hashlib.md5(s['title_translated'].encode()).hexdigest()[:6]}/600/800"
                ],
                "url": "https://1688.com",
                "keyword": kw,
                "merchant": "1688 Mock Supplier",
            })
            out.append(p)
    return out
