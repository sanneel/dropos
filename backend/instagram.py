"""
Instagram posting module.
Stub implementation — replace with instagrapi or Buffer/Later API for production.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class PostResult:
    product_id: int
    status: str
    post_url: Optional[str] = None
    error: Optional[str] = None


async def post_product(product: dict) -> PostResult:
    """Simulate posting a single product to Instagram."""
    pid = product.get("id")
    caption = product.get("caption") or ""
    hashtags = product.get("hashtags") or []

    hashtag_str = " ".join(f"#{t}" for t in hashtags)
    full_caption = f"{caption}\n\n{hashtag_str}".strip()

    # Simulate network latency
    await asyncio.sleep(0.3)

    log.info(
        "Instagram post simulated: id=%s image=%s caption=%.60s...",
        pid,
        (product.get("images") or ["none"])[0][:60],
        full_caption,
    )

    return PostResult(
        product_id=pid,
        status="posted",
        post_url=f"https://instagram.com/p/mock_{pid}",
    )


async def post_batch(products: list) -> list[PostResult]:
    """Post multiple products sequentially (Instagram rate-limit safe)."""
    results: list[PostResult] = []
    for product in products:
        result = await post_product(product)
        results.append(result)
        if len(products) > 1:
            await asyncio.sleep(1.0)  # throttle between posts
    return results
