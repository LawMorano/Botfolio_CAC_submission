import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash
from PIL import Image

import db
from infra import security


class SecurityPolicyTests(unittest.TestCase):
    def test_csp_allows_public_images_and_direct_storage_uploads(self):
        with (
            patch.object(security.settings, "s3_bucket_images", "images"),
            patch.object(security.settings, "s3_bucket_models", "models"),
            patch.object(
                security.settings,
                "s3_images_public_url",
                "https://assets.botfoliohq.com",
            ),
            patch.object(
                security.settings,
                "s3_endpoint",
                "https://account.r2.cloudflarestorage.com/storage/path",
            ),
        ):
            policy = security._csp()

        image_policy = next(
            directive for directive in policy.split("; ")
            if directive.startswith("img-src ")
        )
        connect_policy = next(
            directive for directive in policy.split("; ")
            if directive.startswith("connect-src ")
        )
        self.assertIn("https://assets.botfoliohq.com", image_policy)
        self.assertIn("https://account.r2.cloudflarestorage.com", connect_policy)
        self.assertNotIn("/storage/path", connect_policy)

    def test_csp_ignores_invalid_storage_endpoint(self):
        with (
            patch.object(security.settings, "s3_bucket_images", "images"),
            patch.object(security.settings, "s3_bucket_models", "models"),
            patch.object(security.settings, "s3_endpoint", "not a URL"),
        ):
            policy = security._csp()

        self.assertNotIn("not a URL", policy)

    def test_image_sanitization_removes_exif_and_precise_gps(self):
        import app as application

        original = io.BytesIO()
        image = Image.new("RGB", (32, 32), "blue")
        exif = Image.Exif()
        exif[315] = "Test Photographer"
        exif[34853] = {
            1: "N",
            2: (40.0, 44.0, 54.0),
            3: "W",
            4: (73.0, 59.0, 8.0),
        }
        image.save(original, format="JPEG", exif=exif)
        with Image.open(io.BytesIO(original.getvalue())) as source:
            self.assertTrue(source.getexif().get_ifd(34853))

        cleaned = application.sanitize_image_bytes(original.getvalue())

        with Image.open(io.BytesIO(cleaned)) as public_image:
            self.assertEqual(dict(public_image.getexif()), {})
            self.assertFalse(public_image.getexif().get_ifd(34853))


class AuthenticatedSessionTests(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        self.application.app.testing = False
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "test.db")
        self.db_patch.start()
        db.init_db()
        conn = db.connect()
        cursor = conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete) "
            "VALUES (?,?,?,1)",
            ("session_user", "session@example.com", generate_password_hash("password123")),
        )
        self.user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        self.client = self.application.app.test_client()

    def tearDown(self):
        self.application.app.testing = False
        self.db_patch.stop()
        self.temp.cleanup()

    def _login(self):
        self.client.get("/login")
        with self.client.session_transaction() as browser_session:
            csrf = browser_session["csrf_token"]
        response = self.client.post(
            "/login",
            data={
                "username": "session_user",
                "password": "password123",
                "csrf_token": csrf,
            },
        )
        self.assertEqual(response.status_code, 302)
        return response

    def test_login_cookie_is_hardened_and_expires(self):
        with patch.dict(
            self.application.app.config,
            {"SESSION_COOKIE_SECURE": True},
        ):
            response = self._login()

        cookie = response.headers.get("Set-Cookie", "")
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Expires=", cookie)

    def test_logout_rejects_history_and_replayed_cookie(self):
        self._login()
        account = self.client.get("/account")
        self.assertEqual(account.status_code, 200)
        self.assertEqual(
            account.headers["Cache-Control"], "no-store, private, max-age=0"
        )
        old_cookie = self.client.get_cookie("session").value
        with self.client.session_transaction() as browser_session:
            csrf = browser_session["csrf_token"]

        logout = self.client.post("/logout", data={"csrf_token": csrf})
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(logout.headers["Clear-Site-Data"], '"cache"')
        self.assertEqual(self.client.get("/account").status_code, 302)

        replay = self.application.app.test_client()
        replay.set_cookie("session", old_cookie)
        rejected = replay.get("/account")
        self.assertEqual(rejected.status_code, 302)
        self.assertIn("/login?next=/account", rejected.headers["Location"])

    def test_expired_server_session_is_rejected(self):
        self._login()
        conn = db.connect()
        conn.execute(
            "UPDATE user_sessions SET expires_at=datetime('now', '-1 second') "
            "WHERE user_id=?",
            (self.user_id,),
        )
        conn.commit()
        conn.close()

        response = self.client.get("/account")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login?next=/account", response.headers["Location"])

    def test_changed_legal_documents_are_explained_after_login(self):
        response = self._login()
        self.assertTrue(response.headers["Location"].endswith("/legal-updates"))
        notice = self.client.get("/legal-updates")
        self.assertIn(b"what changed", notice.data)
        self.assertIn(b"Why:", notice.data)
        self.assertIn(b"Privacy Policy", notice.data)
        with self.client.session_transaction() as browser_session:
            csrf = browser_session["csrf_token"]
        acknowledged = self.client.post("/legal-updates", data={"csrf_token": csrf})
        self.assertEqual(acknowledged.status_code, 302)
        conn = db.connect()
        user = conn.execute(
            "SELECT acknowledged_legal_version,acknowledged_legal_at FROM users WHERE id=?",
            (self.user_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(user["acknowledged_legal_version"], self.application.LEGAL_NOTICE_VERSION)
        self.assertIsNotNone(user["acknowledged_legal_at"])

    def test_error_pages_keep_legal_footer_links(self):
        missing = self.client.get("/definitely-not-a-real-page")
        self.assertEqual(missing.status_code, 404)
        self.assertIn(b"Terms of Use", missing.data)
        self.assertIn(b"Privacy Policy", missing.data)
        with self.application.app.test_request_context("/"):
            rendered, status = self.application.internal_error(None)
        self.assertEqual(status, 500)
        self.assertIn(b"Terms of Use", rendered.encode())
        self.assertIn(b"Privacy Policy", rendered.encode())


if __name__ == "__main__":
    unittest.main()
