import json
import os
from typing import Any, Dict

SENSITIVE_KEYS = {
    "apify_token",
    "anthropic_key",
    "gemini_key",
    "groq_key",
    "instagram_access_token",
    "instagram_webhook_token",
    "cssbuy_password",
    "captcha_2captcha_key",
    "google_sheets_credentials",
    "google_service_account_json",
}

ENV_TO_SETTING = {
    "APIFY_TOKEN": "apify_token",
    "ANTHROPIC_KEY": "anthropic_key",
    "GEMINI_KEY": "gemini_key",
    "GROQ_KEY": "groq_key",
    "GOOGLE_SHEETS_ID": "google_sheets_id",
    "GOOGLE_SHEETS_CREDENTIALS": "google_sheets_credentials",
    "INSTAGRAM_ACCESS_TOKEN": "instagram_access_token",
    "INSTAGRAM_USER_ID": "instagram_user_id",
    "INSTAGRAM_USERNAME": "instagram_username",
    "INSTAGRAM_WEBHOOK_TOKEN": "instagram_webhook_token",
    "INSTAGRAM_AUTO_REPLY_ENABLED": "instagram_auto_reply_enabled",
    "INSTAGRAM_DM_REPLY_ENABLED": "instagram_dm_reply_enabled",
    "CSSBUY_USERNAME": "cssbuy_username",
    "CSSBUY_PASSWORD": "cssbuy_password",
    "CSSBUY_SOURCE": "cssbuy_source",
    "CAPTCHA_2CAPTCHA_KEY": "captcha_2captcha_key",
    "PLAYWRIGHT_TIMEOUT": "playwright_timeout",
    "SCRAPE_INTERVAL": "scrape_interval",
    "SCAN_KEYWORDS": "scan_keywords",
    "MIN_MARGIN": "min_margin",
    "MIN_SCORE": "min_score",
    "MIN_ORDERS": "min_orders",
    "MIN_RATING": "min_rating",
    "EXCHANGE_RATE": "exchange_rate",
    "SELL_MARKUP_LOW": "sell_markup_low",
    "SELL_MARKUP_MID": "sell_markup_mid",
    "SELL_MARKUP_HIGH": "sell_markup_high",
    "NICHE": "niche",
    "TARGET_AUDIENCE": "target_audience",
    "SELL_PRICE_MIN": "sell_price_min",
    "SELL_PRICE_MAX": "sell_price_max",
    "EXAMPLE_PRODUCTS": "example_products",
    "GEMINI_MODEL": "gemini_model",
}


def _coerce(value: str, fallback: Any) -> Any:
    if fallback is None:
        # Try JSON first to support arrays/bools/numbers from env.
        try:
            return json.loads(value)
        except Exception:
            return value
    if isinstance(fallback, bool):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(fallback, int) and not isinstance(fallback, bool):
        return int(float(value))
    if isinstance(fallback, float):
        return float(value)
    if isinstance(fallback, list):
        parsed = [s.strip() for s in value.split(",") if s.strip()]
        return parsed
    if isinstance(fallback, dict):
        try:
            return json.loads(value)
        except Exception:
            return fallback
    return value


def get_config(key: str, fallback: Any = None) -> Any:
    env_value = os.getenv(key)
    if env_value is None or env_value == "":
        return fallback
    try:
        return _coerce(env_value, fallback)
    except Exception:
        return fallback


def merge_env_with_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(settings or {})
    for env_key, setting_key in ENV_TO_SETTING.items():
        merged[setting_key] = get_config(env_key, merged.get(setting_key))
    return merged


def sanitize_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = {}
    for key, value in (settings or {}).items():
        if key in SENSITIVE_KEYS:
            continue
        sanitized[key] = value
    return sanitized
