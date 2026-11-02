"""Age cut-offs for newest-first feeds: stop paging once a page is entirely too old."""
from __future__ import annotations

from datetime import datetime, timezone


def to_epoch(value) -> float | None:
    """Epoch seconds for an ISO string / datetime / epoch number, or None if unparseable."""
    try:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, datetime):
            return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def page_is_too_old(batch: list[dict], key: str, max_age_minutes: float | None, now: float | None = None) -> bool:
    """True if EVERY ad in `batch` is older than the limit (feeds are newest-first, so every
    later page is older still and paging can stop). An ad with no readable time keeps the page alive."""
    if not max_age_minutes or not batch:
        return False
    import time
    cutoff = (now or time.time()) - max_age_minutes * 60
    for ad in batch:
        ts = to_epoch(ad.get(key))
        if ts is None or ts >= cutoff:
            return False
    return True
