"""Test setup: backend/ on the import path, and a throwaway data directory so
running the tests never touches a real installation's ./data folder."""
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("DROPOS_DATA_DIR", tempfile.mkdtemp(prefix="dropos-test-"))
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 32)
for key in ("AUTH_DISABLED", "INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET", "INSTAGRAM_ACCESS_TOKEN",
            "INSTAGRAM_USER_ID", "PUBLIC_BASE_URL", "APP_URL", "DATABASE_URL"):
    os.environ.pop(key, None)
