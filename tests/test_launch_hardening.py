"""Pre-launch hardening: the honeypot, the report-URL scheme guard, the image
decompression-bomb cap, the static-model lockout, and the SEO surfaces
(sitemap, robots, canonical, structured data).

These are all "does not regress" tests: each protection is easy to remove by
accident in an unrelated change, and every one of them is invisible in normal
use, so nothing else would notice it was gone.
"""

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash
from PIL import Image

import db


class RequestHardeningTests(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        # testing=True makes the moderation helper skip its network call.
        self.application.app.testing = True
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "test.db")
        self.db_patch.start()
        db.init_db()
        conn = db.connect()
        conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete) "
            "VALUES (?,?,?,1)",
            ("session_user", "session@example.com", generate_password_hash("password123")),
        )
        conn.commit()
        conn.close()
        self.client = self.application.app.test_client()

    def tearDown(self):
        self.application.app.testing = False
        self.db_patch.stop()
        self.temp.cleanup()

    def _csrf(self, path):
        self.client.get(path)
        with self.client.session_transaction() as browser_session:
            return browser_session["csrf_token"]

    def _user_count(self):
        conn = db.connect()
        try:
            return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        finally:
            conn.close()

    # --- Honeypot ----------------------------------------------------------
    def test_registration_honeypot_creates_no_account(self):
        before = self._user_count()
        token = self._csrf("/register")
        response = self.client.post("/register", data={
            "username": "bot_signup", "email": "bot@example.com",
            "password": "supersecret1", "company": "Acme Bots",
            "age_13_confirmed": "yes", "legal_policies_accepted": "yes",
            "minor_permission_confirmed": "yes", "csrf_token": token,
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers.get("Location", ""))
        self.assertEqual(self._user_count(), before)

    def test_registration_without_honeypot_still_works(self):
        before = self._user_count()
        token = self._csrf("/register")
        with patch.object(self.application, "send_verification_email", return_value=True):
            response = self.client.post("/register", data={
                "username": "real_person", "email": "real@example.com",
                "password": "supersecret1", "company": "",
                "age_13_confirmed": "yes", "legal_policies_accepted": "yes",
                "minor_permission_confirmed": "yes", "csrf_token": token,
            })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._user_count(), before + 1)

    def test_forgot_password_honeypot_sends_no_email(self):
        token = self._csrf("/forgot-password")
        with patch.object(self.application.email_service, "send_email") as send:
            self.client.post("/forgot-password", data={
                "email": "session@example.com", "company": "Acme Bots",
                "csrf_token": token,
            })
        send.assert_not_called()

    def test_forgot_password_without_honeypot_sends_email(self):
        token = self._csrf("/forgot-password")
        with patch.object(self.application.email_service, "send_email") as send:
            self.client.post("/forgot-password", data={
                "email": "session@example.com", "company": "",
                "csrf_token": token,
            })
        send.assert_called_once()

    # --- Static model lockout ---------------------------------------------
    def test_static_models_path_is_blocked(self):
        self.assertEqual(self.client.get("/static/models/secret.glb").status_code, 404)

    def test_static_model_normalisation_bypasses_are_blocked(self):
        """Flask's static handler collapses dot-segments and (on a
        case-insensitive filesystem) case before serving, so a raw startswith
        on request.path is trivially sidestepped: /static/./models/x,
        /static/a/../models/x, a trailing slash, or /static/Models/x all reach
        the same gated file. The guard must match the *normalised* path.

        A real file is planted under static/models so a leaked byte would be a
        200, not a 404-for-missing — that is what makes the 404s below
        attributable to the guard rather than to the file simply not existing.
        """
        from pathlib import Path as _Path
        models_dir = _Path(self.application.app.static_folder) / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        probe = models_dir / "hardening_probe.glb"
        probe.write_bytes(b"gated-model-bytes")
        try:
            # Control: dot-segment paths genuinely reach the static handler and
            # serve a real file through this client — so the 404s below are the
            # guard doing its job, not the request path being rejected upstream.
            control = self.client.get("/static/x/../style.css")
            self.assertEqual(control.status_code, 200)
            control.close()  # release the served file handle (ResourceWarning)
            for path in (
                "/static/models/hardening_probe.glb",
                "/static/./models/hardening_probe.glb",
                "/static/x/../models/hardening_probe.glb",
                "/static/models/hardening_probe.glb/",
                "/static/Models/hardening_probe.glb",
            ):
                self.assertEqual(
                    self.client.get(path).status_code, 404,
                    f"{path} leaked the gated model",
                )
        finally:
            probe.unlink(missing_ok=True)

    # --- SEO surfaces ------------------------------------------------------
    def test_robots_advertises_the_sitemap(self):
        body = self.client.get("/robots.txt").get_data(as_text=True)
        self.assertIn("Sitemap: http", body)
        self.assertIn("/sitemap.xml", body)

    def test_sitemap_is_valid_xml_and_lists_pages(self):
        import xml.dom.minidom as minidom
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/xml", response.content_type)
        body = response.get_data(as_text=True)
        minidom.parseString(body)  # raises if malformed
        self.assertIn("<urlset", body)
        self.assertIn("<loc>http", body)

    def test_home_has_canonical_and_structured_data(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn('rel="canonical"', body)
        self.assertIn('"@type": "WebSite"', body)
        self.assertIn('"@type": "Organization"', body)


class ReportUrlGuardTests(unittest.TestCase):
    """The Jinja filter that decides whether a reported-content URL is safe to
    turn into a clickable link in the moderation queue."""

    def setUp(self):
        import app as application
        self.filter = application.app.jinja_env.filters["safe_report_url"]

    def test_javascript_scheme_is_neutralised(self):
        self.assertEqual(self.filter("javascript:alert(document.cookie)"), "")

    def test_data_scheme_is_neutralised(self):
        self.assertEqual(self.filter("data:text/html,<script>alert(1)</script>"), "")

    def test_scheme_relative_url_is_neutralised(self):
        self.assertEqual(self.filter("//evil.example.com/x"), "")

    def test_plain_http_and_https_pass_through(self):
        self.assertEqual(self.filter("https://example.com/report"),
                         "https://example.com/report")
        self.assertEqual(self.filter("http://example.com/report"),
                         "http://example.com/report")


class DecompressionBombTests(unittest.TestCase):
    """A tiny file whose declared pixel dimensions are enormous must be rejected
    with a friendly ValueError, not crash a worker on memory."""

    def test_oversized_image_raises_value_error(self):
        from app import sanitize_image_bytes

        original = Image.MAX_IMAGE_PIXELS
        try:
            # Lower the cap so a cheap 200x200 image trips the same guard a real
            # 20000x20000 decompression bomb would. 40000 px is above 2x the cap
            # (20), the band where Pillow itself raises DecompressionBombError.
            Image.MAX_IMAGE_PIXELS = 10
            buffer = io.BytesIO()
            Image.new("RGB", (200, 200), "white").save(buffer, format="PNG")
            with self.assertRaises(ValueError):
                sanitize_image_bytes(buffer.getvalue())
        finally:
            Image.MAX_IMAGE_PIXELS = original

    def test_image_in_1x_to_2x_band_is_rejected(self):
        """Pillow only *raises* above 2x its cap; between 1x and 2x it merely
        warns and decodes. Our own header check must reject that band, since a
        99 MP file lives there and would otherwise allocate ~280 MB before any
        downscale. This drives app.MAX_IMAGE_PIXELS (the app's own ceiling),
        not Pillow's, and picks a size inside the warn-only band."""
        import app as application

        original = application.MAX_IMAGE_PIXELS
        try:
            application.MAX_IMAGE_PIXELS = 10  # app ceiling: 10 px
            buffer = io.BytesIO()
            # 4x4 = 16 px: over the app's 10-px cap, but under Pillow's 20-px
            # (2x) raise threshold — Pillow would only warn here.
            Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
            with self.assertRaises(ValueError):
                application.sanitize_image_bytes(buffer.getvalue())
        finally:
            application.MAX_IMAGE_PIXELS = original


class EnvironmentClassificationTests(unittest.TestCase):
    """is_local decides whether an ephemeral secret key, plain HTTP, and no HSTS
    are acceptable. It must treat an *unrecognised* environment label as a real
    deployment (secure defaults on), not silently as local."""

    def _settings_for(self, label):
        # A clean slate so an inherited RAILWAY_ENVIRONMENT_NAME / FORCE_HTTPS on
        # the test machine can't skew the classification.
        keep = {k: v for k, v in os.environ.items() if k not in {
            "APP_ENV", "RAILWAY_ENVIRONMENT_NAME",
            "FORCE_HTTPS", "HSTS_SECONDS", "BEHIND_PROXY", "LOG_JSON",
        }}
        keep["APP_ENV"] = label
        with patch.dict("os.environ", keep, clear=True):
            from infra.settings import Settings
            return Settings()

    def test_unknown_label_is_treated_as_hosted(self):
        for label in ("live", "prod-eu", "release", "renamed-env"):
            cfg = self._settings_for(label)
            self.assertFalse(cfg.is_local, label)
            # …and the secure defaults follow from that classification.
            self.assertTrue(cfg.force_https, label)
            self.assertTrue(cfg.hsts_seconds > 0, label)

    def test_known_local_labels_stay_local(self):
        for label in ("development", "dev", "local", "test", "testing"):
            self.assertTrue(self._settings_for(label).is_local, label)

    def test_production_and_staging_are_hosted(self):
        for label in ("production", "prod", "staging", "stage"):
            self.assertFalse(self._settings_for(label).is_local, label)


if __name__ == "__main__":
    unittest.main()
