"""Per-IP request limits, applied before a request costs anything.

Botfolio already limits uploads per *user* in the database (see
UPLOAD_LIMIT_DAILY in config.py). This is the layer underneath that: limits per
*address*, checked before the request body is read and before anyone is logged
in. The two protect different things and neither replaces the other.

Three concrete reasons this exists here:

  * MAX_CONTENT_LENGTH is 400 MB. Without a limit, one client can post 400 MB
    repeatedly and saturate the instance's bandwidth on its own.
  * /designs/<id>/grade calls the OpenAI API, which bills per call. An unlimited
    endpoint that spends money is a bill waiting to happen.
  * /login and /register are guessable. Limiting them turns password guessing
    from "a script" into "not worth it".

Counters live in memory by default and move to Redis when REDIS_URL is set.
That matters once there are two containers: in-process counters mean each
container enforces the limit separately, so the real limit is doubled.
"""

import functools
import logging
import threading
import time

from flask import g, jsonify, request

from infra.settings import settings

log = logging.getLogger("botfolio")

_lock = threading.Lock()
# key -> (window_started_at, count). Trimmed opportunistically in _prune.
_buckets = {}
_last_prune = time.time()

_redis = None


def _client():
    """A Redis handle, or None to use the in-process fallback.

    Resolved lazily and cached: importing redis at module scope would make it a
    hard dependency of the whole application, which is exactly what this
    package is not allowed to introduce.
    """
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
        log.info("rate limiter using redis")
    except Exception as exc:
        # A limiter that raises would take down every route it guards, so a
        # broken Redis degrades to local counting instead.
        log.warning("redis unavailable (%s), limiting in-process", type(exc).__name__)
        _redis = False
    return _redis or None


def _prune(now):
    """Drop expired buckets so the dict cannot grow without bound.

    Called from the hot path, so it is rate-limited itself: sweeping the whole
    dict on every request would make the limiter the slowest thing on the page.
    """
    global _last_prune
    if now - _last_prune < 60:
        return
    _last_prune = now
    for key, (started, _) in list(_buckets.items()):
        if now - started > 3600:
            _buckets.pop(key, None)


def _hit(key, limit, window):
    """Count one request. Returns (allowed, seconds_until_reset).

    A fixed window rather than a sliding one. It permits a burst across a
    window boundary, which for this purpose is fine — the goal is to stop
    sustained abuse, not to meter precisely — and it costs one Redis round trip
    instead of a sorted-set operation.
    """
    now = time.time()
    client = _client()

    if client is not None:
        # Bucket the key by window so expiry is implicit in the name; no
        # separate cleanup pass is needed.
        slot = int(now // window)
        redis_key = f"rl:{key}:{slot}"
        try:
            pipe = client.pipeline()
            pipe.incr(redis_key)
            # Expire slightly past the window so a counter cannot outlive it.
            pipe.expire(redis_key, window + 10)
            count = pipe.execute()[0]
            reset_in = int(window - (now % window))
            return count <= limit, reset_in
        except Exception as exc:
            log.warning("redis limit check failed (%s)", type(exc).__name__)
            # fall through to the in-process path

    with _lock:
        _prune(now)
        started, count = _buckets.get(key, (now, 0))
        if now - started >= window:
            started, count = now, 0
        count += 1
        _buckets[key] = (started, count)
        return count <= limit, int(window - (now - started))


def client_key():
    """Who this request is attributed to.

    A signed-in user is limited as themselves, so two students on the same
    school NAT do not consume each other's allowance. Everyone else is limited
    by address.
    """
    from flask import session

    user_id = session.get("user_id")
    if user_id:
        return f"u{user_id}"

    if settings.behind_proxy:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def limit(name, times, per_seconds, methods=("POST",), exempt=None):
    """Cap a route at `times` requests per `per_seconds`, per client.

    When supplied, ``exempt`` is evaluated in the request context before a hit
    is counted. This lets trusted roles bypass a route-specific product limit
    without weakening the application-wide abuse ceiling.

    Applied as a decorator between @app.route and the view:

        @app.route("/login", methods=["GET", "POST"])
        @ratelimit.limit("login", 12, 300)
        def login(): ...

    Only POSTs count by default. Most of these routes answer both verbs from
    one view, and the GET is just the form — charging someone for reloading the
    login page would lock out anyone who mistypes a password twice and refreshes.
    The expensive, abusable half is always the POST. Pass methods=None to count
    every request, which is what a read-heavy route like the download link wants.
    """

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            if not settings.ratelimit_enabled:
                return view(*args, **kwargs)
            if methods is not None and request.method not in methods:
                return view(*args, **kwargs)
            if exempt is not None and exempt():
                return view(*args, **kwargs)

            key = f"{name}:{client_key()}"
            allowed, reset_in = _hit(key, times, per_seconds)
            if not allowed:
                log.warning(
                    "rate limit hit on %s (%s/%ss)", name, times, per_seconds,
                    extra={"status": 429},
                )
                return _too_many(name, reset_in)

            g._ratelimit = (name, times, reset_in)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def _too_many(name, reset_in):
    """A 429 that matches how the caller asked.

    Form posts get a page they can read; the fetch() callers in the tag
    autocomplete get JSON, because an HTML body would parse as garbage there.
    """
    wants_json = (
        request.accept_mimetypes.best == "application/json"
        or request.path.startswith("/api/")
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )
    retry_after = max(1, reset_in)

    if wants_json:
        body = jsonify(error="Too many requests. Slow down.", retry_after=retry_after)
    else:
        body = (
            "<h1>Slow down</h1><p>Too many requests in a short time. "
            f"Try again in about {retry_after} seconds.</p>"
        )

    response = _make_response(body)
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    return response


def _make_response(body):
    from flask import make_response

    return make_response(body)


def install(app):
    """A global ceiling, on top of whatever individual routes declare.

    This exists to catch what per-route limits miss: a crawler walking every
    design page in a tight loop never trips a single route's limit but can
    still flatten the instance. Set high enough that ordinary browsing — which
    fires a burst of requests per page for CSS, images and models — never sees
    it.
    """

    @app.before_request
    def _global_limit():
        if not settings.ratelimit_enabled:
            return None
        # Static files and health checks are cheap and get hit constantly; a
        # limit that includes them would trip on a normal page load, and one
        # that includes /healthz would make the orchestrator think the app is
        # down.
        if request.endpoint in {"static", "infra_metrics.healthz", "infra_metrics.readyz"}:
            return None

        allowed, reset_in = _hit(f"global:{client_key()}", 300, 60)
        if not allowed:
            return _too_many("global", reset_in)
        return None

    return app
