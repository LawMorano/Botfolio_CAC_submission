"""Operational plumbing for Botfolio: logging, metrics, limits, storage, cache.

Everything in here is *additive*. The application works with none of it
configured — each module falls back to a local, in-process implementation, so
`python app.py` on a laptop behaves exactly as it did before this package
existed. Pointing an environment variable at S3 or Postgres is what switches a
module over to its hosted backend.

That rule is deliberate. A class project that only runs when Redis is up is
worse than one that runs anywhere, so nothing here is allowed to become a
required dependency.

Call `infra.install(app)` once, after the Flask app exists.
"""

from infra import cache, logging_setup, metrics, ratelimit, security, storage
from infra.settings import settings

__all__ = ["install", "settings", "cache", "storage", "ratelimit", "metrics"]


def install(app):
    """Attach every operational concern to a Flask app, in dependency order.

    Order matters more than it looks. Logging goes first so that a failure in
    any later step is itself logged properly. Security wraps the WSGI app, so
    it has to run before anything reads `request.remote_addr` — which the rate
    limiter does on every request.
    """
    logging_setup.install(app)
    security.install(app)
    metrics.install(app)
    ratelimit.install(app)
    cache.install(app)
    storage.install(app)
    return app
