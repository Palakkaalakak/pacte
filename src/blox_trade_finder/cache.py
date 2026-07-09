from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".cache"


def peek(key: str) -> Any | None:
    """Read a cache entry regardless of TTL, without triggering a fetch.
    Returns None if no entry exists yet."""
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_or_fetch(
    key: str, ttl_seconds: int, fetch: Callable[[], Any], *, fresh: bool = False
) -> Any:
    """Disk JSON cache with per-entry TTL (plan section 3). `fetch` must return
    JSON-serializable data (callers pass dicts, not pydantic models)."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{key}.json"

    if not fresh and path.exists():
        age = time.time() - path.stat().st_mtime
        if age < ttl_seconds:
            logger.debug("cache HIT for '%s' (age=%.0fs, ttl=%ds)", key, age, ttl_seconds)
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)

    logger.debug("cache MISS for '%s' (fresh=%s) — fetching live", key, fresh)
    data = fetch()
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    return data
