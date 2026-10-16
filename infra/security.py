"""Transport security, response headers, and cookie hardening.

"Encryption" on a hosted app is mostly not something you implement — Railway
and an AWS load balancer both terminate TLS for you. What is left is the part
that is genuinely the application's job, and that is what this module does:

  * Trust the proxy's forwarded headers, so the app knows the visitor arrived
    over HTTPS and knows their real address.
  * Redirect anyone who reaches it over plain HTTP.
  * Set HSTS, so a browser that has been here once refuses to try HTTP again.
  * Mark the session cookie Secure, HttpOnly and SameSite, so the login session
    cannot be read by JavaScript or sent from another site.

That last one matters most. Botfolio has password login; a session cookie
without HttpOnly is one cross-site scripting bug away from account takeover.
"""

import logging
from urllib.parse import urlsplit

from flask import redirect, request, session

from infra.settings import settings

log = logging.getLogger("botfolio")


def install(app):
    _trust_proxy(app)
    _harden_cookies(app)

    @app.before_request
    def _require_https():
        """Send HTTP visitors to HTTPS, except the health checks.

        The probe exclusion is not a detail: AWS target-group health checks hit
        the instance over plain HTTP inside the VPC, and a 301 is not a
        healthy response, so redirecting them takes the whole service out of
        rotation on deploy.
        """
        # Keep this bit of request state even when /logout clears the Flask
        # session.  The after-request hook uses it to ensure a page reached
        # while signed in is never restored from the browser cache.
        request.environ["botfolio.had_session"] = bool(session.get("user_id"))

        if not settings.force_https:
            return None
        if request.endpoint in {"infra_metrics.healthz", "infra_metrics.readyz"}:
            return None
        # url_scheme has already been corrected by ProxyFix at this point.
        if request.scheme == "https":
            return None
        return redirect(request.url.replace("http://", "https://", 1), code=301)

    @app.after_request
    def _headers(response):
        for header, value in _response_headers().items():
            # setdefault semantics: never clobber a header a view set itself.
            response.headers.setdefault(header, value)
        if request.environ.get("botfolio.had_session"):
            response.headers["Cache-Control"] = "no-store, private, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    return app


def _trust_proxy(app):
    """Read X-Forwarded-* so the app sees the client, not the router.

    Without this every request appears to arrive from the proxy over HTTP,
    which breaks three things at once: url_for(_external=True) generates http://
    links, the HTTPS redirect above loops forever, and the rate limiter
    attributes every visitor on the internet to one address.

    x_for=1 means "trust exactly one hop". Trusting more would let a client
    forge the header and spoof its own address past the rate limiter.
    """
    if not settings.behind_proxy:
        return
    try:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
        log.info("trusting one layer of proxy headers")
    except ImportError:  # pragma: no cover - ships with Flask
        log.warning("ProxyFix unavailable; client IPs will be the proxy's")


def _harden_cookies(app):
    """Flask's session cookie defaults are safe for development, not for a host."""
    app.config.update(
        # Unreadable from JavaScript. The single highest-value flag here.
        SESSION_COOKIE_HTTPONLY=True,
        # Not sent over plain HTTP. Only in production — setting it locally
        # would stop sessions working on http://127.0.0.1 entirely.
        SESSION_COOKIE_SECURE=settings.force_https,
        # "Lax" still sends the cookie when someone follows a link to the site,
        # so ordinary navigation works, but withholds it on cross-site POSTs.
        # That is CSRF defence in depth behind the token check in app.py.
        SESSION_COOKIE_SAMESITE="Lax",
        # How long a login lasts. Login explicitly marks the session permanent,
        # so this value becomes a real cookie expiry rather than a setting Flask
        # never applies. It is a sliding window: REFRESH_EACH_REQUEST re-sends
        # the cookie with a fresh expiry on every response, so an account in
        # active use never has its cookie run out from under it. The matching
        # server-side token in app.py (start_authenticated_session) is slid
        # forward the same way, so the two halves expire together.
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * settings.session_lifetime_days,
        SESSION_REFRESH_EACH_REQUEST=True,
    )


def _response_headers():
    headers = {
        # Stop the browser guessing a response is a script when it is not.
        "X-Content-Type-Options": "nosniff",
        # No other site may frame this one — clickjacking defence.
        "X-Frame-Options": "DENY",
        # Do not leak the page someone was on when they follow a link out.
        "Referrer-Policy": "strict-origin-when-cross-origin",
        # This app needs none of these; deny them rather than leave them open.
        "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
        "Content-Security-Policy": _csp(),
    }

    if settings.hsts_seconds:
        # Only ever sent over HTTPS. Sent on a plain-HTTP response it is
        # ignored, and if it were honoured it would lock a developer out of
        # their own http://localhost.
        headers["Strict-Transport-Security"] = (
            f"max-age={settings.hsts_seconds}; includeSubDomains"
        )

    return headers


def _csp():
    """Content Security Policy, matched to what the templates actually load.

    'unsafe-inline' is present for scripts and it is not an oversight:
    base.html and design_detail.html carry inline <script> blocks, and the
    design page writes the saved camera position into one. A policy that broke
    the 3D viewer would get switched off within a day, which is worse than a
    policy that is honest about its own limit.

    The parts that are strict still earn their place — object-src 'none' kills
    Flash-era plugin vectors, frame-ancestors 'none' blocks framing even where
    X-Frame-Options is ignored, and form-action 'self' stops an injected form
    posting a password somewhere else.
    """
    image_sources = ["'self'", "data:", "blob:"]
    connect_sources = ["'self'"]

    # When uploads are served from a bucket or CDN, that origin has to be
    # allowed explicitly or every photo on the site is blocked.
    if settings.uses_s3:
        origin = settings.s3_images_public_url or (
            f"https://{settings.s3_bucket_images}.s3.{settings.s3_region}.amazonaws.com"
        )
        image_sources.append(origin)
        connect_sources.append(origin)

        # Direct model uploads use a presigned PUT to the private S3/R2 API,
        # not to the public image CDN above. If that API origin is absent from
        # connect-src, authorization succeeds but the browser blocks the PUT
        # and the submission handler never gets to post the completed form.
        endpoint = urlsplit(settings.s3_endpoint)
        if endpoint.scheme in {"http", "https"} and endpoint.netloc:
            storage_origin = f"{endpoint.scheme}://{endpoint.netloc}"
            if storage_origin not in connect_sources:
                connect_sources.append(storage_origin)

    return "; ".join([
        "default-src 'self'",
        f"img-src {' '.join(image_sources)}",
        f"connect-src {' '.join(connect_sources)}",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "font-src 'self' data:",
        # The 3D viewer builds models as blobs before handing them to WebGL.
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])
