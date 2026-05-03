"""
Run CSSBuy scraping locally and upload the scraped data to the hosted website.

Required env:
  WEBSITE_URL=https://your-site.example.com
  INGEST_API_TOKEN=your-shared-token
  CSSBUY_USERNAME=your-cssbuy-login
  CSSBUY_PASSWORD=your-cssbuy-password

Optional env:
  SCAN_KEYWORDS=keyword one,keyword two
  MAX_PER_KEYWORD=100
  CSSBUY_SOURCE=1688|taobao|both
  CAPTCHA_2CAPTCHA_KEY=...
"""

import argparse
import asyncio
import os
import sys
from typing import Sequence

import httpx

sys.path.insert(0, os.path.dirname(__file__))

import scraper_cssbuy


def _csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape CSSBuy locally and upload products to DropOS.")
    parser.add_argument("--website-url", default=os.getenv("WEBSITE_URL", ""), help="Hosted DropOS website URL")
    parser.add_argument("--token", default=os.getenv("INGEST_API_TOKEN", ""), help="Shared ingest API token")
    parser.add_argument("--keywords", nargs="*", default=None, help="Keywords to scan")
    parser.add_argument("--max-per-keyword", type=int, default=int(os.getenv("MAX_PER_KEYWORD", "100")))
    parser.add_argument("--source", default=os.getenv("CSSBUY_SOURCE", "1688"), choices=("1688", "taobao", "both"))
    parser.add_argument("--username", default=os.getenv("CSSBUY_USERNAME", ""))
    parser.add_argument("--password", default=os.getenv("CSSBUY_PASSWORD", ""))
    parser.add_argument("--captcha-key", default=os.getenv("CAPTCHA_2CAPTCHA_KEY", ""))
    return parser


async def _upload(website_url: str, token: str, payload: dict) -> dict:
    url = website_url.rstrip("/") + "/api/ingest/products"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        return response.json()


async def main(argv: Sequence[str] | None = None) -> int:
    args = _arg_parser().parse_args(argv)
    env_keywords = _csv(os.getenv("SCAN_KEYWORDS", ""))
    keywords = args.keywords if args.keywords is not None else env_keywords

    missing = []
    if not args.website_url:
        missing.append("WEBSITE_URL")
    if not args.token:
        missing.append("INGEST_API_TOKEN")
    if not args.username:
        missing.append("CSSBUY_USERNAME")
    if not args.password:
        missing.append("CSSBUY_PASSWORD")
    if not keywords:
        missing.append("SCAN_KEYWORDS or --keywords")
    if missing:
        print("Missing required setting(s): " + ", ".join(missing), file=sys.stderr)
        return 2

    print(f"Scraping {len(keywords)} keyword(s) from CSSBuy source={args.source} max={args.max_per_keyword}")
    products = await scraper_cssbuy.scrape(
        list(keywords),
        args.max_per_keyword,
        username=args.username,
        password=args.password,
        captcha_key=args.captcha_key,
        source=args.source,
    )
    print(f"Scraped {len(products)} product(s)")
    if not products:
        return 1

    result = await _upload(
        args.website_url,
        args.token,
        {"keywords": list(keywords), "source": args.source, "products": products},
    )
    print(f"Uploaded to website: job #{result.get('job_id')} ({result.get('products')} products)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
