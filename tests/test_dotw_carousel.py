"""Design-of-the-Week hero carousel: credit line and self-turning behaviour.

Two things this covers, both requested for the hero merry-go-round:

  1. An admin upload with no team credited is curated, not attributed — the
     carousel must NOT print the BotfolioAdmin account beneath it. A real member
     or team still shows.
  2. The ring turns itself every 10s with static black arrow controls and no
     continuous animation loop.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db


class DotwHeroCreditTests(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        application.app.testing = True

        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "dotw.db")
        self.db_patch.start()
        db.init_db()

        conn = db.connect()
        # A distinctive admin username so "not shown" is unambiguous. The hero
        # suppresses on the uploaded_by_admin flag, not on the name itself.
        self.admin_id = conn.execute(
            "INSERT INTO users(username,email,password_hash,is_admin,onboarding_complete)"
            " VALUES (?,?,?,1,1)",
            ("curator_admin_acct", "curator@example.com", "hash"),
        ).lastrowid
        self.member_id = conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete)"
            " VALUES (?,?,?,1)",
            ("realmember", "member@example.com", "hash"),
        ).lastrowid
        conn.commit()
        conn.close()

        self.week = application.design_week_start()
        self.client = application.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def _award_design(self, *, user_id, title, uploaded_by_admin):
        conn = db.connect()
        design_id = conn.execute(
            "INSERT INTO designs(user_id,title,image_filename,uploaded_by_admin)"
            " VALUES (?,?,?,?)",
            (user_id, title, f"{title.lower().replace(' ', '-')}.jpg", uploaded_by_admin),
        ).lastrowid
        conn.execute(
            "INSERT INTO design_of_week_awards(design_id,selected_by,current_week)"
            " VALUES (?,?,?)",
            (design_id, self.admin_id, self.week),
        )
        conn.commit()
        conn.close()
        return design_id

    def _hero(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        body = home.data
        start = body.index(b'hero__preview')
        end = body.index(b'founding-callout')
        return body[start:end]

    def test_admin_upload_without_a_team_hides_the_admin_account(self):
        self._award_design(
            user_id=self.admin_id, title="Curated Intake", uploaded_by_admin=1
        )
        hero = self._hero()
        # The card is there...
        self.assertIn(b"Curated Intake", hero)
        # ...but the BotfolioAdmin-style account is never credited beneath it.
        self.assertNotIn(b"curator_admin_acct", hero)

    def test_member_upload_still_shows_its_credit(self):
        self._award_design(
            user_id=self.member_id, title="Member Intake", uploaded_by_admin=0
        )
        hero = self._hero()
        self.assertIn(b"Member Intake", hero)
        self.assertIn(b"realmember", hero)


class DotwAutoRotateSourceTests(unittest.TestCase):
    """The auto-rotate timer and static controls."""

    @classmethod
    def setUpClass(cls):
        root = Path(__file__).parents[1]
        cls.script = (root / "static" / "dotw-carousel.js").read_text(encoding="utf-8")
        cls.stylesheet = (root / "static" / "style.css").read_text(encoding="utf-8")
        cls.home = (root / "templates" / "index.html").read_text(encoding="utf-8")

    def test_ring_uses_a_ten_second_timer(self):
        self.assertIn("10000", self.script)
        self.assertIn("setTimeout", self.script)
        self.assertNotIn("requestAnimationFrame", self.script)
        self.assertIn("reduceMotion.matches", self.script)

    def test_arrows_stay_black_without_a_progress_animation(self):
        self.assertNotIn("--dotw-progress", self.script)
        self.assertNotIn("--dotw-progress", self.stylesheet)
        arrow = self.stylesheet.split(".dotw-arrow {", 1)[1].split("}", 1)[0]
        self.assertIn("background: #05070a", arrow)

    def test_hero_credit_suppresses_admin_uploads(self):
        # The template guard that drops the admin account from the credit line.
        self.assertIn("not d['uploaded_by_admin']", self.home)


if __name__ == "__main__":
    unittest.main()
