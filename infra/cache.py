"""A small TTL cache for queries that are expensive and rarely change.

Botfolio's gallery and tag pages aggregate votes with correlated subqueries —
for every design, sum the votes for every tag on it. That is fine at the
current size and gets slower in proportion to designs times tags. Caching the
result for a few seconds turns a burst of visitors into one query instead of
one query each.

Two rules this module enforces, because getting them wrong is how caches cause
bugs rather than fix them:

  * **Nothing user-specific.** Cached values are shared between visitors, so
    caching anything that depends on who is logged in would serve one person's
    view to another. Cached functions take an explicit key and that key must
    contain everything the result depends on.
  * **Short lifetimes.** The default is 30 seconds. A student uploading a
    design wants to see it appear, and waiting a minute for a cache to expire
    reads as the site being broken.

In-process by default; Redis when REDIS_URL is set, which is what makes the
cache shared once there is more than one container.
"""

import functools
import hashlib
import json
import logging
import threading
import time

from infra.settings import settings

log = logging.getLogger("botfolio")

_lock = threading.Lock()
_store = {}          # key -> (expires_at, value)
_stats = {"hits": 0, "misses": 0, "evictions": 0}
_last_sweep = time.time()

# Above this many entries, expired items are swept early. The cache holds page
# fragments, so an unbounded one is a slow memory leak on a small instance.
_MAX_ENTRIES = 500

_redis = None


def _client():
    global _redis
    if _redis is not None:
        return _redis or None
    if not settings.redis_url:
        _redis = False
        return None
    try:
        import redis

        _redis = redis.Redis.from_url(settings.redis_url, socket_timeout=0.25)
        _redis.ping()
        log.info("cache using redis")
    except Exception as exc:
        log.warning("redis unavailable (%s), caching in-process", type(exc).__name__)
        _redis = False
    return _redis or None


def _sweep(now):
    """Drop expired entries. Cheap, and only when the cache is actually large."""
    global _last_sweep
    if len(_store) < _MAX_ENTRIES and now - _last_sweep < 120:
        return
    _last_sweep = now
    for key, (expires, _) in list(_store.items()):
        if expires <= now:
            _store.pop(key, None)
            _stats["evictions"] += 1
    # Still oversized after dropping expired entries: discard the soonest to
    # expire until it fits. Crude, but bounded memory beats a perfect policy.
    if len(_store) > _MAX_ENTRIES:
        for key, _ in sorted(_store.items(), key=lambda kv: kv[1][0])[: len(_store) // 4]:
            _store.pop(key, None)
            _stats["evictions"] += 1


def get(key):
    """Return a cached value, or None if absent or expired."""
    if not settings.cache_enabled:
        return None

    client = _client()
    if client is not None:
        try:
            raw = client.get(f"cache:{key}")
            if raw is None:
                _stats["misses"] += 1
                return None
            _stats["hits"] += 1
            return json.loads(raw)
        except Exception:
            # A cache is an optimisation; a broken one must never be an error.
            return None

    now = time.time()
    with _lock:
        _sweep(now)
        entry = _store.get(key)
        if entry is None or entry[0] <= now:
            _stats["misses"] += 1
            return None
        _stats["hits"] += 1
        return entry[1]


def put(key, value, seconds=None):
    """Store a value for `seconds` (default CACHE_SECONDS)."""
    if not settings.cache_enabled:
        return value
    ttl = seconds if seconds is not None else settings.cache_seconds

    client = _client()
    if client is not None:
        try:
            client.setex(f"cache:{key}", ttl, json.dumps(value, default=str))
        except Exception:
            pass
        return value

    with _lock:
        _store[key] = (time.time() + ttl, value)
    return value


def clear(prefix=""):
    """Drop cached entries, optionally only those under a prefix.

    Called after a write so the change is visible immediately rather than after
    the TTL. Without this, uploading a design and not seeing it on the gallery
    looks exactly like a failed upload.
    """
    client = _client()
    if client is not None:
        try:
            # scan_iter, never KEYS: KEYS blocks the Redis server for the whole
            # scan, which on a shared instance stalls everything else using it.
            for key in client.scan_iter(match=f"cache:{prefix}*", count=200):
                client.delete(key)
        except Exception:
            pass
        return

    with _lock:
        for key in [k for k in _store if k.startswith(prefix)]:
            _store.pop(key, None)


def memoize(prefix, seconds=None):
    """Cache a function's return value under a key built from its arguments.

    Only safe for functions whose result depends entirely on those arguments —
    see the module docstring. Arguments are hashed rather than concatenated so
    a long search query cannot produce an unbounded key.

        @cache.memoize("gallery", seconds=30)
        def gallery_page(query, page): ...
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not settings.cache_enabled:
                return func(*args, **kwargs)

            fingerprint = hashlib.sha256(
                json.dumps([args, sorted(kwargs.items())], default=str).encode()
            ).hexdigest()[:16]
            key = f"{prefix}:{fingerprint}"

            hit = get(key)
            if hit is not None:
                return hit
            return put(key, func(*args, **kwargs), seconds)

        # Exposed so a write path can invalidate just this function's entries.
        wrapper.cache_clear = lambda: clear(f"{prefix}:")
        return wrapper

    return decorator


def stats():
    """Hit rate, for /metrics. A cache nobody hits is just latency."""
    total = _stats["hits"] + _stats["misses"]
    return {
        **_stats,
        "entries": len(_store),
        "hit_rate": round(_stats["hits"] / total, 3) if total else 0.0,
        "backend": "redis" if _client() is not None else "in-process",
    }


def install(app):
    # Static assets are already immutable (a UUID filename never changes), but
    # Flask defaults to a 12-hour cache. A year means a returning visitor
    # re-downloads nothing.
    app.config.setdefault("SEND_FILE_MAX_AGE_DEFAULT", 31536000)
    return app
