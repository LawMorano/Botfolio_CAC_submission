import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import db
from robotics import frc_teams


class FrcImplementationTests(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        application.app.testing = True
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "frc.db")
        self.db_patch.start()
        db.init_db()
        conn = db.connect()
        application._ensure_reference_data(conn)
        self.user_id = conn.execute(
            """INSERT INTO users(username,email,password_hash,onboarding_complete,
                       email_verified_at,acknowledged_legal_version)
                 VALUES (?,?,?,1,datetime('now'),?)""",
            ("frc_builder", "frc@example.com",
             generate_password_hash("correct horse", method="pbkdf2:sha256:1"),
             application.LEGAL_NOTICE_VERSION),
        ).lastrowid
        conn.commit()
        conn.close()
        self.client = application.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def sign_in(self):
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"

    def test_same_number_can_exist_in_both_first_programs(self):
        conn = db.connect()
        conn.execute(
            "INSERT INTO teams(program,number,name,invite_code) VALUES ('ftc',254,'FTC 254','a')"
        )
        conn.execute(
            "INSERT INTO teams(program,number,name,invite_code) VALUES ('frc',254,'The Cheesy Poofs','b')"
        )
        count = conn.execute("SELECT COUNT(*) n FROM teams WHERE number=254").fetchone()["n"]
        conn.close()
        self.assertEqual(count, 2)

    def test_frc_profile_uses_the_frc_registry(self):
        lookup = {
            "state": "found",
            "team": {"number": 254, "name": "The Cheesy Poofs",
                     "location": "San Jose, California, USA",
                     "rookie_year": 1999, "website": None},
        }
        with patch.object(frc_teams, "describe", return_value=lookup) as describe:
            response = self.client.get("/teams/frc/254")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"FRC team 254", response.data)
        describe.assert_called_once_with(254)

    def test_claiming_an_frc_team_keeps_its_program(self):
        self.sign_in()
        response = self.client.post(
            "/teams",
            data={"csrf_token": "test-csrf", "program": "frc", "number": "254",
                  "name": "The Cheesy Poofs", "region": "California"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/teams/frc/254"))
        conn = db.connect()
        team = conn.execute(
            "SELECT program,name FROM teams WHERE program='frc' AND number=254"
        ).fetchone()
        conn.close()
        self.assertEqual(team["program"], "frc")

    def test_reference_data_contains_frc_seasons(self):
        conn = db.connect()
        rows = conn.execute(
            "SELECT name FROM seasons WHERE program='frc' ORDER BY sort_order DESC"
        ).fetchall()
        conn.close()
        self.assertEqual([row["name"] for row in rows[:2]], ["REBUILT", "REEFSCAPE"])

    def test_design_taxonomy_cannot_mix_ftc_and_frc_seasons(self):
        conn = db.connect()
        ftc_season = conn.execute(
            "SELECT id FROM seasons WHERE program='ftc' LIMIT 1"
        ).fetchone()["id"]
        message = self.application._design_taxonomy_error(
            conn, "frc", ftc_season, None
        )
        conn.close()
        self.assertEqual(message, "Choose a season from the selected robotics program.")

    def test_design_taxonomy_accepts_program_archetype_without_a_season(self):
        conn = db.connect()
        archetype_id = conn.execute(
            """INSERT INTO archetypes(season_id,name,slug)
               VALUES (NULL,'Shared FRC Type','shared-frc-type')"""
        ).lastrowid
        message = self.application._design_taxonomy_error(
            conn, "frc", None, archetype_id
        )
        conn.close()
        self.assertIsNone(message)

    def test_design_taxonomy_accepts_matching_archetype_and_season(self):
        conn = db.connect()
        season_id = conn.execute(
            "SELECT id FROM seasons WHERE program='frc' LIMIT 1"
        ).fetchone()["id"]
        archetype_id = conn.execute(
            """INSERT INTO archetypes(season_id,name,slug)
               VALUES (?, 'Season FRC Type','season-frc-type')""",
            (season_id,),
        ).lastrowid
        message = self.application._design_taxonomy_error(
            conn, "frc", season_id, archetype_id
        )
        conn.close()
        self.assertIsNone(message)

    def test_existing_team_data_migrates_without_breaking_memberships(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE users (id INTEGER PRIMARY KEY);
            CREATE TABLE teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number INTEGER NOT NULL UNIQUE,
                name TEXT NOT NULL,
                region TEXT NOT NULL DEFAULT '',
                owner_id INTEGER,
                invite_code TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (owner_id) REFERENCES users(id)
            );
            CREATE TABLE memberships (
                user_id INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, team_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (team_id) REFERENCES teams(id)
            );
            INSERT INTO users(id) VALUES (1);
            INSERT INTO teams(number,name,owner_id,invite_code)
                VALUES (254,'FTC 254',1,'invite');
            INSERT INTO memberships(user_id,team_id) VALUES (1,1);
            CREATE TABLE seasons (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE designs (id INTEGER PRIMARY KEY);
            """
        )

        self.application._ensure_program_schema(conn)
        conn.execute(
            "INSERT INTO teams(program,number,name,invite_code) "
            "VALUES ('frc',254,'The Cheesy Poofs','frc-invite')"
        )

        self.assertEqual(
            conn.execute("SELECT COUNT(*) n FROM teams WHERE number=254").fetchone()["n"],
            2,
        )
        self.assertEqual(
            conn.execute("SELECT program FROM teams WHERE id=1").fetchone()["program"],
            "ftc",
        )
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        conn.close()


if __name__ == "__main__":
    unittest.main()
