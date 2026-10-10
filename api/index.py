"""Vercel entrypoint: serves the DropOS backend + SPA as one Python function.

Needs DATABASE_URL (or POSTGRES_URL from the Neon / Supabase integration).
The login is off by default here; set AUTH_DISABLED=0 to bring it back.
"""

import os
import sys

# Only /tmp is writable on Vercel.
os.environ.setdefault("DROPOS_DATA_DIR", "/tmp/dropos")
os.environ.setdefault("AUTH_DISABLED", "1")
os.environ.setdefault("LOCAL_SCRAPING_ONLY", "true")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from main import app  # noqa: E402,F401
