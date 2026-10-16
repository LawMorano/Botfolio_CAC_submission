import unittest

from production_readiness import audit_environment, format_report


class ProductionReadinessTests(unittest.TestCase):
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

    def test_report_never_contains_secret_values(self):
        secret = "do-not-print-this"
        report = format_report(audit_environment({"FLASK_SECRET_KEY": secret}))
        self.assertNotIn(secret, report)


if __name__ == "__main__":
    unittest.main()
