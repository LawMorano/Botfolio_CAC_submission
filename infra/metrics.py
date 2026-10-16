"""Request timing, plus the health endpoints a host needs to route traffic.

Two separate things that belong together because both answer "is the site OK":

  * Timing — every request's duration is recorded, and anything slower than
    SLOW_REQUEST_MS is logged with its path. That is how a slow page gets
    noticed before someone complains about it.
  * Health — /healthz and /readyz. Railway polls one to decide whether a
    deploy succeeded; an AWS target group polls one to decide whether to send
    an instance traffic. Without them a container that boots but cannot reach
    its database still receives visitors.

Counters live in memory, which means they describe *this* process and reset on
restart. That is the honest scope: a real metrics stack ships them to a
time-series database, and for a project this size the extra moving part costs
more than it returns.
"""

import threading
import time
from collections import Counter, deque

from flask import Blueprint, g, jsonify, request

from infra.settings import settings

bp = Blueprint("infra_metrics", __name__)

# Guards every counter below. Gunicorn serves requests on threads, so two
# requests finishing at once would otherwise interleave read-modify-write on
# the same integer and quietly lose counts.
_lock = threading.Lock()

_started = time.time()
_requests = Counter()          # (method, endpoint, status class) -> count
_errors = Counter()            # endpoint -> count of 5xx
# Bounded on purpose: a deque with maxlen keeps memory flat no matter how long
# the process runs, which an unbounded list of every request duration does not.
_durations = deque(maxlen=2000)
_recent = deque(maxlen=2000)   # completion timestamps, for the QPS window


def _percentile(values, fraction):
    """p50/p95 without pulling in numpy for four lines of arithmetic."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return round(ordered[index], 1)


def snapshot():
    """Everything the /metrics endpoint reports, as plain data."""
    with _lock:
        durations = list(_durations)
        recent = list(_recent)
        requests_by = dict(_requests)
        errors_by = dict(_errors)

    now = time.time()
    # QPS over the last minute rather than since boot: an average over three
    # days of uptime hides the spike you are trying to see.
    last_minute = [t for t in recent if now - t <= 60]

    return {
        "uptime_seconds": round(now - _started, 1),
        "environment": settings.environment,
        "instance": settings.instance,
        "release": settings.release,
        "qps_1m": round(len(last_minute) / 60.0, 3),
        "requests_total": sum(requests_by.values()),
        "errors_total": sum(errors_by.values()),
        "latency_ms": {
            "p50": _percentile(durations, 0.50),
            "p95": _percentile(durations, 0.95),
            "p99": _percentile(durations, 0.99),
            "max": round(max(durations), 1) if durations else 0.0,
        },
        "by_endpoint": {
            f"{method} {endpoint} {status}": count
            for (method, endpoint, status), count in sorted(
                requests_by.items(), key=lambda kv: -kv[1]
            )[:25]
        },
        "errors_by_endpoint": errors_by,
    }


def install(app):
    import logging

    log = logging.getLogger("botfolio")

    @app.before_request
    def _start_timer():
        # perf_counter, not time(): it is monotonic, so an NTP correction
        # mid-request cannot produce a negative duration.
        g._started_at = time.perf_counter()

    @app.after_request
    def _record(response):
        started = getattr(g, "_started_at", None)
        if started is None:
            return response

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        # request.endpoint, not request.path: grouping by path would make every
        # design ID its own bucket and the counters useless.
        endpoint = request.endpoint or "unmatched"
        status_class = f"{response.status_code // 100}xx"

        with _lock:
            _requests[(request.method, endpoint, status_class)] += 1
            _durations.append(elapsed_ms)
            _recent.append(time.time())
            if response.status_code >= 500:
                _errors[endpoint] += 1

        if elapsed_ms >= settings.slow_request_ms:
            log.warning(
                "slow request %.0fms", elapsed_ms,
                extra={"status": response.status_code, "ms": round(elapsed_ms, 1)},
            )

        # Handy in the browser's network tab while tuning a page.
        response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.1f}"
        return response

    app.register_blueprint(bp)
    return app


@bp.route("/healthz")
def healthz():
    """Liveness: is this process running?

    Deliberately does not touch the database. A liveness probe that fails when
    a *dependency* is down causes the orchestrator to kill and restart a
    perfectly healthy container, which does nothing but add downtime to an
    outage it cannot fix. Dependency checks belong in /readyz.
    """
    return jsonify(status="ok", release=settings.release), 200


@bp.route("/readyz")
def readyz():
    """Readiness: can this process actually serve a request?

    Checked by the load balancer before sending traffic, and by Railway to
    decide whether a new deploy is healthy enough to swap in. A failure here
    takes the instance out of rotation without killing it.
    """
    import db

    checks = {}
    ok = True

    try:
        conn = db.get_db()
        conn.execute("SELECT 1").fetchone()
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
        ok = False

    try:
        from infra import storage

        checks["storage"] = storage.health()
    except Exception as exc:
        checks["storage"] = f"error: {type(exc).__name__}"
        # Uploads being unavailable degrades the site but does not break
        # browsing, so it is reported without failing the whole check.

    status = 200 if ok else 503
    return jsonify(status="ok" if ok else "degraded", checks=checks), status


@bp.route("/metrics")
def metrics():
    """Counters for this process.

    Gated behind METRICS_TOKEN because the endpoint names every route and its
    error count, which is a free map of the application for anyone probing it.
    Unset (the default) means the endpoint is simply off in production; it stays
    open locally, where there is nothing to protect.
    """
    if settings.metrics_token:
        supplied = request.headers.get("X-Metrics-Token") or request.args.get("token")
        if supplied != settings.metrics_token:
            return jsonify(error="not found"), 404
    elif not settings.is_local:
        return jsonify(error="not found"), 404

    return jsonify(snapshot()), 200
