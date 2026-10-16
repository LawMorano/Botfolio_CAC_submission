"""Withdrawing a Design-of-the-Week award inside the week it was granted.

The award has two halves: ``design_of_week_awards`` holds the current
selection (what the homepage hero shows) and ``design_of_week_history`` holds
the permanent dated record (what the badge on the design page shows). Removing
a design mid-week used to clear only the first half, so the design kept a
"Design of the Week · Week of ..." badge for an award that had been taken back.

These tests pin the corrected behaviour and its two easy-to-miss edges. An
award from an earlier, completed week must survive the withdrawal. And the
withdrawal must survive the legacy backfill in ``ensure_runtime_schema``, which
re-derives dated history from any surviving award row: that backfill runs on
every app import and inside the nightly maintenance pass, so a resurrection
would land within a day rather than on some distant deploy.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db


class DesignOfWeekWithdrawalTests(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        application.app.testing = True

        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "dotw-award.db")
        self.db_patch.start()
        db.init_db()

        conn = db.connect()
        self.admin_id = conn.execute(
            "INSERT INTO users(username,email,password_hash,is_admin,onboarding_complete)"
            " VALUES (?,?,?,1,1)",
            ("award_admin", "award-admin@example.com", "hash"),
        ).lastrowid
        self.member_id = conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete)"
            " VALUES (?,?,?,1)",
            ("award_member", "award-member@example.com", "hash"),
        ).lastrowid
        self.design_id = conn.execute(
            "INSERT INTO designs(user_id,title,image_filename) VALUES (?,?,?)",
            (self.member_id, "Withdrawable Swerve", "withdrawable-swerve.jpg"),
        ).lastrowid
        conn.commit()
        conn.close()

        self.week = application.design_week_start()
        self.client = application.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    # -- helpers ---------------------------------------------------------
    def _signin(self, user_id):
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["csrf_token"] = "test-csrf"

    def _toggle(self, *, csrf="test-csrf", follow=False):
        data = {"csrf_token": csrf} if csrf is not None else {}
        return self.client.post(
            f"/designs/{self.design_id}/design-of-the-week",
            data=data,
            follow_redirects=follow,
        )

    def _detail(self):
        page = self.client.get(f"/designs/{self.design_id}")
        self.assertEqual(page.status_code, 200)
        return page.data

    def _homepage(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        return home.data

    def _hero(self):
        # The Design-of-the-Week carousel, or nothing at all when no design is
        # currently selected. "Newest designs" lists every design regardless of
        # any award, so the slice matters.
        body = self._homepage()
        if b"hero__preview" not in body:
            return b""
        return body[body.index(b"hero__preview"):body.index(b"founding-callout")]

    def _rows(self):
        conn = db.connect()
        awards = conn.execute(
            "SELECT week_start FROM design_of_week_history WHERE design_id=?"
            " ORDER BY week_start",
            (self.design_id,),
        ).fetchall()
        current = conn.execute(
            "SELECT is_current,current_week FROM design_of_week_awards WHERE design_id=?",
            (self.design_id,),
        ).fetchone()
        conn.close()
        return [row["week_start"] for row in awards], current

    def _badge_weeks(self, body):
        # One badge per dated award; the week is printed in the badge text.
        return [
            chunk.split(b"<")[0].strip()
            for chunk in body.split(b"Design of the Week &middot; Week of ")[1:]
        ]

    # -- tests -----------------------------------------------------------
    def test_choosing_a_design_records_the_award_and_shows_the_badge(self):
        self._signin(self.admin_id)
        self.assertEqual(self._toggle().status_code, 302)

        history, current = self._rows()
        self.assertEqual(history, [self.week])
        self.assertEqual((current["is_current"], current["current_week"]), (1, self.week))

        body = self._detail()
        self.assertEqual(self._badge_weeks(body), [self.week.encode()])
        self.assertIn(b"Remove from this week", body)
        self.assertIn(b"Withdrawable Swerve", self._hero())
        self.assertIn(b"Designs of the Week", self._homepage())

    def test_removing_it_in_the_same_week_takes_the_award_back(self):
        self._signin(self.admin_id)
        self._toggle()
        removed = self._toggle(follow=True)
        self.assertEqual(removed.status_code, 200)
        # What the admin is told has to match what happened: the old copy
        # promised "Its dated award remains".
        self.assertIn(b"award no longer stands", removed.data)
        self.assertNotIn(b"dated award remains", removed.data)

        # Both halves of the award are gone, not just the current selection.
        history, current = self._rows()
        self.assertEqual(history, [])
        self.assertIsNone(current)

        body = self._detail()
        self.assertEqual(self._badge_weeks(body), [])
        self.assertNotIn(b"detail-card__award", body)
        # The button offers the award again rather than another removal.
        self.assertIn(b"Choose as Design of the Week", body)
        self.assertNotIn(b"Remove from this week", body)
        # Off the hero carousel and out of the featured band as well.
        self.assertEqual(self._hero(), b"")
        self.assertNotIn(b"Designs of the Week", self._homepage())

    def test_an_award_from_an_earlier_week_survives_this_week_s_withdrawal(self):
        earlier = "2024-01-07"
        conn = db.connect()
        conn.execute(
            "INSERT INTO design_of_week_history(design_id,week_start,selected_by)"
            " VALUES (?,?,?)",
            (self.design_id, earlier, self.admin_id),
        )
        conn.commit()
        conn.close()

        self._signin(self.admin_id)
        self._toggle()
        self._toggle()

        history, current = self._rows()
        self.assertEqual(history, [earlier])
        self.assertIsNone(current)
        self.assertEqual(self._badge_weeks(self._detail()), [earlier.encode()])

        # And it is still the earlier week alone once the backfill has run: a
        # too-wide delete plus a re-derivation could otherwise hide each other.
        self.application.ensure_runtime_schema()
        history, _ = self._rows()
        self.assertEqual(history, [earlier])
        self.assertEqual(self._badge_weeks(self._detail()), [earlier.encode()])

    def test_the_withdrawal_is_not_undone_by_the_startup_backfill(self):
        self._signin(self.admin_id)
        self._toggle()
        self._toggle()

        # A restart re-runs the legacy backfill, which rebuilds dated history
        # from award rows. The withdrawal has to outlast it.
        self.application.ensure_runtime_schema()

        history, _ = self._rows()
        self.assertEqual(history, [])
        self.assertEqual(self._badge_weeks(self._detail()), [])

    def test_the_nightly_maintenance_pass_does_not_bring_it_back(self):
        import maintenance

        self._signin(self.admin_id)
        self._toggle()
        self._toggle()

        # run_retention() calls the same backfill before rolling weeks over, so
        # the withdrawal has to outlast the daily cron and not just a restart.
        maintenance.run_retention()

        history, _ = self._rows()
        self.assertEqual(history, [])
        self.assertEqual(self._badge_weeks(self._detail()), [])

    def test_it_can_be_chosen_again_after_being_withdrawn(self):
        self._signin(self.admin_id)
        self._toggle()
        self._toggle()
        self.assertEqual(self._toggle().status_code, 302)

        history, current = self._rows()
        self.assertEqual(history, [self.week])
        self.assertEqual((current["is_current"], current["current_week"]), (1, self.week))
        self.assertEqual(self._badge_weeks(self._detail()), [self.week.encode()])

    def test_a_member_cannot_withdraw_an_award(self):
        self._signin(self.admin_id)
        self._toggle()
        self._signin(self.member_id)
        self.assertEqual(self._toggle().status_code, 403)
        history, _ = self._rows()
        self.assertEqual(history, [self.week])

    def test_a_withdrawal_without_a_csrf_token_is_refused(self):
        self._signin(self.admin_id)
        self._toggle()
        self.assertEqual(self._toggle(csrf=None).status_code, 400)
        history, current = self._rows()
        self.assertEqual(history, [self.week])
        self.assertEqual(current["is_current"], 1)


if __name__ == "__main__":
    unittest.main()
