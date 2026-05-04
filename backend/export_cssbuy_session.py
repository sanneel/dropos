"""
Open CSSBuy in a visible browser, let a human pass verification/login, then
export Playwright storage_state JSON for the CSSBUY_SESSION_JSON Railway var.
"""

import argparse
import asyncio
import json
from pathlib import Path


BASE_URL = "https://www.cssbuy.com"
DEFAULT_OUTPUT = Path(__file__).with_name("cssbuy_session.json")


def _cookie_names(storage: dict) -> set[str]:
    return {cookie.get("name", "") for cookie in storage.get("cookies", [])}


async def export_session(output: Path, url: str, keep_open: bool) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise SystemExit(
            "Playwright is not installed. Run: pip install -r backend/requirements.txt"
        ) from exc

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )
        context = await browser.new_context(viewport=None)
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)

        print("\nA browser window is open.")
        print("1. Manually pass Cloudflare verification if shown.")
        print("2. Log in to CSSBuy if needed.")
        print("3. Visit the product search page once if you want to warm up cookies.")
        print("4. Come back here and press Enter when CSSBuy is usable.\n")
        input("Press Enter to export CSSBuy session JSON...")

        storage = await context.storage_state()
        output.write_text(json.dumps(storage, separators=(",", ":")), encoding="utf-8")

        names = _cookie_names(storage)
        print(f"\nSaved: {output}")
        print(f"Cookies captured: {', '.join(sorted(names)) or '(none)'}")
        if "cf_clearance" not in names:
            print("Warning: no cf_clearance cookie was captured. Cloudflare may still challenge Railway.")
        if "loginauth" not in names and "laravel_session" not in names:
            print("Warning: no obvious CSSBuy login/session cookie was captured.")

        print("\nPaste this full value into Railway as CSSBUY_SESSION_JSON:")
        print(output.read_text(encoding="utf-8"))

        if keep_open:
            print("\nBrowser left open. Press Enter to close it.")
            input()
        await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export CSSBuy Playwright session JSON.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Where to save the session JSON.")
    parser.add_argument("--url", default=f"{BASE_URL}/productlist?keyWork=romantic%20gift", help="Initial URL to open.")
    parser.add_argument("--keep-open", action="store_true", help="Keep browser open after export until Enter.")
    args = parser.parse_args()

    asyncio.run(export_session(Path(args.output), args.url, args.keep_open))


if __name__ == "__main__":
    main()
