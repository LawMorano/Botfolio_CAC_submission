import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import db


class ModelValidationTests(unittest.TestCase):
    def test_model_size_tiers_are_separate(self):
        import app as application
        self.assertEqual(application.AUTO_VIEW_MODEL_BYTES, 350_000_000)
        self.assertEqual(application.MAX_VIEW_MODEL_BYTES, 500_000_000)
        self.assertEqual(application.MAX_MODEL_BYTES, 2_500_000_000)

    def test_ai_review_excerpt_keeps_two_sentences(self):
        import app as application
        excerpt = application.review_excerpt("First sentence. Second sentence! Third sentence.")
        self.assertEqual(excerpt, "First sentence. Second sentence!")

    def test_rejects_executable_renamed_as_obj(self):
        import app as application
        self.assertFalse(application.valid_model_content(".obj", b"MZ\x00\x00program", 12))

    def test_accepts_structured_obj(self):
        import app as application
        self.assertTrue(application.valid_model_content(".obj", b"v 0 0 0\nf 1 2 3\n", 18))

    def test_accepts_consistent_binary_stl(self):
        import app as application
        payload = bytearray(84 + 50)
        payload[80:84] = (1).to_bytes(4, "little")
        self.assertTrue(application.valid_model_content(".stl", bytes(payload), len(payload)))

    def test_storage_counter_migration_uses_bigint_and_recalculates_usage(self):
        import app as application

        class Cursor:
            def __init__(self, row=None):
                self.row = row

            def fetchone(self):
                return self.row

        class RecordingConnection:
            def __init__(self):
                self.statements = []

            def execute(self, statement, params=()):
                self.statements.append(" ".join(statement.split()))
                return Cursor(None)

        conn = RecordingConnection()
        with patch.object(application.db, "using_postgres", return_value=True):
            application._ensure_bigint_byte_counters(conn)

        ddl = "\n".join(conn.statements)
        self.assertIn("ALTER TABLE users ALTER COLUMN storage_used_bytes TYPE BIGINT", ddl)
        self.assertIn("ALTER TABLE pending_model_uploads ALTER COLUMN declared_size_bytes TYPE BIGINT", ddl)
        self.assertIn("SELECT SUM(storage_bytes) FROM designs", ddl)
        self.assertIn("INSERT INTO schema_migrations(version) VALUES (5)", ddl)


class SecurityIncidentRegisterTests(unittest.TestCase):
    def setUp(self):
        import app as application
        self.application = application
        self.application.app.testing = True
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "test.db")
        self.db_patch.start()
        db.init_db()
        conn = db.connect()
        self.admin_id = conn.execute(
            "INSERT INTO users(username,email,password_hash,is_admin,onboarding_complete) VALUES (?,?,?,1,1)",
            ("incident_admin", "incident-admin@example.com", "hash"),
        ).lastrowid
        self.user_id = conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete) VALUES (?,?,?,1)",
            ("ordinary_user", "ordinary@example.com", "hash"),
        ).lastrowid
        conn.commit()
        conn.close()
        self.client = self.application.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def _login(self, user_id):
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["csrf_token"] = "incident-csrf"

    def _incident(self, **changes):
        data = {
            "incident_number": "INC-2026-001", "discovery_date": "2026-08-14",
            "discovered_by": "Operations", "systems_affected": "Web application",
            "information_affected": "No personal information confirmed",
            "actions_taken": "Contained and investigated", "credentials_rotated": "Database password",
            "vendors_contacted": "Railway", "notifications": "Internal administrator notified",
            "root_cause": "Misconfiguration", "corrective_action": "Configuration corrected",
            "resolution_date": "2026-08-15", "csrf_token": "incident-csrf",
        }
        data.update(changes)
        return data

    def test_only_admin_can_open_incident_register(self):
        self._login(self.user_id)
        self.assertEqual(self.client.get("/admin/incidents").status_code, 403)
        self._login(self.admin_id)
        self.assertEqual(self.client.get("/admin/incidents").status_code, 200)

    def test_admin_can_record_and_update_all_incident_fields(self):
        self._login(self.admin_id)
        response = self.client.post("/admin/incidents", data=self._incident())
        self.assertEqual(response.status_code, 302)
        conn = db.connect()
        incident = conn.execute("SELECT * FROM security_incidents WHERE incident_number='INC-2026-001'").fetchone()
        conn.close()
        self.assertEqual(incident["root_cause"], "Misconfiguration")
        self.assertEqual(incident["created_by"], self.admin_id)
        response = self.client.post(
            f"/admin/incidents/{incident['id']}",
            data=self._incident(actions_taken="Contained, investigated, and documented"),
        )
        self.assertEqual(response.status_code, 302)
        conn = db.connect()
        updated = conn.execute("SELECT actions_taken,resolution_date FROM security_incidents WHERE id=?", (incident["id"],)).fetchone()
        conn.close()
        self.assertIn("documented", updated["actions_taken"])
        self.assertEqual(updated["resolution_date"], "2026-08-15")


class AccountDeletionTests(unittest.TestCase):
    def setUp(self):
        import app as application
        self.application = application
        self.application.app.testing = True
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "test.db")
        self.db_patch.start()
        db.init_db()
        conn = db.connect()
        cursor = conn.execute(
            """INSERT INTO users(username,email,password_hash,onboarding_complete,
                       accepted_terms_version,accepted_privacy_version,accepted_terms_at,
                       age_13_confirmed,minor_permission_confirmed,email_verified_at)
                 VALUES (?,?,?,1,'test','test',datetime('now'),1,1,datetime('now'))""",
            ("delete_me", "delete@example.com", generate_password_hash("correct horse")),
        )
        self.user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        self.client = self.application.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_deletion_anonymizes_account_and_terminates_session(self):
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"
        response = self.client.post(
            "/account/delete",
            data={"password": "correct horse", "confirmation": "DELETE", "csrf_token": "test-csrf"},
        )
        self.assertEqual(response.status_code, 302)
        conn = db.connect()
        user = conn.execute("SELECT * FROM users WHERE id=?", (self.user_id,)).fetchone()
        conn.close()
        self.assertIsNotNone(user["deleted_at"])
        self.assertEqual(user["password_hash"], "")
        self.assertEqual(user["email"], f"deleted-{self.user_id}@invalid.botfolio")
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

    def test_account_and_upload_certification_controls_render(self):
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
        account = self.client.get("/account")
        self.assertIn(b"Delete My Account", account.data)
        submit = self.client.get("/submit")
        self.assertIn(b"permission from its owner and my team", submit.data)
        self.assertIn(b'name="team_id" required', submit.data)
        self.assertIn(b">Individual</option>", submit.data)
        self.assertIn(b'id="publish-design" type="submit" disabled', submit.data)
        self.assertIn(b'id="model-upload-progress"', submit.data)
        self.assertIn(b'Uploading model', submit.data)
        self.assertIn(b'id="upload-page"', submit.data)
        self.assertIn(b'View your design', submit.data)
        self.assertIn(b'Publishing design', submit.data)

    def test_large_model_authorization_uses_multipart_without_account_quota(self):
        conn = db.connect()
        conn.execute(
            "UPDATE users SET storage_limit_bytes=1,storage_used_bytes=999999999 WHERE id=?",
            (self.user_id,),
        )
        conn.commit()
        conn.close()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"

        size = 2_500_000_000
        with patch.object(self.application.settings, "s3_bucket_models", "models"), \
             patch.object(self.application.settings, "s3_bucket_quarantine", "quarantine"), \
             patch.object(self.application.infra_storage, "initiate_multipart_upload", return_value="upload-id"), \
             patch.object(self.application.infra_storage, "presign_upload_part", side_effect=lambda *args: f"https://storage.example/{args[-1]}"):
            response = self.client.post(
                "/api/model-uploads/authorize",
                json={"filename": "large-robot.stl", "size": size},
                headers={"X-CSRF-Token": "test-csrf"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["part_size"], 64 * 1024 * 1024)
        self.assertEqual(len(payload["parts"]), 38)
        self.assertEqual(payload["expires_in"], 6 * 60 * 60)

    def test_completed_multipart_upload_is_marked_ready(self):
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"
        token = "multipart-token"
        import hashlib
        conn = db.connect()
        conn.execute(
            "INSERT INTO pending_model_uploads(user_id,token_hash,original_filename,"
            "object_filename,declared_size_bytes,multipart_upload_id,expires_at) "
            "VALUES (?,?,?,?,?,?,datetime('now','+1 hour'))",
            (self.user_id, hashlib.sha256(token.encode()).hexdigest(), "robot.obj",
             "object.obj", 18, "upload-id"),
        )
        conn.commit()
        conn.close()

        with patch.object(self.application.infra_storage, "complete_multipart_upload"), \
             patch.object(self.application.infra_storage, "size", return_value=18), \
             patch.object(self.application.infra_storage, "read_prefix", return_value=b"v 0 0 0\nf 1 2 3\n"), \
             patch.object(self.application.infra_storage, "promote") as promote:
            response = self.client.post(
                "/api/model-uploads/complete",
                json={"upload_token": token, "parts": [
                    {"part_number": 1, "etag": '"0123456789abcdef0123456789abcdef"'}
                ]},
                headers={"X-CSRF-Token": "test-csrf"},
            )

        self.assertEqual(response.status_code, 200)
        conn = db.connect()
        completed = conn.execute(
            "SELECT upload_completed_at,promoted_at FROM pending_model_uploads WHERE token_hash=?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(completed["upload_completed_at"])
        self.assertIsNotNone(completed["promoted_at"])
        promote.assert_called_once_with("quarantine", "models", "object.obj")

    def test_hidden_overlays_cannot_block_header_links(self):
        stylesheet = (Path(__file__).parents[1] / "static" / "style.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("[hidden] { display: none !important; }", stylesheet)

    def test_submit_requires_team_or_individual_attribution(self):
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"
        response = self.client.post(
            "/submit",
            data={"csrf_token": "test-csrf", "upload_certification": "accepted"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Choose whether this design is uploaded", response.data)

    def test_admin_upload_bypasses_limits_and_is_labeled(self):
        conn = db.connect()
        conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (self.user_id,))
        for _ in range(12):
            conn.execute("INSERT INTO upload_attempts(user_id) VALUES (?)", (self.user_id,))
        conn.commit()
        conn.close()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"

        data = {
            "csrf_token": "test-csrf",
            "team_id": "individual",
            "title": "Administrator Design",
            "description": "Uploaded for an administrative test.",
            "prototype_version": "1",
            "competition_tested": "0",
            "length_in": "1",
            "width_in": "1",
            "height_in": "1",
            "preview_data_url": "data:image/png;base64,test",
            "upload_certification": "accepted",
        }
        with patch.object(self.application, "save_preview_data_url", return_value="admin-preview.jpg"), \
             patch.object(self.application.infra_storage, "size", return_value=1):
            response = self.client.post("/submit", data=data, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Uploaded by admin", response.data)
        conn = db.connect()
        design = conn.execute(
            "SELECT uploaded_by_admin,team_id FROM designs WHERE title='Administrator Design'"
        ).fetchone()
        attempts = conn.execute(
            "SELECT COUNT(*) n FROM upload_attempts WHERE user_id=?", (self.user_id,)
        ).fetchone()["n"]
        conn.close()
        self.assertEqual(design["uploaded_by_admin"], 1)
        self.assertIsNone(design["team_id"])
        self.assertEqual(attempts, 12)

    def test_admin_can_attribute_upload_to_named_team(self):
        conn = db.connect()
        conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (self.user_id,))
        conn.commit()
        conn.close()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"

        form = self.client.get("/submit")
        self.assertIn(b'name="admin_attribution"', form.data)
        self.assertIn(b'name="admin_team_name"', form.data)
        data = {
            "csrf_token": "test-csrf", "admin_attribution": "team",
            "admin_team_number": "8675", "admin_team_name": "Circuit Breakers",
            "title": "Admin Team Design", "description": "Attributed by an admin.",
            "prototype_version": "1", "competition_tested": "0",
            "length_in": "1", "width_in": "1", "height_in": "1",
            "preview_data_url": "data:image/png;base64,test",
            "upload_certification": "accepted",
        }
        with patch.object(self.application, "save_preview_data_url", return_value="team-preview.jpg"), \
             patch.object(self.application.infra_storage, "size", return_value=1):
            response = self.client.post("/submit", data=data)
        self.assertEqual(response.status_code, 302)
        conn = db.connect()
        team = conn.execute("SELECT id,name,profile_status,founding_rank FROM teams WHERE number=8675").fetchone()
        design = conn.execute("SELECT team_id,team_attribution_accepted FROM designs WHERE title='Admin Team Design'").fetchone()
        conn.close()
        self.assertEqual(team["name"], "Circuit Breakers")
        self.assertEqual(team["profile_status"], "reference")
        self.assertIsNone(team["founding_rank"])
        self.assertEqual(design["team_id"], team["id"])
        self.assertEqual(design["team_attribution_accepted"], 0)

        reference_page = self.client.get("/teams/8675")
        self.assertIn(b"not a team-managed profile", reference_page.data)
        self.assertIn(b"Admin Team Design", reference_page.data)

        rejected_claim = self.client.post(
            "/teams",
            data={"csrf_token": "test-csrf", "number": "8675", "name": "Circuit Breakers"},
        )
        self.assertEqual(rejected_claim.status_code, 302)
        conn = db.connect()
        self.assertEqual(
            conn.execute("SELECT profile_status FROM teams WHERE number=8675").fetchone()["profile_status"],
            "reference",
        )
        conn.close()

        claimed = self.client.post(
            "/teams",
            data={"csrf_token": "test-csrf", "number": "8675", "name": "Circuit Breakers",
                  "accept_attributions": "accepted"},
        )
        self.assertEqual(claimed.status_code, 302)
        conn = db.connect()
        team = conn.execute("SELECT profile_status,owner_id,founding_rank FROM teams WHERE number=8675").fetchone()
        design = conn.execute("SELECT team_attribution_accepted FROM designs WHERE title='Admin Team Design'").fetchone()
        membership = conn.execute(
            "SELECT role FROM memberships m JOIN teams t ON t.id=m.team_id WHERE t.number=8675 AND m.user_id=?",
            (self.user_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(team["profile_status"], "claimed")
        self.assertEqual(team["owner_id"], self.user_id)
        self.assertIsNotNone(team["founding_rank"])
        self.assertEqual(design["team_attribution_accepted"], 1)
        self.assertEqual(membership["role"], "owner")

    def test_gallery_uses_expandable_filter_menu(self):
        gallery = self.client.get("/gallery")
        self.assertIn(b'class="filter-menu"', gallery.data)
        self.assertIn(b'class="filter-section"', gallery.data)
        self.assertNotIn(b'<select name="season">', gallery.data)

    def test_account_email_can_be_changed_and_requires_reverification(self):
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"
        with patch.object(self.application.email_service, "send_email", return_value=True) as send_email:
            response = self.client.post(
                "/account/email",
                data={"email": "New.Address@Example.com", "password": "correct horse", "csrf_token": "test-csrf"},
            )
        self.assertEqual(response.status_code, 302)
        conn = db.connect()
        user = conn.execute("SELECT email,email_verified_at FROM users WHERE id=?", (self.user_id,)).fetchone()
        token_count = conn.execute(
            "SELECT count(*) total FROM email_verification_tokens WHERE user_id=? AND used_at IS NULL",
            (self.user_id,),
        ).fetchone()["total"]
        conn.close()
        self.assertEqual(user["email"], "new.address@example.com")
        self.assertIsNone(user["email_verified_at"])
        self.assertEqual(token_count, 1)
        self.assertEqual(send_email.call_args.kwargs["to_email"], "new.address@example.com")

    def test_admin_can_search_users_by_username(self):
        conn = db.connect()
        conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (self.user_id,))
        conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete) VALUES (?,?,?,1)",
            ("GearBuilder", "gear@example.com", generate_password_hash("password123")),
        )
        conn.commit()
        conn.close()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
        response = self.client.get("/moderation/comments?user=gear")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"GearBuilder", response.data)
        self.assertIn(b"/u/GearBuilder", response.data)
        self.assertNotIn(b"gear@example.com", response.data)

    def test_admin_can_list_and_restore_hidden_designs_from_moderation(self):
        conn = db.connect()
        conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (self.user_id,))
        hidden_id = conn.execute(
            """INSERT INTO designs(user_id,title,description,image_filename,is_hidden)
                 VALUES (?,?,?,?,1)""",
            (self.user_id, "Hidden Flywheel", "Needs another review", "placeholder.png"),
        ).lastrowid
        conn.execute(
            """INSERT INTO designs(user_id,title,description,image_filename,is_hidden)
                 VALUES (?,?,?,?,0)""",
            (self.user_id, "Visible Flywheel", "Already public", "placeholder.png"),
        )
        conn.execute(
            """INSERT INTO moderation_actions(admin_id,target_type,target_id,action,reason)
                 VALUES (?,?,?,?,?)""",
            (self.user_id, "design", str(hidden_id), "hide", "Incorrect attribution"),
        )
        conn.commit()
        conn.close()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"

        page = self.client.get("/moderation/comments")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Hidden designs", page.data)
        self.assertIn(b"Hidden Flywheel", page.data)
        self.assertIn(b"Incorrect attribution", page.data)
        self.assertNotIn(b"Visible Flywheel", page.data)

        response = self.client.post(
            f"/designs/{hidden_id}/moderate",
            data={
                "action": "restore",
                "reason": "Attribution corrected",
                "return_to": "moderation",
                "csrf_token": "test-csrf",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/moderation/comments"))
        conn = db.connect()
        design = conn.execute("SELECT is_hidden FROM designs WHERE id=?", (hidden_id,)).fetchone()
        action = conn.execute(
            "SELECT action,reason FROM moderation_actions WHERE target_type='design' AND target_id=? ORDER BY id DESC LIMIT 1",
            (str(hidden_id),),
        ).fetchone()
        conn.close()
        self.assertEqual(design["is_hidden"], 0)
        self.assertEqual((action["action"], action["reason"]), ("restore", "Attribution corrected"))

    def test_admin_can_see_and_delete_another_users_comment(self):
        conn = db.connect()
        conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (self.user_id,))
        author_id = conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete) VALUES (?,?,?,1)",
            ("CommentAuthor", "comment@example.com", generate_password_hash("password123")),
        ).lastrowid
        design_id = conn.execute(
            "INSERT INTO designs(user_id,title,description,image_filename) VALUES (?,?,?,?)",
            (author_id, "Comment Test Design", "Testing moderation", "placeholder.png"),
        ).lastrowid
        comment_id = conn.execute(
            "INSERT INTO comments(design_id,user_id,body) VALUES (?,?,?)",
            (design_id, author_id, "An administrator should be able to remove this."),
        ).lastrowid
        conn.commit()
        conn.close()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"

        page = self.client.get(f"/designs/{design_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'/comments/{comment_id}/delete'.encode(), page.data)

        response = self.client.post(
            f"/comments/{comment_id}/delete", data={"csrf_token": "test-csrf"}
        )
        self.assertEqual(response.status_code, 302)
        conn = db.connect()
        comment = conn.execute("SELECT status,body FROM comments WHERE id=?", (comment_id,)).fetchone()
        conn.close()
        self.assertEqual(comment["status"], "deleted")
        self.assertEqual(comment["body"], "[deleted]")

    def test_global_search_returns_categorized_site_results(self):
        conn = db.connect()
        conn.execute("UPDATE users SET tagline='Nova builder' WHERE id=?", (self.user_id,))
        design_id = conn.execute(
            "INSERT INTO designs(user_id,title,description,image_filename,competition_tested) VALUES (?,?,?,?,1)",
            (self.user_id, "Nova Intake", "A compact roller intake", "placeholder.png"),
        ).lastrowid
        team_id = conn.execute(
            "INSERT INTO teams(number,name,region,owner_id,invite_code) VALUES (?,?,?,?,?)",
            (4242, "Nova Robotics", "North Carolina", self.user_id, "search-test"),
        ).lastrowid
        conn.execute("UPDATE designs SET team_id=? WHERE id=?", (team_id, design_id))
        tag_id = conn.execute(
            "INSERT INTO tags(name,created_by) VALUES (?,?)", ("nova mechanism", self.user_id)
        ).lastrowid
        conn.execute(
            "INSERT INTO design_tags(design_id,tag_id,added_by) VALUES (?,?,?)",
            (design_id, tag_id, self.user_id),
        )
        # Award it Design of the Week so the home hero carousel (awarded designs
        # only) has something to show.
        conn.execute(
            "INSERT INTO design_of_week_awards(design_id,selected_by,current_week) VALUES (?,?,?)",
            (design_id, self.user_id, self.application.design_week_start()),
        )
        conn.commit()
        conn.close()

        response = self.client.get("/api/search?q=nova")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        groups = {group["key"]: group["items"] for group in payload["groups"]}
        self.assertEqual(groups["designs"][0]["title"], "Nova Intake")
        self.assertEqual(groups["teams"][0]["title"], "Team 4242 - Nova Robotics")
        self.assertEqual(groups["tags"][0]["title"], "Nova Mechanism")
        self.assertTrue(groups["people"])
        self.assertGreaterEqual(payload["total"], 4)

        page = self.client.get("/search?q=nova")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Results for', page.data)
        self.assertIn(b'Nova Intake', page.data)
        self.assertIn(b'design-card', page.data)

        home = self.client.get("/")
        gallery = self.client.get("/gallery")
        team_page = self.client.get("/teams/4242")
        directory = self.client.get("/teams")
        for rendered in (home, gallery, team_page, directory):
            self.assertEqual(rendered.status_code, 200)
        self.assertNotIn(b'+ Upload', home.data)
        topbar_nav = home.data.split(b'<nav class="topbar__nav">', 1)[1].split(b'</nav>', 1)[0]
        self.assertNotIn(b'Contact', topbar_nav)
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
        self.assertIn(b'+ Upload', self.client.get("/").data)
        self.assertIn(b'Build better robots by seeing how others built theirs.', home.data)
        self.assertIn(b'data-dotw-carousel', home.data)
        # The "how it works" walkthrough now lives on the dedicated Help page.
        self.assertNotIn(b'How it works', home.data)
        help_page = self.client.get("/help")
        self.assertEqual(help_page.status_code, 200)
        self.assertIn(b'How Botfolio works', help_page.data)
        self.assertIn(b'Upload your design', help_page.data)
        self.assertIn(b'card__tested', gallery.data)
        self.assertLess(team_page.data.index(b'Designs by season'), team_page.data.index(b'Members'))
        self.assertIn(b'team-directory-card', directory.data)

    def test_timed_suspension_and_access_changes_send_emails(self):
        conn = db.connect()
        conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (self.user_id,))
        target_id = conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete) VALUES (?,?,?,1)",
            ("TimedUser", "timed@example.com", generate_password_hash("password123")),
        ).lastrowid
        conn.commit()
        conn.close()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"

        with patch.object(self.application.email_service, "send_email", return_value=True) as send_email:
            response = self.client.post(
                "/u/TimedUser/moderate",
                data={"action": "suspend", "reason": "Repeated spam", "suspension_duration": "3_days", "csrf_token": "test-csrf"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(send_email.call_args.kwargs["event_type"], "moderation_suspension")
            self.assertIn("3 days", send_email.call_args.kwargs["message"])

            response = self.client.post(
                "/u/TimedUser/moderate",
                data={"action": "restore", "reason": "Appeal approved", "csrf_token": "test-csrf"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(send_email.call_args.kwargs["event_type"], "moderation_access_restored")

            response = self.client.post(
                "/u/TimedUser/moderate",
                data={"action": "ban", "reason": "Severe abuse", "csrf_token": "test-csrf"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(send_email.call_args.kwargs["event_type"], "moderation_ban")

        conn = db.connect()
        target = conn.execute("SELECT * FROM users WHERE id=?", (target_id,)).fetchone()
        actions = conn.execute(
            "SELECT action,reason FROM moderation_actions WHERE target_id=? ORDER BY id",
            (str(target_id),),
        ).fetchall()
        conn.close()
        self.assertIsNotNone(target["banned_at"])
        self.assertIsNone(target["suspended_until"])
        self.assertIn("Suspension duration: 3 days", actions[0]["reason"])

    def test_expired_suspension_restores_access_and_emails_user(self):
        conn = db.connect()
        target_id = conn.execute(
            """INSERT INTO users(username,email,password_hash,onboarding_complete,suspended_at,suspended_until)
                 VALUES (?,?,?,1,datetime('now','-2 hours'),datetime('now','-1 hour'))""",
            ("ExpiredUser", "expired@example.com", generate_password_hash("password123")),
        ).lastrowid
        conn.commit()
        conn.close()
        with patch.object(self.application.email_service, "send_email", return_value=True) as send_email:
            response = self.client.post(
                "/login",
                data={"username": "ExpiredUser", "password": "password123", "csrf_token": self._csrf_token()},
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(send_email.call_args.kwargs["event_type"], "moderation_access_restored")
        conn = db.connect()
        target = conn.execute("SELECT suspended_at,suspended_until FROM users WHERE id=?", (target_id,)).fetchone()
        conn.close()
        self.assertIsNone(target["suspended_at"])
        self.assertIsNone(target["suspended_until"])

    def _csrf_token(self):
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-csrf"
        return "test-csrf"

    def test_report_supports_four_state_workflow(self):
        conn = db.connect()
        conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (self.user_id,))
        cursor = conn.execute(
            """INSERT INTO content_reports(content_type,content_url,reason,description,reporter_email)
                 VALUES ('design','https://example.test/design','unsafe','Unsafe test report','reporter@example.test')"""
        )
        report_id = cursor.lastrowid
        conn.commit()
        conn.close()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"
        response = self.client.post(
            f"/moderation/content-reports/{report_id}",
            data={"action": "set_status", "workflow_status": "under_review", "note": "Assigned", "csrf_token": "test-csrf"},
        )
        self.assertEqual(response.status_code, 302)
        conn = db.connect()
        report = conn.execute("SELECT * FROM content_reports WHERE id=?", (report_id,)).fetchone()
        conn.close()
        self.assertEqual(report["workflow_status"], "under_review")
        self.assertEqual(report["assigned_admin_id"], self.user_id)

    def test_anonymous_intimate_report_is_p1_and_admin_can_hide_immediately(self):
        conn = db.connect()
        design_id = conn.execute(
            "INSERT INTO designs(user_id,title,image_filename) VALUES (?,?,?)",
            (self.user_id, "Sensitive report target", "test-image.jpg"),
        ).lastrowid
        conn.commit()
        conn.close()

        with patch.object(self.application.email_service, "send_email", return_value=True) as send_email:
            response = self.client.post(
                "/report",
                data={
                    "content_type": "design",
                    "content_id": str(design_id),
                    "content_url": f"https://example.test/designs/{design_id}",
                    "reason": "intimate",
                    "description": "Possible nonconsensual intimate imagery.",
                    "email": "reporter@example.test",
                    "csrf_token": self._csrf_token(),
                },
            )
        self.assertEqual(response.status_code, 302)
        conn = db.connect()
        report = conn.execute(
            "SELECT * FROM content_reports ORDER BY id DESC LIMIT 1"
        ).fetchone()
        design = conn.execute("SELECT is_hidden FROM designs WHERE id=?", (design_id,)).fetchone()
        conn.close()
        self.assertIsNone(report["reporter_id"])
        self.assertEqual(report["priority"], 3)
        self.assertEqual(report["urgent"], 1)
        self.assertIsNotNone(report["created_at"])
        self.assertIsNone(report["action_taken_at"])
        self.assertEqual(design["is_hidden"], 0)
        self.assertTrue(any(
            call.kwargs.get("to_email") == self.application.SECURITY_EMAIL
            and "URGENT P1" in call.kwargs.get("subject", "")
            for call in send_email.call_args_list
        ))

        conn = db.connect()
        conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (self.user_id,))
        conn.commit()
        conn.close()
        with self.client.session_transaction() as browser_session:
            browser_session["user_id"] = self.user_id
            browser_session["csrf_token"] = "test-csrf"
        hidden = self.client.post(
            f"/moderation/content-reports/{report['id']}",
            data={
                "action": "hide_content",
                "note": "Hidden immediately for safety review.",
                "csrf_token": "test-csrf",
            },
        )
        self.assertEqual(hidden.status_code, 302)
        conn = db.connect()
        report = conn.execute("SELECT * FROM content_reports WHERE id=?", (report["id"],)).fetchone()
        design = conn.execute("SELECT is_hidden FROM designs WHERE id=?", (design_id,)).fetchone()
        conn.close()
        self.assertEqual(design["is_hidden"], 1)
        self.assertEqual(report["workflow_status"], "action_taken")
        self.assertIsNotNone(report["action_taken_at"])


class TeamMembershipWorkflowTests(unittest.TestCase):
    def setUp(self):
        import app as application
        self.application = application
        self.application.app.testing = True
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "test.db")
        self.db_patch.start()
        db.init_db()
        conn = db.connect()
        self.owner_id = self._create_user(conn, "TeamOwner", "owner@example.com")
        self.member_id = self._create_user(conn, "FutureMember", "member@example.com")
        self.outsider_id = self._create_user(conn, "Outsider", "outsider@example.com")
        self.team_id = conn.execute(
            "INSERT INTO teams(number,name,owner_id,invite_code) VALUES (?,?,?,?)",
            (9999, "Test Robotics", self.owner_id, "legacy-code"),
        ).lastrowid
        conn.execute(
            "INSERT INTO memberships(user_id,team_id,role) VALUES (?,?,'owner')",
            (self.owner_id, self.team_id),
        )
        conn.commit()
        conn.close()
        self.client = self.application.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    @staticmethod
    def _create_user(conn, username, email):
        return conn.execute(
            """INSERT INTO users(username,email,password_hash,onboarding_complete,
                       accepted_terms_version,email_verified_at)
                 VALUES (?,?,?,1,'test',datetime('now'))""",
            (username, email, generate_password_hash("password123")),
        ).lastrowid

    def _login(self, user_id):
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["csrf_token"] = "test-csrf"

    def test_owner_invites_user_and_user_accepts_from_notifications(self):
        self._login(self.owner_id)
        with patch.object(self.application.email_service, "send_email", return_value=True) as send_email:
            response = self.client.post(
                "/teams/9999/members/invite",
                data={"username": "futuremember", "csrf_token": "test-csrf"},
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(send_email.call_args.kwargs["to_email"], "member@example.com")
        self.assertEqual(send_email.call_args.kwargs["event_type"], "team_invitation")
        conn = db.connect()
        invitation = conn.execute(
            "SELECT * FROM team_membership_requests WHERE team_id=? AND user_id=?",
            (self.team_id, self.member_id),
        ).fetchone()
        conn.close()
        self.assertEqual((invitation["kind"], invitation["status"]), ("invitation", "pending"))

        self._login(self.member_id)
        page = self.client.get("/notifications")
        self.assertIn(b"invited you to join", page.data)
        self.assertIn(b"Test Robotics", page.data)
        self.assertIn(b"Accept", page.data)
        response = self.client.post(
            f"/team-membership-requests/{invitation['id']}/respond",
            data={"action": "accept", "csrf_token": "test-csrf"},
        )
        self.assertEqual(response.status_code, 302)
        conn = db.connect()
        membership = conn.execute(
            "SELECT role FROM memberships WHERE team_id=? AND user_id=?",
            (self.team_id, self.member_id),
        ).fetchone()
        status = conn.execute(
            "SELECT status FROM team_membership_requests WHERE id=?", (invitation["id"],)
        ).fetchone()["status"]
        conn.close()
        self.assertEqual(membership["role"], "member")
        self.assertEqual(status, "accepted")

    def test_user_requests_to_join_and_only_owner_can_approve(self):
        self._login(self.member_id)
        with patch.object(self.application.email_service, "send_email", return_value=True) as send_email:
            response = self.client.post(
                "/teams/9999/join-request", data={"csrf_token": "test-csrf"}
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(send_email.call_args.kwargs["to_email"], "owner@example.com")
        self.assertEqual(send_email.call_args.kwargs["event_type"], "team_join_request")
        conn = db.connect()
        join_request = conn.execute(
            "SELECT * FROM team_membership_requests WHERE team_id=? AND user_id=?",
            (self.team_id, self.member_id),
        ).fetchone()
        conn.close()

        self._login(self.outsider_id)
        forbidden = self.client.post(
            f"/team-membership-requests/{join_request['id']}/respond",
            data={"action": "accept", "csrf_token": "test-csrf"},
        )
        self.assertEqual(forbidden.status_code, 403)

        self._login(self.owner_id)
        page = self.client.get("/notifications")
        self.assertIn(b"requested to join", page.data)
        with patch.object(self.application.email_service, "send_email", return_value=True) as send_email:
            accepted = self.client.post(
                f"/team-membership-requests/{join_request['id']}/respond",
                data={"action": "accept", "csrf_token": "test-csrf"},
            )
        self.assertEqual(accepted.status_code, 302)
        self.assertEqual(send_email.call_args.kwargs["event_type"], "team_request_accepted")

    def test_owner_can_remove_member_but_non_owner_cannot(self):
        conn = db.connect()
        conn.execute(
            "INSERT INTO memberships(user_id,team_id) VALUES (?,?)",
            (self.member_id, self.team_id),
        )
        conn.commit()
        conn.close()
        self._login(self.outsider_id)
        forbidden = self.client.post(
            f"/teams/9999/members/{self.member_id}/remove",
            data={"csrf_token": "test-csrf"},
        )
        self.assertEqual(forbidden.status_code, 403)

        self._login(self.owner_id)
        with patch.object(self.application.email_service, "send_email", return_value=True) as send_email:
            removed = self.client.post(
                f"/teams/9999/members/{self.member_id}/remove",
                data={"csrf_token": "test-csrf"},
            )
        self.assertEqual(removed.status_code, 302)
        self.assertEqual(send_email.call_args.kwargs["event_type"], "team_member_removed")
        conn = db.connect()
        membership = conn.execute(
            "SELECT 1 FROM memberships WHERE team_id=? AND user_id=?",
            (self.team_id, self.member_id),
        ).fetchone()
        conn.close()
        self.assertIsNone(membership)

    def test_owner_can_deny_join_request_without_adding_member(self):
        conn = db.connect()
        request_id = conn.execute(
            """INSERT INTO team_membership_requests
               (team_id,user_id,initiated_by_id,kind) VALUES (?,?,?,'request')""",
            (self.team_id, self.member_id, self.member_id),
        ).lastrowid
        conn.commit()
        conn.close()
        self._login(self.owner_id)
        with patch.object(self.application.email_service, "send_email", return_value=True) as send_email:
            response = self.client.post(
                f"/team-membership-requests/{request_id}/respond",
                data={"action": "deny", "csrf_token": "test-csrf"},
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(send_email.call_args.kwargs["event_type"], "team_request_denied")
        conn = db.connect()
        status = conn.execute(
            "SELECT status FROM team_membership_requests WHERE id=?", (request_id,)
        ).fetchone()["status"]
        membership = conn.execute(
            "SELECT 1 FROM memberships WHERE team_id=? AND user_id=?",
            (self.team_id, self.member_id),
        ).fetchone()
        conn.close()
        self.assertEqual(status, "denied")
        self.assertIsNone(membership)

    def test_admin_can_remove_member_but_not_team_owner(self):
        conn = db.connect()
        conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (self.outsider_id,))
        conn.execute(
            "INSERT INTO memberships(user_id,team_id) VALUES (?,?)",
            (self.member_id, self.team_id),
        )
        conn.commit()
        conn.close()
        self._login(self.outsider_id)

        page = self.client.get("/teams/9999")
        self.assertIn(f"/teams/9999/members/{self.member_id}/remove".encode(), page.data)
        self.assertNotIn(f"/teams/9999/members/{self.owner_id}/remove".encode(), page.data)
        with patch.object(self.application.email_service, "send_email", return_value=True):
            removed = self.client.post(
                f"/teams/9999/members/{self.member_id}/remove",
                data={"csrf_token": "test-csrf"},
            )
        self.assertEqual(removed.status_code, 302)
        owner_attempt = self.client.post(
            f"/teams/9999/members/{self.owner_id}/remove",
            data={"csrf_token": "test-csrf"},
        )
        self.assertEqual(owner_attempt.status_code, 400)


if __name__ == "__main__":
    unittest.main()
