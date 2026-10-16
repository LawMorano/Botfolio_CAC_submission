"""The curated gallery shelf order and chronological homepage order.

Team uploads lead, then individual ones, then anything an admin published;
inside each of those, full-robot designs come before single mechanisms, and
link-only quick shares sit behind the lot in the gallery. Every design here is
created in that order, so the homepage's newest-first list is exactly the
reverse while the gallery demonstrates its shelf ordering.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import db


class DesignShelfOrderTests(unittest.TestCase):
    def setUp(self):
        import app as application
        self.application = application
        self.application.app.testing = True
        # /designs/<id>/edit is rate limited per user, and each test
        # starts on a fresh database where the owner is again user 1.
        self.application.ratelimit._buckets.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "test.db")
        self.db_patch.start()
        db.init_db()
        conn = db.connect()

        def add_user(username, is_admin=0):
            return conn.execute(
                """INSERT INTO users(username,email,password_hash,is_admin,
                           onboarding_complete,accepted_terms_version,
                           accepted_privacy_version,accepted_terms_at,
                           age_13_confirmed,minor_permission_confirmed,
                           email_verified_at)
                     VALUES (?,?,?,?,1,'test','test',datetime('now'),1,1,datetime('now'))""",
                (username, f"{username}@example.com",
                 generate_password_hash("correct horse"), is_admin),
            ).lastrowid

        member = add_user("team_member")
        solo = add_user("solo_builder")
        admin = add_user("admin_user", is_admin=1)
        self.team_id = conn.execute(
            "INSERT INTO teams(number,name,owner_id,invite_code) VALUES (?,?,?,?)",
            (9999, "Demo Robotics", member, "demo-invite"),
        ).lastrowid
        season_id = conn.execute(
            "INSERT INTO seasons(name,year_label,slug,sort_order) VALUES ('DECODE','2025-26','decode',4)"
        ).lastrowid
        self.full_robot_id = conn.execute(
            "INSERT INTO archetypes(season_id,name,slug) VALUES (?,'Full Robot','full-robot')",
            (season_id,),
        ).lastrowid
        self.mechanism_id = conn.execute(
            "INSERT INTO archetypes(season_id,name,slug) VALUES (?,'Artifact Intake','artifact-intake')",
            (season_id,),
        ).lastrowid

        # Oldest first, so plain recency would reverse this list.
        self.expected = [
            "Team full robot",
            "Team mechanism",
            "Solo full robot",
            "Solo mechanism",
            "Admin full robot",
            "Admin mechanism",
            "Team quick share",
            "Admin quick share",
        ]
        plan = [
            ("Team full robot", self.team_id, member, 0, self.full_robot_id, True),
            ("Team mechanism", self.team_id, member, 0, self.mechanism_id, True),
            ("Solo full robot", None, solo, 0, self.full_robot_id, True),
            ("Solo mechanism", None, solo, 0, self.mechanism_id, True),
            ("Admin full robot", None, admin, 1, self.full_robot_id, True),
            ("Admin mechanism", None, admin, 1, self.mechanism_id, True),
            ("Team quick share", self.team_id, member, 0, None, False),
            ("Admin quick share", None, admin, 1, None, False),
        ]
        self.design_ids = {}
        for minute, (title, team_id, user_id, by_admin, archetype_id, full) in enumerate(plan):
            self.design_ids[title] = conn.execute(
                """INSERT INTO designs(user_id,team_id,title,description,season_id,
                           archetype_id,prototype_version,image_filename,model_filename,
                           uploaded_by_admin,created_at)
                     VALUES (?,?,?,'',?,?,?,?,?,?,datetime('now',?))""",
                (user_id, team_id, title, season_id, archetype_id,
                 1 if full else None, "shot.jpg", "model.stl" if full else None,
                 by_admin, f"-{len(plan) - minute} minutes"),
            ).lastrowid
        conn.commit()
        conn.close()
        self.client = self.application.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def order_on(self, path):
        """The design titles in the order the page lists them."""
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200)
        body = page.data.decode()
        found = [(body.index(title), title) for title in self.expected if title in body]
        self.assertEqual(len(found), len(self.expected), f"missing designs on {path}")
        return [title for _, title in sorted(found)]

    def test_gallery_leads_with_team_uploads_and_ends_with_quick_shares(self):
        self.assertEqual(self.order_on("/gallery"), self.expected)

    def test_home_page_grid_is_newest_first_regardless_of_shelf_bucket(self):
        self.assertEqual(self.order_on("/"), list(reversed(self.expected)))

    def test_explicit_sorts_reorder_within_the_shelf_order(self):
        # The most-liked design is an admin mechanism, the bottom of the
        # non-quick order: sorting by likes must not lift it past a team's.
        conn = db.connect()
        for user_id in (1, 2, 3):
            conn.execute(
                "INSERT INTO design_likes(user_id,design_id) VALUES (?,?)",
                (user_id, self.design_ids["Admin mechanism"]),
            )
        conn.commit()
        conn.close()
        self.assertEqual(self.order_on("/gallery?sort=liked"), self.expected)

    def test_recency_still_breaks_ties_inside_a_bucket(self):
        conn = db.connect()
        newest = conn.execute(
            """INSERT INTO designs(user_id,team_id,title,description,archetype_id,
                       prototype_version,image_filename,model_filename,uploaded_by_admin)
                 VALUES (?,?,'Team full robot two','',?,1,'shot.jpg','model.stl',0)""",
            (1, self.team_id, self.full_robot_id),
        ).lastrowid
        conn.commit()
        conn.close()
        self.assertIsNotNone(newest)
        body = self.client.get("/gallery").data.decode()
        self.assertLess(body.index("Team full robot two"), body.index("Team full robot<"))
        self.assertLess(body.index("Team full robot two"), body.index("Team mechanism"))


if __name__ == "__main__":
    unittest.main()
