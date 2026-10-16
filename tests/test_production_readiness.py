import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import db

from production_readiness import audit_environment, format_report


class ProductionReadinessTests(unittest.TestCase):
    def test_liveness_ignores_missing_schema_but_readiness_reports_it(self):
        import app as application

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            with patch.object(db, "DB_PATH", Path(directory) / "empty.db"):
                previous_testing = application.app.testing
                previous_purge = application._last_ai_chat_purge
                try:
                    application.app.testing = False
                    application._last_ai_chat_purge = 0
                    client = application.app.test_client()
                    self.assertEqual(client.get("/healthz").status_code, 200)
                    readiness = client.get("/readyz")
                    self.assertEqual(readiness.status_code, 503)
                    self.assertEqual(readiness.json["checks"]["database"], "error: RuntimeError")
                finally:
                    application.app.testing = previous_testing
                    application._last_ai_chat_purge = previous_purge

    def test_complete_environment_passes_required_checks(self):
        env = {
            "APP_ENV": "production", "FLASK_SECRET_KEY": "secret", "DATABASE_URL": "postgres://configured",
            "S3_BUCKET_IMAGES": "images", "S3_BUCKET_MODELS": "models", "S3_BUCKET_QUARANTINE": "quarantine",
            "S3_ENDPOINT_URL": "https://r2.example", "AWS_ACCESS_KEY_ID": "id", "AWS_SECRET_ACCESS_KEY": "secret",
            "S3_IMAGES_PUBLIC_URL": "https://assets.example", "FORCE_HTTPS": "true", "BEHIND_PROXY": "true",
            "EMAILJS_SERVICE_ID": "service", "EMAILJS_TEMPLATE_ID": "template", "EMAILJS_PUBLIC_KEY": "public",
            "BOTFOLIO_FROM_EMAIL": "noreply@botfoliohq.com", "BOTFOLIO_FROM_NAME": "Botfolio",
            "METRICS_TOKEN": "metrics",
        }
        result = audit_environment(env)
        self.assertTrue(all(passed for _, passed, _ in result["required"]))

    def test_railway_volume_passes_storage_checks(self):
        env = {
            "RAILWAY_ENVIRONMENT_NAME": "production", "FLASK_SECRET_KEY": "secret",
            "BOTFOLIO_DATA_DIR": "/data", "RAILWAY_VOLUME_MOUNT_PATH": "/data",
            "RAILWAY_RUN_UID": "0", "EMAILJS_SERVICE_ID": "service",
            "EMAILJS_TEMPLATE_ID": "template", "EMAILJS_PUBLIC_KEY": "public",
            "BOTFOLIO_FROM_EMAIL": "noreply@botfoliohq.com",
        }
        result = audit_environment(env)
        self.assertTrue(all(passed for _, passed, _ in result["required"]), format_report(result))

    def test_report_never_contains_secret_values(self):
        secret = "do-not-print-this"
        report = format_report(audit_environment({"FLASK_SECRET_KEY": secret}))
        self.assertNotIn(secret, report)


if __name__ == "__main__":
    unittest.main()
