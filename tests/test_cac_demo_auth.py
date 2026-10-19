"""CAC keeps password sign-in while disabling all email flows."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db


class CacDemoAuthTests(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        self.application.app.testing = True
        self.demo_env = patch.dict(os.environ, {"CAC_ISOLATED_DEPLOYMENT": "true"})
        self.demo_env.start()
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent)
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "cac.db")
        self.db_patch.start()
        db.init_db()
        self.client = self.application.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()
        self.demo_env.stop()
        self.application.app.testing = False

    def csrf(self, path):
        self.client.get(path)
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def test_registration_needs_no_email_verification(self):
        token = self.csrf("/register")
        with patch.object(self.application.email_service, "send_email") as send:
            response = self.client.post("/register", data={
                "username": "demo_user", "email": "demo@example.test",
                "password": "password123", "company": "",
                "age_13_confirmed": "yes", "legal_policies_accepted": "yes",
                "minor_permission_confirmed": "yes", "csrf_token": token,
            })
        self.assertEqual(response.status_code, 302)
        send.assert_not_called()
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT email_verified_at FROM users WHERE username='demo_user'"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertIsNone(row["email_verified_at"])
        finally:
            conn.close()

    def test_reset_notice_creates_no_token_or_email(self):
        login = self.client.get("/login")
        self.assertIn(b'data-demo-reset-link', login.data)
        self.assertIn(b'id="demo-reset-dialog"', login.data)
        token = self.csrf("/forgot-password")
        with patch.object(self.application.email_service, "send_email") as send:
            response = self.client.post("/forgot-password", data={
                "email": "demo@example.test", "csrf_token": token,
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No email was sent", response.data)
        send.assert_not_called()
        conn = db.connect()
        try:
            count = conn.execute("SELECT COUNT(*) AS n FROM password_reset_tokens").fetchone()["n"]
            self.assertEqual(count, 0)
        finally:
            conn.close()
        self.assertEqual(self.client.get("/reset-password/token").status_code, 404)

    def test_mail_provider_is_disabled_for_cac(self):
        with patch("urllib.request.urlopen") as request:
            sent = self.application.email_service.send_email(
                to_email="demo@example.test", to_name="Demo",
                subject="Demo", heading="Demo", message="Demo",
            )
        self.assertFalse(sent)
        request.assert_not_called()

    def test_cac_uses_local_moderation_without_main_api_key(self):
        from services import openai_service

        with patch.object(openai_service, "_client") as client:
            openai_service.moderate_public_content(texts=["demo robot"], use_api=True)
        client.assert_not_called()
        with self.assertRaises(openai_service.ModerationRejected):
            openai_service.moderate_public_content(texts=["fuck"], use_api=True)


if __name__ == "__main__":
    unittest.main()
