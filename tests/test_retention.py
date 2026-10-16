import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db


class RetentionTests(unittest.TestCase):
    def setUp(self):
        import app as application
        import maintenance

        self.application = application
        self.application.app.testing = True
        self.maintenance = maintenance
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "test.db")
        self.db_patch.start()
        db.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_retention_periods_and_active_holds_are_enforced(self):
        conn = db.connect()
        user_id = conn.execute(
            """INSERT INTO users(
                   username,email,password_hash,deleted_at,
                   age_13_confirmed,minor_permission_confirmed,
                   accepted_terms_version,accepted_terms_at,
                   accepted_privacy_version,accepted_privacy_at)
                 VALUES ('closed','closed@example.test','',datetime('now','-6 years'),
                         1,1,'terms-v1',datetime('now','-6 years'),
                         'privacy-v1',datetime('now','-6 years'))"""
        ).lastrowid
        expired_event = conn.execute(
            "INSERT INTO security_events(event_type,occurred_at) VALUES ('login_failed',datetime('now','-91 days'))"
        ).lastrowid
        held_event = conn.execute(
            "INSERT INTO security_events(event_type,occurred_at) VALUES ('security_review',datetime('now','-91 days'))"
        ).lastrowid
        conn.execute(
            "INSERT INTO retention_holds(target_type,target_id,reason) VALUES ('security_event',?,'Active investigation')",
            (str(held_event),),
        )
        ordinary_report = conn.execute(
            """INSERT INTO content_reports(content_type,content_url,reason,description,
                       reporter_email,workflow_status,resolved_at)
                 VALUES ('design','https://example.test/1','spam','ordinary report',
                         'reporter@example.test','closed',datetime('now','-2 years','-1 day'))"""
        ).lastrowid
        security_report = conn.execute(
            """INSERT INTO content_reports(content_type,content_url,reason,description,
                       reporter_email,workflow_status,resolved_at,priority,urgent)
                 VALUES ('design','https://example.test/2','malware','security report',
                         'reporter@example.test','closed',datetime('now','-3 years'),3,1)"""
        ).lastrowid
        conn.commit()
        conn.close()

        self.maintenance.run_retention()

        conn = db.connect()
        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        event_ids = {row["id"] for row in conn.execute("SELECT id FROM security_events")}
        report_ids = {row["id"] for row in conn.execute("SELECT id FROM content_reports")}
        conn.close()
        self.assertEqual(user["age_13_confirmed"], 0)
        self.assertEqual(user["minor_permission_confirmed"], 0)
        self.assertIsNone(user["accepted_terms_version"])
        self.assertIsNone(user["accepted_terms_at"])
        self.assertIsNone(user["accepted_privacy_version"])
        self.assertIsNone(user["accepted_privacy_at"])
        self.assertNotIn(expired_event, event_ids)
        self.assertIn(held_event, event_ids)
        self.assertNotIn(ordinary_report, report_ids)
        self.assertIn(security_report, report_ids)

    def test_account_hold_preserves_consent_evidence(self):
        conn = db.connect()
        user_id = conn.execute(
            """INSERT INTO users(username,email,password_hash,deleted_at,
                       age_13_confirmed,minor_permission_confirmed,
                       accepted_terms_version,accepted_terms_at,
                       accepted_privacy_version,accepted_privacy_at)
                 VALUES ('held','held@example.test','',datetime('now','-8 years'),
                         1,1,'terms-v1',datetime('now','-8 years'),
                         'privacy-v1',datetime('now','-8 years'))"""
        ).lastrowid
        conn.execute(
            "INSERT INTO retention_holds(target_type,target_id,reason) VALUES ('user',?,'Legal hold')",
            (str(user_id),),
        )
        conn.commit()
        conn.close()

        self.maintenance.run_retention()

        conn = db.connect()
        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        conn.close()
        self.assertEqual(user["age_13_confirmed"], 1)
        self.assertEqual(user["minor_permission_confirmed"], 1)
        self.assertEqual(user["accepted_terms_version"], "terms-v1")
        self.assertEqual(user["accepted_privacy_version"], "privacy-v1")

    def test_maintenance_purges_soft_deleted_content(self):
        conn = db.connect()
        user_id = conn.execute(
            "INSERT INTO users(username,email,password_hash) VALUES ('purged','purged@example.test','')"
        ).lastrowid
        design_id = conn.execute(
            "INSERT INTO designs(user_id,title,description,image_filename,is_hidden) VALUES (?,?,?,?,1)",
            (user_id, "Hidden", "Hidden design", "hidden.png"),
        ).lastrowid
        comment_id = conn.execute(
            "INSERT INTO comments(design_id,user_id,body,status) VALUES (?,?,?,'deleted')",
            (design_id, user_id, "[deleted]"),
        ).lastrowid
        conn.commit()
        conn.close()

        with patch.object(self.maintenance.storage, "delete"):
            self.maintenance.run_retention()

        conn = db.connect()
        self.assertIsNone(conn.execute("SELECT 1 FROM comments WHERE id=?", (comment_id,)).fetchone())
        self.assertIsNone(conn.execute("SELECT 1 FROM designs WHERE id=?", (design_id,)).fetchone())
        conn.close()

    def test_unsaved_ai_chats_expire_after_three_days_but_saved_chats_remain(self):
        conn = db.connect()
        user_id = conn.execute(
            "INSERT INTO users(username,email,password_hash) VALUES ('ai-user','ai@example.test','')"
        ).lastrowid
        design_id = conn.execute(
            "INSERT INTO designs(user_id,title,description,image_filename) VALUES (?, 'Robot', 'Test', 'robot.jpg')",
            (user_id,),
        ).lastrowid
        expired_id = conn.execute(
            """INSERT INTO ai_feedback(design_id,requester_id,summary,created_at)
                 VALUES (?,?,'expired',datetime('now','-3 days','-1 minute'))""",
            (design_id, user_id),
        ).lastrowid
        recent_id = conn.execute(
            """INSERT INTO ai_feedback(design_id,requester_id,summary,created_at)
                 VALUES (?,?,'recent',datetime('now','-2 days'))""",
            (design_id, user_id),
        ).lastrowid
        saved_id = conn.execute(
            """INSERT INTO ai_feedback(design_id,requester_id,summary,saved_at,created_at)
                 VALUES (?,?,'saved',datetime('now'),datetime('now','-30 days'))""",
            (design_id, user_id),
        ).lastrowid
        conn.commit()
        conn.close()

        self.maintenance.run_retention()

        conn = db.connect()
        remaining = {row["id"] for row in conn.execute("SELECT id FROM ai_feedback")}
        conn.close()
        self.assertNotIn(expired_id, remaining)
        self.assertIn(recent_id, remaining)
        self.assertIn(saved_id, remaining)


if __name__ == "__main__":
    unittest.main()
