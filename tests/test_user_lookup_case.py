"""Finding an account must not depend on how its owner capitalised it.

schema.sql declares username and email `UNIQUE COLLATE NOCASE`, which in SQLite
makes *both* uniqueness and every `WHERE email = ?` case-insensitive. Postgres
has no NOCASE, so infra/database.py strips it and puts the uniqueness half back
as unique indexes on `lower(username)` and `lower(email)`. Nothing put the
lookup half back, so on Postgres alone an account registered as
"Friend@Gmail.com" was invisible to every query that searched for
"friend@gmail.com" — while still occupying the name.

That produced a locked-out account nobody could see: the reset email went
nowhere (and still said it had been sent), signing up again hit the unique index
instead of the friendly "already registered", and the row could not be found by
hand either.

These tests therefore build SQLite in the *Postgres* shape — NOCASE removed, the
lower() indexes added — because a stock SQLite database cannot reproduce the bug
and would pass either way.
"""

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import db

REPO_ROOT = Path(__file__).resolve().parent.parent

# Postgres gets these from install_compat(). SQLite has supported indexes on an
# expression since 3.9, so the same two statements reproduce it exactly.
CASE_INSENSITIVE_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_ci ON users (lower(username));
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_ci    ON users (lower(email));
"""

PASSWORD = "supersecret1"


def build_postgres_shaped_db(path):
    """Create the app's schema the way Postgres ends up holding it."""
    schema = (REPO_ROOT / "schema.sql").read_text(encoding="utf-8")
    schema = re.sub(r"\s+COLLATE\s+NOCASE\b", "", schema, flags=re.I)
    conn = sqlite3.connect(path)
    conn.executescript(schema)
    conn.executescript(CASE_INSENSITIVE_INDEXES)
    conn.commit()
    conn.close()


class CaseFoldedLookupTests(unittest.TestCase):
    """The account was created with capitals; everything else uses lower case."""

    STORED_EMAIL = "Friend@Gmail.com"
    STORED_USERNAME = "Friend_Nine"

    def setUp(self):
        import app as application

        self.application = application
        self.application.app.testing = True
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "test.db"
        build_postgres_shaped_db(path)
        self.db_patch = patch.object(db, "DB_PATH", path)
        self.db_patch.start()

        conn = db.connect()
        conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete) "
            "VALUES (?,?,?,1)",
            (self.STORED_USERNAME, self.STORED_EMAIL,
             generate_password_hash(PASSWORD)),
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

    def _query(self, sql, params=()):
        conn = db.connect()
        try:
            return conn.execute(sql, params).fetchone()
        finally:
            conn.close()

    def _register(self, username, email):
        token = self._csrf("/register")
        with patch.object(self.application, "send_verification_email",
                          return_value=True):
            return self.client.post("/register", data={
                "username": username, "email": email, "password": PASSWORD,
                "company": "", "age_13_confirmed": "yes",
                "legal_policies_accepted": "yes",
                "minor_permission_confirmed": "yes", "csrf_token": token,
            }, follow_redirects=True)

    # -- the database really is in the shape that broke -------------------

    def test_the_fixture_reproduces_the_postgres_shape(self):
        """A guard on the test itself: stock SQLite would pass either way."""
        row = self._query("SELECT sql FROM sqlite_master WHERE name='users'")
        self.assertNotIn("NOCASE", row["sql"].upper())
        found = self._query(
            "SELECT id FROM users WHERE email = ?", ("friend@gmail.com",))
        self.assertIsNone(found, "lookups must be case-sensitive here")
        with self.assertRaises(sqlite3.IntegrityError):
            conn = db.connect()
            try:
                conn.execute(
                    "INSERT INTO users(username,email,password_hash) "
                    "VALUES (?,?,?)",
                    ("someone_else", "friend@gmail.com", "x"),
                )
                conn.commit()
            finally:
                conn.close()

    # -- symptom 1: the reset email went nowhere --------------------------

    def test_password_reset_finds_an_account_stored_with_capitals(self):
        token = self._csrf("/forgot-password")
        with patch.object(self.application.email_service, "send_email",
                          return_value=True) as send:
            self.client.post("/forgot-password", data={
                "email": "friend@gmail.com", "company": "",
                "csrf_token": token,
            })
        self.assertTrue(send.called, "no reset email was sent")
        self.assertEqual(send.call_args.kwargs["to_email"], self.STORED_EMAIL)
        self.assertIsNotNone(
            self._query("SELECT id FROM password_reset_tokens"),
            "no reset token was issued",
        )

    def test_a_reset_email_that_fails_to_send_is_logged(self):
        token = self._csrf("/forgot-password")
        with patch.object(self.application.email_service, "send_email",
                          return_value=False):
            with self.assertLogs(self.application.app.logger, "ERROR") as logged:
                self.client.post("/forgot-password", data={
                    "email": "friend@gmail.com", "company": "",
                    "csrf_token": token,
                })
        self.assertIn("could not be sent", "\n".join(logged.output))

    # -- symptom 2: signing up again ------------------------------------

    def test_signing_up_again_is_refused_politely_not_with_a_500(self):
        response = self._register("friend_nine", "friend@gmail.com")
        self.assertEqual(response.status_code, 200)
        self.assertIn("already registered", response.get_data(as_text=True))

    def test_a_differently_cased_email_alone_is_enough_to_clash(self):
        response = self._register("someone_new", "FRIEND@GMAIL.COM")
        self.assertEqual(response.status_code, 200)
        self.assertIn("already registered", response.get_data(as_text=True))

    def test_an_unrelated_signup_still_works(self):
        response = self._register("brand_new", "brand@new.example")
        self.assertIsNotNone(
            self._query("SELECT id FROM users WHERE email='brand@new.example'"))

    # -- and the account can be signed into at all ------------------------

    def test_login_accepts_the_email_in_any_case(self):
        token = self._csrf("/login")
        self.client.post("/login", data={
            "username": "friend@gmail.com", "password": PASSWORD,
            "csrf_token": token,
        })
        with self.client.session_transaction() as browser_session:
            self.assertIn("user_id", browser_session)

    def test_login_accepts_the_username_in_any_case(self):
        token = self._csrf("/login")
        self.client.post("/login", data={
            "username": "FRIEND_NINE", "password": PASSWORD,
            "csrf_token": token,
        })
        with self.client.session_transaction() as browser_session:
            self.assertIn("user_id", browser_session)

    def test_the_profile_page_is_reachable_in_any_case(self):
        response = self.client.get("/u/friend_nine")
        self.assertEqual(response.status_code, 200)


def route_sources():
    """Every file that holds a view, wherever the routes currently live."""
    return [REPO_ROOT / "app.py", *sorted((REPO_ROOT / "routes").glob("*.py"))]


class NoCaseSensitiveLookupsRemainTests(unittest.TestCase):
    """A source guard, so the next `WHERE email = ?` does not slip back in."""

    def test_no_user_lookup_compares_a_name_or_email_directly(self):
        for path in route_sources():
            with self.subTest(path=path.name):
                offenders = re.findall(
                    r"(?:WHERE|OR|AND)\s+(?:username|email)\s*=\s*\?",
                    path.read_text(encoding="utf-8"),
                )
                self.assertEqual(
                    offenders, [],
                    "user lookups must compare lower(column) = lower(?), because "
                    "COLLATE NOCASE is stripped for Postgres: %r" % (offenders,),
                )

    def test_the_registration_insert_is_guarded(self):
        sources = [p.read_text(encoding="utf-8") for p in route_sources()]
        self.assertTrue(
            any("except db.INTEGRITY_ERRORS:" in source for source in sources),
            "register must catch the UNIQUE violation the clash check can miss",
        )

    def test_integrity_errors_covers_the_backend_in_use(self):
        self.assertIn(sqlite3.IntegrityError, db.INTEGRITY_ERRORS)


if __name__ == "__main__":
    unittest.main()
