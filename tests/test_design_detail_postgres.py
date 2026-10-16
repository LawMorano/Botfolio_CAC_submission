"""A design page must not emit SQL that only SQLite accepts.

The tag-suggestion box scopes its query to the design's season and model type.
A design that has neither -- which is every design published without picking
them -- left the scope clause as the bare literal `1`, so the query went out as
`... AND 1`. SQLite treats that as true; PostgreSQL rejects it outright with
"argument of AND must be type boolean, not type integer", which took the whole
page down with a 500.

That mattered far beyond the page itself: /submit finishes by redirecting to
the new design, and the publish form follows that redirect over XHR. A 500 here
was reported to the author as "Publishing failed (500)" even though the upload
had succeeded and the design row was committed.

These tests run on SQLite, where the bad SQL is accepted, so the guard is on
the shape of the statements rather than on the status code alone.
"""

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import db

# An integer literal standing on its own as an operand of AND/OR. `AND 1=1` is
# a boolean expression and fine; `AND 1` is the SQLite-only form.
INTEGER_AS_BOOLEAN = re.compile(r"\b(?:AND|OR)\s+\d+(?!\s*[=<>!])", re.I)


class DesignDetailPostgresSafetyTests(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        application.app.testing = True
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "test.db")
        self.db_patch.start()
        db.init_db()
        application.ratelimit._buckets.clear()

        self.statements = []
        real_connect = db.connect

        def recording_connect():
            conn = real_connect()
            if isinstance(conn, sqlite3.Connection):
                conn.set_trace_callback(self.statements.append)
            return conn

        self.connect_patch = patch.object(db, "connect", recording_connect)
        self.connect_patch.start()

        self.client = application.app.test_client()

    def tearDown(self):
        self.connect_patch.stop()
        self.db_patch.stop()

    def seed_design(self, season_id=None, archetype_id=None):
        conn = db.connect()
        try:
            user_id = conn.execute(
                "INSERT INTO users(username,email,password_hash,onboarding_complete,"
                "email_verified_at) VALUES (?,?,?,1,datetime('now'))",
                ("owner", "owner@example.com",
                 generate_password_hash("correct-horse", method="pbkdf2:sha256:1")),
            ).lastrowid
            design_id = conn.execute(
                "INSERT INTO designs(user_id,title,description,image_filename,"
                "season_id,archetype_id,upload_status) "
                "VALUES (?,?,'Competition intake','preview.jpg',?,?,'approved')",
                (user_id, "Intake", season_id, archetype_id),
            ).lastrowid
            conn.commit()
            return design_id
        finally:
            conn.close()

    def emitted_sql(self):
        return [s for s in self.statements if INTEGER_AS_BOOLEAN.search(s)]

    def test_design_without_season_or_model_type_uses_a_boolean_scope(self):
        design_id = self.seed_design()

        response = self.client.get(f"/designs/{design_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.emitted_sql(), [],
            "an integer literal was used where PostgreSQL requires a boolean",
        )

    def test_design_with_a_season_still_scopes_suggestions_to_it(self):
        conn = db.connect()
        season_id = conn.execute(
            "INSERT INTO seasons(name,year_label,slug,sort_order) VALUES (?,?,?,1)",
            ("Into the Deep", "2024-2025", "into-the-deep"),
        ).lastrowid
        conn.commit()
        conn.close()

        design_id = self.seed_design(season_id=season_id)

        response = self.client.get(f"/designs/{design_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.emitted_sql(), [])
        self.assertTrue(
            any("d2.season_id" in statement for statement in self.statements),
            "the suggestion query stopped scoping to the design's season",
        )


if __name__ == "__main__":
    unittest.main()
