"""
Shared enumerations for the DropOS Operations Engine.

Kept in a standalone module so neither `main.py` nor `worker.py` need to
import from each other, which would create a circular import and crash Python
before the uvicorn server can bind to its port.
"""

from enum import Enum


class ProductStage(str, Enum):
    SCRAPED  = "SCRAPED"
    ENRICHED = "ENRICHED"
    REVIEWED = "REVIEWED"
    QUEUED   = "QUEUED"
    LIVE     = "LIVE"
    REJECTED = "REJECTED"
