import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

TMP_CREDS_PATH = Path("/tmp/service-account.json")


def configure_google_credentials_from_env() -> Optional[str]:
    raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw_json:
        return None

    try:
        payload = json.loads(raw_json)
    except Exception as exc:
        log.error("Invalid GOOGLE_SERVICE_ACCOUNT_JSON: %s", exc)
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
