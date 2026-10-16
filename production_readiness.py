"""Redacted production configuration audit for Botfolio deployments."""

import os


def _present(name):
    return bool((os.environ.get(name) or "").strip())


def audit_environment(environ=None):
    """Return checks without returning or logging any secret values."""
    env = environ if environ is not None else os.environ

    def present(name):
        return bool((env.get(name) or "").strip())

    production = (env.get("APP_ENV") or env.get("RAILWAY_ENVIRONMENT_NAME") or "").lower() in {
        "production", "prod"
    }
    checks = [
        ("production environment", production, "Set APP_ENV=production."),
        ("stable session secret", present("FLASK_SECRET_KEY"), "Set a stable random FLASK_SECRET_KEY."),
        ("PostgreSQL database", present("DATABASE_URL"), "Attach PostgreSQL and set DATABASE_URL."),
        ("persistent image storage", present("S3_BUCKET_IMAGES") or present("S3_BUCKET"), "Set S3_BUCKET_IMAGES."),
        ("persistent model storage", present("S3_BUCKET_MODELS") or present("S3_BUCKET"), "Set S3_BUCKET_MODELS."),
        ("upload quarantine", present("S3_BUCKET_QUARANTINE"), "Set S3_BUCKET_QUARANTINE."),
        ("object-storage endpoint", present("S3_ENDPOINT_URL"), "Set the Cloudflare R2 endpoint URL."),
        ("object-storage credentials", present("AWS_ACCESS_KEY_ID") and present("AWS_SECRET_ACCESS_KEY"), "Set the R2 access key and secret."),
        ("public image URL", present("S3_IMAGES_PUBLIC_URL") or present("S3_PUBLIC_URL"), "Set S3_IMAGES_PUBLIC_URL."),
        ("HTTPS enforcement", (env.get("FORCE_HTTPS") or "").lower() in {"1", "true", "yes", "on"}, "Set FORCE_HTTPS=true."),
        ("trusted reverse proxy", (env.get("BEHIND_PROXY") or "").lower() in {"1", "true", "yes", "on"}, "Set BEHIND_PROXY=true."),
        ("email service", all(present(n) for n in ("EMAILJS_SERVICE_ID", "EMAILJS_TEMPLATE_ID", "EMAILJS_PUBLIC_KEY")), "Set the EmailJS service, template, and public key."),
        ("domain sender", (env.get("BOTFOLIO_FROM_EMAIL") or "").strip().lower().endswith("@botfoliohq.com"), "Set BOTFOLIO_FROM_EMAIL to a verified @botfoliohq.com sender."),
        ("sender name", present("BOTFOLIO_FROM_NAME"), "Set BOTFOLIO_FROM_NAME=Botfolio."),
        ("metrics protection", present("METRICS_TOKEN"), "Set a stable random METRICS_TOKEN."),
    ]
    optional = [
        ("OpenAI design feedback", present("OPENAI_API_KEY"), "Set OPENAI_API_KEY to enable AI feedback."),
        ("shared Redis", present("REDIS_URL"), "Set REDIS_URL when using multiple replicas/workers for shared counters."),
    ]
    return {"required": checks, "optional": optional}


def format_report(result):
    lines = ["Botfolio production-readiness audit", ""]
    for heading, checks in (("Required", result["required"]), ("Optional / scale-dependent", result["optional"])):
        lines.append(heading + ":")
        for name, passed, remedy in checks:
            lines.append(f"  [{'PASS' if passed else 'FAIL'}] {name}")
            if not passed:
                lines.append(f"         {remedy}")
        lines.append("")
    failed = sum(not passed for _, passed, _ in result["required"])
    lines.append(f"Required checks failed: {failed}")
    return "\n".join(lines)


def main():
    result = audit_environment()
    print(format_report(result))
    return 1 if any(not passed for _, passed, _ in result["required"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
