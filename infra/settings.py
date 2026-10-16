"""One place that reads the environment, so nothing else has to.

Modules elsewhere ask `settings.s3_bucket` rather than `os.environ.get(...)`.
The benefit is not tidiness: it means every knob the deployment has is visible
in one file, and `python -c "from infra.settings import settings; settings.describe()"`
prints exactly how a running container is configured. Debugging a deploy is
mostly the question "what does it think its settings are", and this answers it.

Nothing here fails on a missing variable. Absent configuration means "use the
local fallback", never "crash on startup" — see infra/__init__.py.
"""

import os

# Values people naturally write in a .env file when they mean "yes".
_TRUE = {"1", "true", "yes", "on"}

# The only environment labels that mean "a developer's machine". Everything
# else is treated as a real deployment (see is_local): defaulting the unknown
# case to "hosted" keeps the secure settings on rather than silently off.
_LOCAL_ENVIRONMENTS = frozenset({"development", "dev", "local", "test", "testing"})


def _flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE


def _num(name, default):
    """An int from the environment, falling back rather than raising.

    A typo in a deploy variable should degrade to the default and be visible in
    the startup log, not take the site down on boot.
    """
    try:
        return int(os.environ.get(name, "").strip())
    except (TypeError, ValueError):
        return default


class Settings:
    def __init__(self):
        # --- Which deployment is this -------------------------------------
        # Railway and ECS both inject their own hints; falling back to those
        # means staging usually identifies itself correctly with no config.
        self.environment = (
            os.environ.get("APP_ENV")
            or os.environ.get("RAILWAY_ENVIRONMENT_NAME")
            or "development"
        ).strip().lower()

        # Set by Railway, and by the ECS task definition in aws/. Ends up in
        # every log line, which is how you tell two instances apart.
        self.instance = (
            os.environ.get("RAILWAY_REPLICA_ID")
            or os.environ.get("HOSTNAME")
            or "local"
        )[:12]
        self.release = (
            os.environ.get("RAILWAY_GIT_COMMIT_SHA")
            or os.environ.get("GIT_SHA")
            or "dev"
        )[:12]

        # --- Database ------------------------------------------------------
        # Railway's Postgres plugin and AWS RDS both hand out a DATABASE_URL.
        # Empty means SQLite, which is the right answer on a laptop.
        self.database_url = (os.environ.get("DATABASE_URL") or "").strip()

        # --- Uploads -------------------------------------------------------
        # The important one. Railway containers and ECS tasks have ephemeral
        # disks: without a bucket, every redeploy silently deletes every
        # uploaded photo and model. See infra/storage.py.
        self.s3_bucket = (os.environ.get("S3_BUCKET") or "").strip()
        self.s3_bucket_images = (os.environ.get("S3_BUCKET_IMAGES") or self.s3_bucket).strip()
        self.s3_bucket_models = (os.environ.get("S3_BUCKET_MODELS") or self.s3_bucket).strip()
        self.s3_bucket_quarantine = (os.environ.get("S3_BUCKET_QUARANTINE") or "").strip()
        self.s3_region = (os.environ.get("AWS_REGION") or "us-east-1").strip()
        # Set when serving uploads through CloudFront instead of straight from
        # the bucket. Also lets you point at MinIO in a local compose file.
        self.s3_public_url = (os.environ.get("S3_PUBLIC_URL") or "").strip().rstrip("/")
        self.s3_images_public_url = (
            os.environ.get("S3_IMAGES_PUBLIC_URL") or self.s3_public_url
        ).strip().rstrip("/")
        self.s3_endpoint = (os.environ.get("S3_ENDPOINT_URL") or "").strip()

        # --- Sessions ------------------------------------------------------
        # How long a login lasts. It is a sliding window: any activity pushes
        # the expiry back to a full window, so only a genuinely idle account is
        # ever logged out. 30 days is the usual "keep me signed in" default.
        self.session_lifetime_days = _num("SESSION_LIFETIME_DAYS", 30)

        # --- Sign in with Google -------------------------------------------
        # Unset means the feature is simply off: the button is not rendered and
        # the routes 404, so a deploy that was never given credentials behaves
        # exactly as it did before the feature existed. There is no local
        # fallback -- a real OAuth client is the only way to talk to Google.
        self.google_client_id = (os.environ.get("GOOGLE_CLIENT_ID") or "").strip()
        self.google_client_secret = (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip()
        # Must equal a URI registered in the Google console byte for byte, and
        # is repeated identically in the token exchange. Deliberately not
        # derived from url_for(_external=True): behind Railway's proxy that can
        # emit http:// or the internal hostname, and Google rejects the
        # exchange with redirect_uri_mismatch.
        self.google_redirect_uri = (os.environ.get("GOOGLE_REDIRECT_URI") or "").strip()

        # --- Cache and rate limiting ---------------------------------------
        # Both work in-process without this. Redis matters only once there is
        # more than one container, because two processes otherwise keep two
        # separate sets of counters and the effective limit doubles.
        self.redis_url = (os.environ.get("REDIS_URL") or "").strip()
        self.cache_seconds = _num("CACHE_SECONDS", 30)
        self.cache_enabled = _flag("CACHE_ENABLED", True)
        self.ratelimit_enabled = _flag("RATELIMIT_ENABLED", True)

        # --- Logging and metrics -------------------------------------------
        self.log_level = (os.environ.get("LOG_LEVEL") or "INFO").strip().upper()
        # JSON in the cloud (CloudWatch and Railway both parse it into fields),
        # human-readable on a laptop where you are reading with your eyes.
        self.log_json = _flag("LOG_JSON", not self.is_local)
        self.slow_request_ms = _num("SLOW_REQUEST_MS", 1000)
        # Guessable paths get scraped. Off by default; set it to expose them.
        self.metrics_token = (os.environ.get("METRICS_TOKEN") or "").strip()

        # Optional Discord notification for newly published designs. The URL
        # contains a credential, so it belongs in deployment secrets rather
        # than source control. An empty value leaves publishing unchanged.
        self.discord_showcase_webhook_url = (
            os.environ.get("DISCORD_SHOWCASE_WEBHOOK_URL") or ""
        ).strip()

        # --- Transport security --------------------------------------------
        # Behind Railway's router or an ALB, the app itself speaks plain HTTP;
        # the proxy terminates TLS. So "require HTTPS" has to mean "trust the
        # forwarded header and redirect", not "check request.scheme".
        self.behind_proxy = _flag("BEHIND_PROXY", not self.is_local)
        # Force HTTPS — and therefore mark the session cookie Secure and send
        # HSTS — on every hosted environment, staging included. Staging is
        # served over HTTPS too, so defaulting it off left the login cookie
        # emitted without the Secure flag there unless an operator remembered to
        # set FORCE_HTTPS by hand. Only genuine local development stays plain.
        self.force_https = _flag("FORCE_HTTPS", not self.is_local)
        self.hsts_seconds = _num("HSTS_SECONDS", 31536000 if not self.is_local else 0)

    # --- Derived views the rest of the code reads --------------------------

    @property
    def is_production(self):
        return self.environment in {"production", "prod"}

    @property
    def is_staging(self):
        return self.environment in {"staging", "stage"}

    @property
    def is_local(self):
        # A positive allowlist, not "not production and not staging". An
        # unrecognised label — a renamed Railway environment, APP_ENV=live,
        # prod-eu, release, or a typo — must be treated as a real deployment so
        # the secure defaults switch ON (a stable secret key is required, HTTPS
        # is forced, HSTS and proxy trust and JSON logging turn on). Defaulting
        # the unknown case to "local" did the opposite: it silently handed a
        # hosted deploy an ephemeral per-process secret key and plain HTTP.
        return self.environment in _LOCAL_ENVIRONMENTS

    @property
    def google_oauth_enabled(self):
        """All three values, or the feature stays closed.

        A half-configured deploy is worse than an unconfigured one: the button
        would render and every click would dead-end on Google's error page.
        """
        return bool(
            self.google_client_id
            and self.google_client_secret
            and self.google_redirect_uri
        )

    @property
    def uses_postgres(self):
        return bool(self.database_url)

    @property
    def uses_s3(self):
        return bool(self.s3_bucket_images or self.s3_bucket_models)

    @property
    def uses_direct_model_uploads(self):
        return bool(self.s3_bucket_models and self.s3_bucket_quarantine)

    def storage_bucket(self, kind):
        if kind == "uploads":
            return self.s3_bucket_images
        if kind == "quarantine":
            return self.s3_bucket_quarantine
        return self.s3_bucket_models

    def describe(self):
        """A redacted summary, logged once at startup.

        Values are reported as on/off or as a hostname rather than printed:
        DATABASE_URL carries a password, and logs get shipped somewhere less
        private than the environment they came from.
        """
        return {
            "environment": self.environment,
            "instance": self.instance,
            "release": self.release,
            "database": "postgres" if self.uses_postgres else "sqlite",
            "uploads": (
                f"images={self.s3_bucket_images},models={self.s3_bucket_models}"
                if self.uses_s3 else "local disk"
            ),
            "cache": "redis" if self.redis_url else "in-process",
            "ratelimit": "on" if self.ratelimit_enabled else "off",
            "https": "forced" if self.force_https else "not forced",
            # On/off only -- the id is public but the secret is not, and this
            # dict is printed into the startup log.
            "google_oauth": "on" if self.google_oauth_enabled else "off",
            "session_days": self.session_lifetime_days,
        }


settings = Settings()
