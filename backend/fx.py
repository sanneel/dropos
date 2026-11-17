"""
Lari exchange rates from the National Bank of Georgia's public daily feed.

Used by link import: a product pasted from any shop can be priced in USD, EUR,
TRY… and has to become a cost in ₾. No key is needed. Rates are cached for a
few hours; until the first successful download rough built-in values are used
and reported as approximate.
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

log = logging.getLogger(__name__)

NBG_URL = "https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json/"
_MAX_AGE = 6 * 3600

# Lari per one unit. Only a stand-in until the feed answers.
_FALLBACK = {
    "USD": 2.7, "EUR": 3.1, "GBP": 3.6, "TRY": 0.065, "CNY": 0.38, "RUB": 0.033,
    "AED": 0.735, "PLN": 0.73, "UAH": 0.065, "AMD": 0.007, "AZN": 1.59, "JPY": 0.018,
    "CAD": 1.95, "AUD": 1.78, "CHF": 3.3, "KZT": 0.0052,
}

_state = {"rates": dict(_FALLBACK), "date": None, "fetched_at": 0.0, "approximate": True}
_lock = asyncio.Lock()
_transport = None  # tests swap in an httpx.MockTransport


async def refresh() -> dict:
    async with _lock:
        try:
            async with httpx.AsyncClient(timeout=8, transport=_transport) as client:
                resp = await client.get(NBG_URL)
            resp.raise_for_status()
            data = resp.json()
            day = data[0] if isinstance(data, list) else data
            rates = {}
            for row in day.get("currencies") or []:
                per_unit = float(row.get("rate") or 0) / (float(row.get("quantity") or 1) or 1)
                if row.get("code") and per_unit > 0:
                    rates[str(row["code"]).upper()] = per_unit
            if not rates.get("USD"):
                raise ValueError("NBG reply had no USD rate")
            _state.update(rates=rates, date=str(day.get("date") or "")[:10] or None,
                          fetched_at=time.time(), approximate=False)
        except Exception as exc:
            # Try again in half an hour rather than on every import.
            _state["fetched_at"] = time.time() - _MAX_AGE + 1800
            log.warning("NBG rates unavailable (%s) — keeping %s rates", exc,
                        "approximate" if _state["approximate"] else "the last downloaded")
    return _state


async def get_rates() -> dict:
    """{'rates': {CODE: lari per unit}, 'date': 'YYYY-MM-DD' | None, 'approximate': bool}"""
    if time.time() - _state["fetched_at"] > _MAX_AGE:
        await refresh()
    return _state


def to_gel(amount, currency: Optional[str], rates: dict) -> Optional[float]:
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return None
    if value <= 0 or not currency:
        return None
    if currency == "GEL":
        return round(value, 2)
    rate = (rates or {}).get(currency)
    return round(value * rate, 2) if rate and rate > 0 else None
