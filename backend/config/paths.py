"""
Filesystem locations for self-hosted runs.

Everything DropOS writes at runtime (embedded Postgres cluster, generated JWT
secret, collages, cleaned images, scraper debug shots, CSSBuy session) lives
under one data directory so a local install is a single folder you can back up
or delete.

    DROPOS_DATA_DIR   override (default: <repo>/data)
"""

import os
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_DIR = _BACKEND_DIR.parent

DATA_DIR = Path(os.getenv("DROPOS_DATA_DIR") or (_REPO_DIR / "data")).resolve()


def data_path(*parts: str, is_file: bool = False) -> Path:
    """Return DATA_DIR/parts, creating the directory (or, for files, the parent)."""
    p = DATA_DIR.joinpath(*parts)
    (p.parent if is_file else p).mkdir(parents=True, exist_ok=True)
    return p


COLLAGE_DIR = data_path("collages")
CLEANED_DIR = data_path("cleaned")
PG_DIR = data_path("pg")
SECRET_FILE = data_path("jwt_secret.key", is_file=True)
