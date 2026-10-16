import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import db


class ViewCountingTests(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        application.app.testing = True
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "test.db")
        self.db_patch.start()
        db.init_db()
        application.ratelimit._buckets.clear()
        self.client = application.app.test_client()

        conn = db.connect()
        self.owner_id = conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete,email_verified_at) "
            "VALUES (?,?,?,1,datetime('now'))",
            ("owner", "owner@example.test", generate_password_hash("password")),
        ).lastrowid
        self.design_id = conn.execute(
            "INSERT INTO designs(user_id,title,description,image_filename,upload_status) "
            "VALUES (?,?,'A design','preview.jpg','approved')",
            (self.owner_id, "Clean counter"),
        ).lastrowid
        # Prove that the old crawler-inflated table is not reused by the new
        # public counter.
        conn.execute(
            "INSERT INTO design_visits(design_id,visitor_key) VALUES (?,'legacy:crawler')",
            (self.design_id,),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    @property
    def detail_url(self):
        return f"/designs/{self.design_id}"

    @property
    def view_url(self):
        return f"{self.detail_url}/view"

    def count(self):
        conn = db.connect()
        try:
            return conn.execute(
                "SELECT COUNT(*) AS n FROM design_view_events WHERE design_id=?",
                (self.design_id,),
            ).fetchone()["n"]
        finally:
            conn.close()

    def csrf(self, client=None):
        client = client or self.client
        client.get(self.detail_url)
        with client.session_transaction() as session:
            return session["csrf_token"]

    def record(self, client=None, user_agent="Mozilla/5.0 Test Browser"):
        client = client or self.client
        token = self.csrf(client)
        return client.post(
            self.view_url,
            headers={"X-CSRF-Token": token, "User-Agent": user_agent},
        )

    def test_get_and_head_never_count_as_views(self):
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)
        self.assertEqual(self.client.head(self.detail_url).status_code, 200)
        self.assertEqual(self.count(), 0)

    def test_old_visit_rows_do_not_appear_in_the_clean_counter(self):
        page = self.client.get(self.detail_url).get_data(as_text=True)
        self.assertIn("0</span> views since 10/12/26", page)
        self.assertNotIn("1</span> views since 10/12/26", page)

        gallery = self.client.get("/gallery").get_data(as_text=True)
        self.assertIn('<span class="sr-only">Views:</span>0', gallery)
        self.assertNotIn("views since 10/12/26", gallery)

    def test_runtime_migration_adds_the_clean_counter_to_existing_databases(self):
        conn = db.connect()
        conn.execute("DROP TABLE design_view_state")
        conn.execute("DROP TABLE design_view_events")
        self.application._ensure_runtime_schema(conn)
        conn.commit()
        tables = {
            row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        conn.close()
        self.assertIn("design_view_events", tables)
        self.assertIn("design_view_state", tables)

    def test_same_person_counts_again_only_after_thirty_minutes(self):
        first = self.record()
        second = self.record()
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.get_json()["counted"])
        self.assertFalse(second.get_json()["counted"])
        self.assertEqual(self.count(), 1)

        conn = db.connect()
        conn.execute(
            "UPDATE design_view_state SET last_viewed_at=datetime('now','-30 minutes') "
            "WHERE design_id=?",
            (self.design_id,),
        )
        conn.commit()
        conn.close()

        third = self.record()
        self.assertTrue(third.get_json()["counted"])
        self.assertEqual(third.get_json()["view_count"], 2)
        self.assertEqual(self.count(), 2)

    def test_different_browser_sessions_each_count(self):
        other = self.application.app.test_client()
        self.assertTrue(self.record().get_json()["counted"])
        self.assertTrue(self.record(other).get_json()["counted"])
        self.assertEqual(self.count(), 2)

    def test_known_crawler_does_not_count(self):
        response = self.record(user_agent="Googlebot/2.1")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["counted"])
        self.assertEqual(self.count(), 0)

    def test_view_events_survive_retention_maintenance(self):
        import maintenance

        conn = db.connect()
        conn.execute(
            "INSERT INTO design_view_events(design_id,viewed_at) "
            "VALUES (?,datetime('now','-200 days'))",
            (self.design_id,),
        )
        conn.commit()
        conn.close()

        maintenance.run_retention()
        self.assertEqual(self.count(), 1)


if __name__ == "__main__":
    unittest.main()
