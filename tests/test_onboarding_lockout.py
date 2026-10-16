"""A half-onboarded account must never be able to get stuck.

`require_account_setup` redirects a user with `onboarding_complete = 0` to
/account/setup from everywhere else, which makes that one page load-bearing:
if it 500s, every other page 302s into it and the account is bricked. The
sign-out button lives on a page that will not render, so the user cannot even
leave. Nothing else in the suite exercises this state -- every other test seeds
`onboarding_complete = 1` -- which is how it reached production unnoticed.

These tests pin the three properties that keep the state escapable:
  * the notification badge cannot take the page down with it,
  * an unroutable request answers for itself instead of being swept into
    onboarding,
  * GET /logout is always a way out.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import db


class OnboardingLockoutTests(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        self.application.app.testing = True
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "test.db")
        self.db_patch.start()
        db.init_db()
        conn = db.connect()
        conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete) "
            "VALUES (?,?,?,0)",
            ("newcomer", "newcomer@example.com", generate_password_hash("password123")),
        )
        conn.commit()
        conn.close()
        self.client = self.application.app.test_client()
        self._sign_in()

    def tearDown(self):
        self.application.app.testing = False
        self.db_patch.stop()
        self.temp.cleanup()

    def _sign_in(self):
        token = self._csrf("/login")
        self.client.post("/login", data={
            "username": "newcomer", "password": "password123", "csrf_token": token,
        })

    def _csrf(self, path):
        self.client.get(path)
        with self.client.session_transaction() as browser_session:
            return browser_session["csrf_token"]

    def _drop(self, *tables):
        conn = db.connect()
        for table in tables:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
        conn.close()

    def test_setup_page_is_the_landing_place(self):
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/account/setup", response.headers["Location"])
        self.assertEqual(self.client.get("/account/setup").status_code, 200)

    def test_onboarding_pages_stay_exempt_once_they_live_in_a_blueprint(self):
        """The exemptions are endpoint names, and moving a view renames it.

        A view in a Blueprint reports "auth.account_setup" where the same view
        reported "account_setup" from app.py. If the guard misses the rename it
        redirects the setup page to itself, which is the exact lockout these
        tests exist to prevent -- so pin the names it actually sees.
        """
        seen = {}
        for path in ("/account/setup", "/account/setup/interests",
                     "/account/setup/role", "/account/setup/team", "/logout"):
            with self.application.app.test_request_context(path):
                from flask import request
                seen[path] = request.endpoint
            self.assertEqual(
                self.client.get(path).status_code, 200,
                f"{path} redirected instead of rendering; its endpoint is "
                f"{seen[path]!r} and the guard did not exempt it",
            )

    def test_unreadable_notification_count_does_not_break_the_page(self):
        """The badge is decoration; losing it must not cost the whole account.

        Dropping the tables it reads stands in for any way that one query can
        fail on a database the app did not build itself -- a migration that was
        skipped, a column that never landed, a connection already in a failed
        transaction.
        """
        self._drop("notifications", "team_membership_requests")
        response = self.client.get("/account/setup")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Set up your profile", response.data)

    def test_the_error_page_survives_what_broke_the_page(self):
        """error.html renders through the same processor, so it must be fenced too."""
        self._drop("notifications", "team_membership_requests")
        response = self.client.get("/no-such-page")
        self.assertEqual(response.status_code, 404)
        self.assertIn(b"No such page", response.data)

    def test_unroutable_request_is_not_swept_into_onboarding(self):
        """A 404 must stay a 404, or every typo becomes a redirect."""
        self.assertEqual(self.client.get("/no-such-page").status_code, 404)

    def test_signing_out_is_always_reachable(self):
        response = self.client.get("/logout")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Sign out", response.data)

        token = self._csrf("/account/setup")
        response = self.client.post("/logout", data={"csrf_token": token})
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as browser_session:
            self.assertNotIn("user_id", browser_session)


if __name__ == "__main__":
    unittest.main()
