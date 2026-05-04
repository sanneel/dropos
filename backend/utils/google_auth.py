import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

TMP_CREDS_PATH = Path("/tmp/service-account.json")


def _validate_service_account_payload(payload: dict) -> bool:
    if not isinstance(payload, dict):
        log.error("Invalid GOOGLE_SERVICE_ACCOUNT_JSON: expected a JSON object")
        return False

    private_key = str(payload.get("private_key") or "").replace("\\n", "\n").strip()
    client_email = str(payload.get("client_email") or "").strip()

    if not client_email or "@" not in client_email:
        log.error("Invalid GOOGLE_SERVICE_ACCOUNT_JSON: missing client_email")
        return False
    if "NEW_PRIVATE_KEY_HERE" in private_key or "NEW_KEY_ID" in str(payload.get("private_key_id") or ""):
        log.error("Invalid GOOGLE_SERVICE_ACCOUNT_JSON: placeholder service account key is still configured")
        return False
    if not private_key.startswith("-----BEGIN PRIVATE KEY-----") or not private_key.endswith("-----END PRIVATE KEY-----"):
        log.error("Invalid GOOGLE_SERVICE_ACCOUNT_JSON: private_key is not a PEM private key")
        return False

    payload["private_key"] = private_key
    return True


def configure_google_credentials_from_env() -> Optional[str]:
    raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw_json:
        return None

    try:
        payload = json.loads(raw_json)
    except Exception as exc:
        log.error("Invalid GOOGLE_SERVICE_ACCOUNT_JSON: %s", exc)
        return None

    if not _validate_service_account_payload(payload):
        for env_key in ("GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_SHEETS_CREDENTIALS"):
            if os.getenv(env_key) == str(TMP_CREDS_PATH):
                os.environ.pop(env_key, None)
        return None

    try:
        TMP_CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        TMP_CREDS_PATH.write_text(json.dumps(payload), encoding="utf-8")
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(TMP_CREDS_PATH)
        return str(TMP_CREDS_PATH)
    except Exception as exc:
        log.error("Failed to write service account file: %s", exc)
        return None
