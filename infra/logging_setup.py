"""Structured logging, and a 500 handler that actually says what broke.

The motivating incident: a template filter was registered after the template
that used it had already been compiled, and the only evidence anywhere was the
words "Internal Server Error" in a browser. Finding it took two servers running
side by side. With this module the same failure writes one line naming the
exception, the route, the user, and a traceback, and hands the visitor an error
ID they can quote back to you.

Everything is logged to stdout, never to a file. Both Railway and ECS capture a
container's stdout and nothing else; a log file inside a container is written
to a disk that is deleted on the next deploy.
"""

import json
import logging
import os
import re
import sys
import time
import traceback
import uuid

from flask import g, has_request_context, render_template, request

from infra.settings import settings

log = logging.getLogger("botfolio")

# Never let these reach a log aggregator, whatever the field is called. Checked
# as substrings, so `new_password` and `csrf_token` are both caught.
_SECRET_HINTS = ("password", "token", "secret", "key", "authorization", "cookie")


def _redact(mapping):
    """Copy a dict with anything that smells like a credential replaced.

    Called on form data before it goes into an error log. Logging the form is
    the difference between a reproducible bug report and a guess, but the login
    form's `password` field must never survive that trip.
    """
    out = {}
    for key, value in mapping.items():
        lowered = key.lower()
        if any(hint in lowered for hint in _SECRET_HINTS):
            out[key] = "<redacted>"
        else:
            text = str(value)
            # Long values are almost always a base64 model preview; the length
            # is the useful part, the payload would flood the log.
            out[key] = text if len(text) <= 200 else f"<{len(text)} chars>"
    return out


class JsonFormatter(logging.Formatter):
    """One JSON object per line.

    CloudWatch Logs Insights and Railway's log search both index JSON fields,
    which turns "find the 500s from this user" into a query instead of a scroll.
    """

    def format(self, record):
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "env": settings.environment,
            "instance": settings.instance,
            "release": settings.release,
        }

        # Request details are attached by the filter below, not looked up here,
        # so that logs emitted from a background thread still format cleanly.
        for field in ("request_id", "method", "path", "user", "ip", "status", "ms"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info))

        return json.dumps(payload, default=str)


class HumanFormatter(logging.Formatter):
    """Local development: short, aligned, and readable at a glance."""

    def format(self, record):
        stamp = time.strftime("%H:%M:%S", time.localtime(record.created))
        where = getattr(record, "path", "")
        rid = getattr(record, "request_id", "")
        prefix = f"{stamp} {record.levelname:<7}"
        if where:
            prefix += f" {getattr(record, 'method', '')} {where}"
        line = f"{prefix}  {record.getMessage()}"
        if rid:
            line += f"  [{rid}]"
        if record.exc_info:
            line += "\n" + "".join(traceback.format_exception(*record.exc_info))
        return line


class RequestContextFilter(logging.Filter):
    """Stamp every record with the request it happened inside.

    A filter rather than a formatter, because this has to work for logs written
    by Flask and Werkzeug too, not just ones this app emits deliberately.
    """

    def filter(self, record):
        if not has_request_context():
            return True
        record.request_id = getattr(g, "request_id", "-")
        record.method = request.method
        record.path = request.path
        record.ip = _client_ip()
        # Read straight from the session: calling current_user() here would run
        # a database query from inside the logger, and a logger that can raise
        # is a logger that hides the error it was called to report.
        try:
            from flask import session

            record.user = session.get("user_id", "-")
        except Exception:
            record.user = "-"
        return True


def _client_ip():
    """The visitor's address, trusting X-Forwarded-For only behind a proxy.

    On Railway and behind an ALB the direct peer is the router, so every
    request would otherwise be attributed to one address — which would make the
    rate limiter throttle the whole site as a single client.
    """
    if settings.behind_proxy:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            # Left-most entry is the original client; the rest are hops.
            return forwarded.split(",")[0].strip()
    return request.remote_addr or "-"


class _SuppressStartupBanner(logging.Filter):
    """Drop the start-up lines that app.py's own banner replaces.

    Werkzeug announces the address it bound and how to quit. app.py prints that
    same information, plus the network address and which database is in use, so
    letting both through means saying it twice. Everything else Werkzeug logs —
    the access lines, the reloader's restart notices — passes untouched, which
    is why this matches specific messages rather than raising the level.

    Two details make the obvious version of this not work. Werkzeug wraps these
    messages in ANSI colour codes, so they do not *start* with the text you see
    on screen, and it emits the development-server warning and both "Running on"
    lines as one multi-line record. Hence: strip the escapes, then search.

    Dropping that record drops the "this is a development server" warning with
    it. That is acceptable here and only here — this code path is `python
    app.py`, which is always somebody's laptop. Deployments run gunicorn, which
    never calls run_simple and never printed the warning in the first place.
    """

    _ANSI = re.compile(r"\x1b\[[0-9;]*m")
    _SUPPRESSED = (" * Running on", "Press CTRL+C to quit")

    def filter(self, record):
        message = self._ANSI.sub("", str(record.msg))
        return not any(phrase in message for phrase in self._SUPPRESSED)


def install(app):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.log_json else HumanFormatter())
    handler.addFilter(RequestContextFilter())

    root = logging.getLogger()
    # Replace rather than append: Flask installs its own handler, and keeping
    # both prints every line twice.
    root.handlers = [handler]
    root.setLevel(settings.log_level)
    app.logger.handlers = []
    app.logger.propagate = True

    # In production Werkzeug's per-request access line duplicates what
    # metrics.py records, with less detail, so it is dropped. Locally it is the
    # opposite: watching requests scroll past is how you develop, and metrics.py
    # only speaks up for slow ones. So keep it on a laptop and quiet it on a
    # server.
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.setLevel(logging.INFO if settings.is_local else logging.WARNING)
    werkzeug_logger.addFilter(_SuppressStartupBanner())

    @app.before_request
    def _assign_request_id():
        # Reuse the proxy's ID when there is one, so a single request can be
        # followed across the load balancer's logs and this app's.
        incoming = request.headers.get("X-Request-Id", "")
        g.request_id = (incoming[:64] or uuid.uuid4().hex[:12])

    @app.after_request
    def _echo_request_id(response):
        response.headers["X-Request-Id"] = getattr(g, "request_id", "-")
        return response

    @app.errorhandler(Exception)
    def _unhandled(exc):
        """Log the traceback, show the visitor an ID, never show the traceback.

        Flask re-raises HTTP exceptions (404 and friends) past this handler, so
        only genuine bugs land here. The ID printed on the page is the same one
        in the log line, which is what makes a bug report actionable.
        """
        from werkzeug.exceptions import HTTPException

        if isinstance(exc, HTTPException):
            return exc

        request_id = getattr(g, "request_id", "-")
        log.error(
            "unhandled %s: %s", type(exc).__name__, exc,
            exc_info=exc,
            extra={"form": _redact(request.form.to_dict()) if request.form else {}},
        )

        # In development the interactive debugger is more useful than a pretty
        # page, so let the exception through to it.
        if app.debug:
            raise exc

        try:
            # Same template the 403/404 handlers use, so a crash looks like the
            # rest of the site rather than like a different application.
            return render_template(
                "error.html", code=500,
                message="Something broke on our end. If you report this, "
                        f"quote reference {request_id}.",
            ), 500
        except Exception:
            # A broken error template must not itself 500 — that loops. This
            # runs with no template engine and no database behind it, so it is
            # literal markup, but it still has to be readable and still has to
            # carry the reference: this is the page a user actually reports.
            log.error("error template failed to render for request %s", request_id)
            return (
                "<!doctype html><meta charset=utf-8>"
                "<title>Something broke &mdash; Botfolio</title>"
                "<style>body{font:16px/1.6 system-ui,sans-serif;margin:0;"
                "display:grid;place-items:center;min-height:100vh;"
                "background:#0f1116;color:#e8eaf0}main{max-width:32rem;padding:2rem}"
                "code{background:#1c1f27;padding:.15em .4em;border-radius:.3em}"
                "a{color:#8ab4ff}</style>"
                "<main><h1>Something broke on our end</h1>"
                "<p>This one is our fault, not yours. Please try again in a moment.</p>"
                f"<p>If you report it, quote reference <code>{request_id}</code>.</p>"
                '<p><a href="/">Back to Botfolio</a> &middot; '
                '<a href="/logout">Sign out</a></p></main>'
            ), 500

    log.info("logging ready: %s", json.dumps(settings.describe()))
    return app
