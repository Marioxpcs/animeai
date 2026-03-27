"""
engine/cache.py
Simple in-memory TTL cache for search results.

- Normalised query string as key (lowercase, stripped, no punctuation)
- 24-hour TTL per entry
- Max 500 entries, oldest evicted first
"""

import re
import time
import logging
import threading

logger = logging.getLogger(__name__)

_MAX_SIZE = 500
_TTL_SECONDS = 24 * 60 * 60  # 24 hours

# {normalised_query: (timestamp, response_data)}
_cache: dict[str, tuple[float, list]] = {}
_lock = threading.Lock()

_PUNCT_RE = re.compile(r'[^\w\s]', re.UNICODE)


def normalise_key(query: str) -> str:
    """Lowercase, strip whitespace, remove punctuation."""
    q = query.lower().strip()
    q = _PUNCT_RE.sub('', q)
    # collapse multiple spaces
    q = re.sub(r'\s+', ' ', q).strip()
    return q


def get(query: str) -> list | None:
    """Return cached response or None on miss/expiry."""
    key = normalise_key(query)
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            logger.info('CACHE MISS: "%s"', query)
            return None
        ts, data = entry
        if time.time() - ts > _TTL_SECONDS:
            del _cache[key]
            logger.info('CACHE MISS: "%s"', query)
            return None
        logger.info('CACHE HIT: "%s"', query)
        return data


def put(query: str, data: list) -> None:
    """Store a response. Evicts oldest entry if at capacity."""
    key = normalise_key(query)
    with _lock:
        # If key already exists, just update it
        if key in _cache:
            _cache[key] = (time.time(), data)
            return
        # Evict oldest if full
        if len(_cache) >= _MAX_SIZE:
            oldest_key = min(_cache, key=lambda k: _cache[k][0])
            del _cache[oldest_key]
        _cache[key] = (time.time(), data)
