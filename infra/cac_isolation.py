"""Fail closed when the standalone CAC deployment is misconfigured."""

import os
from urllib.parse import urlparse


CAC_PROJECT_ID = "7ef1cdea-6185-4602-ab8e-6961ea39dbf4"
CAC_SERVICE_ID = "6ed7b60a-e7c0-441b-9716-91b9c037c083"
CAC_POSTGRES_SERVICE_ID = "11faaf52-9031-4b89-8d9c-c0376a6ef82e"
CAC_BUCKETS = {
    "S3_BUCKET_IMAGES": "botfolio-cac-images",
    "S3_BUCKET_MODELS": "botfolio-cac-models",
    "S3_BUCKET_QUARANTINE": "botfolio-cac-quarantine",
}
CAC_ORIGIN = "https://botfoliosimple-production.up.railway.app"


def validate():
    if os.environ.get("CAC_ISOLATED_DEPLOYMENT") != "true":
        return

    required_ids = {
        "RAILWAY_PROJECT_ID": CAC_PROJECT_ID,
        "RAILWAY_SERVICE_ID": CAC_SERVICE_ID,
        "CAC_POSTGRES_SERVICE_ID": CAC_POSTGRES_SERVICE_ID,
    }
    for name, expected in {**required_ids, **CAC_BUCKETS}.items():
        if os.environ.get(name) != expected:
            raise RuntimeError(f"CAC isolation: invalid {name}")

    required = ("DATABASE_URL", "S3_ENDPOINT_URL", "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY", "FLASK_SECRET_KEY", "S3_IMAGES_PUBLIC_URL")
    for name in required:
        if not os.environ.get(name):
            raise RuntimeError(f"CAC isolation: missing {name}")
    if len(os.environ["FLASK_SECRET_KEY"]) < 32:
        raise RuntimeError("CAC isolation: FLASK_SECRET_KEY must be at least 32 characters")

    if os.environ.get("AWS_REGION") != "auto":
        raise RuntimeError("CAC isolation: AWS_REGION must be auto")
    if os.environ.get("SITE_URL") != CAC_ORIGIN:
        raise RuntimeError("CAC isolation: SITE_URL must be the CAC origin")
    if os.environ.get("S3_BUCKET") or os.environ.get("S3_PUBLIC_URL"):
        raise RuntimeError("CAC isolation: legacy shared bucket settings are forbidden")
    if os.environ.get("BOTFOLIO_DATA_DIR"):
        raise RuntimeError("CAC isolation: SQLite volume setting is forbidden")
    if os.environ.get("REDIS_URL"):
        raise RuntimeError("CAC isolation: Redis requires a dedicated CAC instance")
    for name in ("EMAILJS_PRIVATE_KEY", "EMAILJS_PUBLIC_KEY", "EMAILJS_SERVICE_ID",
                 "EMAILJS_TEMPLATE_ID", "BOTFOLIO_FROM_EMAIL", "CAC_EMAILJS_DEDICATED",
                 "GEMINI_API_KEY", "OPENAI_API_KEY",
                 "DISCORD_SHOWCASE_WEBHOOK_URL"):
        if os.environ.get(name):
            raise RuntimeError(f"CAC isolation: {name} requires a dedicated CAC credential")
    if os.environ.get("GOOGLE_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_SECRET"):
        if os.environ.get("GOOGLE_REDIRECT_URI") != CAC_ORIGIN + "/auth/google/callback":
            raise RuntimeError("CAC isolation: Google callback must use the CAC origin")
    endpoint = urlparse(os.environ["S3_ENDPOINT_URL"])
    if endpoint.scheme != "https" or endpoint.hostname != (
        "f49134581f8815cebd081da262395c56.r2.cloudflarestorage.com"
    ):
        raise RuntimeError("CAC isolation: unexpected R2 endpoint")
