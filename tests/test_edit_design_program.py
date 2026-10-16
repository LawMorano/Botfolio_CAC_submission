import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import db


class EditDesignProgramTests(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        application.app.testing = True
        # /designs/<id>/edit is rate limited per user, and each test
        # starts on a fresh database where the owner is again user 1.
        application.ratelimit._buckets.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            db, "DB_PATH", Path(self.temp.name) / "edit-program.db"
        )
        self.db_patch.start()
        db.init_db()

        conn = db.connect()
        self.user_id = conn.execute(
            """INSERT INTO users(username,email,password_hash,onboarding_complete,
                       email_verified_at,acknowledged_legal_version)
                 VALUES (?,?,?,1,datetime('now'),?)""",
            (
                "program_editor",
                "program-editor@example.com",
                generate_password_hash("correct horse", method="pbkdf2:sha256:1"),
                application.LEGAL_NOTICE_VERSION,
            ),
        ).lastrowid
        self.ftc_season = conn.execute(
            """INSERT INTO seasons(program,name,year_label,slug,sort_order)
               VALUES ('ftc','DECODE','2025-26','edit-ftc',2026)"""
        ).lastrowid
        self.frc_season = conn.execute(
            """INSERT INTO seasons(program,name,year_label,slug,sort_order)
               VALUES ('frc','REEFSCAPE','2025','edit-frc',2025)"""
        ).lastrowid
        self.team_id = conn.execute(
            """INSERT INTO teams(program,number,name,owner_id,invite_code)
               VALUES ('ftc',12345,'FTC Editors',?,'invite')""",
            (self.user_id,),
        ).lastrowid
        conn.execute(
            "INSERT INTO memberships(user_id,team_id,role) VALUES (?,?,'owner')",
            (self.user_id, self.team_id),
        )
        self.design_id = conn.execute(
            """INSERT INTO designs(user_id,team_id,program,title,description,
                       cad_software,cad_link,season_id,competition_tested,image_filename)
                 VALUES (?,?,'ftc','Program Switch','A quick design.','onshape',
                         'https://cad.onshape.com/documents/example',?,1,'preview.jpg')""",
            (self.user_id, self.team_id, self.ftc_season),
        ).lastrowid
        conn.commit()
        conn.close()

        self.client = application.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def edit(self, **overrides):
        data = {
            "csrf_token": "test-csrf",
            "full_mode": "0",
            "title": "Program Switch",
            "description": "A quick design.",
            "program": "frc",
            "cad_software": "onshape",
            "cad_link": "https://cad.onshape.com/documents/example",
            "season_id": str(self.frc_season),
            "competition_tested": "1",
        }
        data.update(overrides)
        return self.client.post(f"/designs/{self.design_id}/edit", data=data)

    def design(self):
        conn = db.connect()
        row = conn.execute(
            "SELECT program,season_id,team_id FROM designs WHERE id=?",
            (self.design_id,),
        ).fetchone()
        conn.close()
        return row

    def test_edit_form_offers_both_programs_and_program_tagged_seasons(self):
        response = self.client.get(f"/designs/{self.design_id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="program" id="program-select"', response.data)
        self.assertIn(b'<option value="frc">FRC</option>', response.data)
        self.assertIn(b'data-program="frc"', response.data)

    def test_owner_can_change_program_and_incompatible_team_credit_is_removed(self):
        response = self.edit()
        self.assertEqual(response.status_code, 302)
        design = self.design()
        self.assertEqual(design["program"], "frc")
        self.assertEqual(design["season_id"], self.frc_season)
        self.assertIsNone(design["team_id"])

    def test_cross_program_season_is_rejected(self):
        response = self.edit(season_id=str(self.ftc_season))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Choose a season from the selected robotics program", response.data)
        design = self.design()
        self.assertEqual(design["program"], "ftc")
        self.assertEqual(design["team_id"], self.team_id)

    def test_version_can_change_when_model_type_has_no_season(self):
        conn = db.connect()
        archetype_id = conn.execute(
            """INSERT INTO archetypes(season_id,name,slug)
               VALUES (NULL,'Shared Model Type','shared-edit-type')"""
        ).lastrowid
        conn.execute(
            "UPDATE designs SET prototype_version=1,archetype_id=? WHERE id=?",
            (archetype_id, self.design_id),
        )
        conn.commit()
        conn.close()

        response = self.edit(
            full_mode="1",
            season_id="",
            archetype_id=str(archetype_id),
            prototype_version="2",
        )
        self.assertEqual(response.status_code, 302)

        conn = db.connect()
        version = conn.execute(
            "SELECT prototype_version FROM designs WHERE id=?", (self.design_id,)
        ).fetchone()["prototype_version"]
        conn.close()
        self.assertEqual(version, 2)

    def test_admin_recredits_the_design_inside_the_new_program(self):
        conn = db.connect()
        conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (self.user_id,))
        conn.execute(
            "UPDATE designs SET uploaded_by_admin=1 WHERE id=?", (self.design_id,)
        )
        conn.commit()
        conn.close()

        response = self.edit(
            admin_attribution="team",
            admin_team_number="12345",
            admin_team_name="FRC Editors",
        )
        self.assertEqual(response.status_code, 302)

        conn = db.connect()
        design = conn.execute(
            """SELECT d.program,d.team_id,t.program team_program,t.number
                 FROM designs d JOIN teams t ON t.id=d.team_id WHERE d.id=?""",
            (self.design_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(design["program"], "frc")
        self.assertEqual(design["team_program"], "frc")
        self.assertEqual(design["number"], 12345)


if __name__ == "__main__":
    unittest.main()
