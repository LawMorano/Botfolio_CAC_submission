"""The admin "upload for a team" credit control.

An admin identifies the team by number; the name is resolved rather than typed,
both live (the /api/admin/team-credit endpoint the picker calls) and again on
the server when the form is posted, so the credit is still right with the
picker's JavaScript disabled.
"""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import db
from robotics import ftc_teams

REGISTRY = {
    7405: {"number": 7405, "name": "Knightkrawler", "location": "Rogers, MN, USA",
           "rookie_year": 2016, "website": None},
    12345: {"number": 12345, "name": "Example Robotics", "location": "Palo Alto, CA, USA",
            "rookie_year": 2020, "website": None},
}


def fake_lookup(number, timeout=None):
    return REGISTRY.get(int(number))


def fake_search(text, limit=25, timeout=None):
    needle = (text or "").lower()
    return [team for team in REGISTRY.values() if needle in team["name"].lower()][:limit]


def outage(*args, **kwargs):
    raise ftc_teams.FtcApiError("registry unreachable")


def credit_form(**overrides):
    data = {
        "csrf_token": "test-csrf",
        "title": "Credited design",
        "description": "Posted on behalf of a team.",
        "cad_software": "onshape",
        "cad_link": "https://cad.onshape.com/documents/example",
        "competition_tested": "0",
        "upload_certification": "accepted",
        "admin_attribution": "team",
        "admin_team_number": "7405",
        # What the picker leaves empty unless it confirmed a name for this exact
        # number -- which is the case this whole feature exists for.
        "admin_team_name": "",
        "image_files": (io.BytesIO(b"fake-image-bytes"), "photo.png"),
    }
    data.update(overrides)
    return data


class _CreditCase(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        self.application.app.testing = True
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "credit.db")
        self.db_patch.start()
        db.init_db()
        conn = db.connect()
        self.admin_id = conn.execute(
            """INSERT INTO users(username,email,password_hash,is_admin,onboarding_complete,
                       accepted_terms_version,accepted_privacy_version,accepted_terms_at,
                       age_13_confirmed,minor_permission_confirmed,email_verified_at)
                 VALUES (?,?,?,1,1,'test','test',datetime('now'),1,1,datetime('now'))""",
            ("credit_admin", "credit@example.com", generate_password_hash("correct horse")),
        ).lastrowid
        self.member_id = conn.execute(
            """INSERT INTO users(username,email,password_hash,is_admin,onboarding_complete,
                       accepted_terms_version,accepted_privacy_version,accepted_terms_at,
                       age_13_confirmed,minor_permission_confirmed,email_verified_at)
                 VALUES (?,?,?,0,1,'test','test',datetime('now'),1,1,datetime('now'))""",
            ("ordinary", "ordinary@example.com", generate_password_hash("correct horse")),
        ).lastrowid
        conn.commit()
        conn.close()
        self.client = self.sign_in(self.admin_id)

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def sign_in(self, user_id):
        client = self.application.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = user_id
            session["csrf_token"] = "test-csrf"
        return client

    def publish(self, **overrides):
        with patch.object(ftc_teams, "lookup", fake_lookup), \
             patch.object(ftc_teams, "search", fake_search), \
             patch.object(self.application, "save_image_upload", return_value="quick.jpg"), \
             patch.object(self.application.infra_storage, "size", return_value=1):
            return self.client.post("/submit/link", data=credit_form(**overrides),
                                    content_type="multipart/form-data")

    def credited_team(self, title="Credited design"):
        conn = db.connect()
        row = conn.execute(
            """SELECT t.number, t.name, t.profile_status
                 FROM designs d JOIN teams t ON t.id = d.team_id
                WHERE d.title = ?""", (title,)).fetchone()
        conn.close()
        return row


class CreditLookupApiTests(_CreditCase):
    def get(self, query, client=None):
        with patch.object(ftc_teams, "lookup", fake_lookup), \
             patch.object(ftc_teams, "search", fake_search):
            return (client or self.client).get(f"/api/admin/team-credit?{query}")

    def test_a_number_resolves_to_the_registered_team_name(self):
        payload = self.get("number=7405").get_json()
        self.assertEqual(payload["state"], "found")
        self.assertEqual(payload["teams"][0]["name"], "Knightkrawler")
        self.assertEqual(payload["teams"][0]["location"], "Rogers, MN, USA")
        self.assertFalse(payload["teams"][0]["on_botfolio"])

    def test_a_number_no_team_holds_is_absent_rather_than_an_error(self):
        self.assertEqual(self.get("number=4242").get_json()["state"], "absent")

    def test_a_number_outside_the_valid_range_is_rejected_without_a_call(self):
        for number in ("0", "1000000"):
            self.assertEqual(self.get(f"number={number}").get_json()["state"], "invalid")

    def test_a_name_search_returns_teams_to_click(self):
        payload = self.get("q=robotics").get_json()
        self.assertEqual([team["number"] for team in payload["teams"]], [12345])

    def test_a_one_letter_query_is_not_searched(self):
        self.assertEqual(self.get("q=r").get_json()["state"], "short")

    def test_a_team_already_on_botfolio_keeps_its_botfolio_name(self):
        conn = db.connect()
        conn.execute(
            "INSERT INTO teams(number,name,invite_code,profile_status) "
            "VALUES (7405,'Knightkrawler (claimed)','code-a','claimed')")
        conn.commit()
        conn.close()
        team = self.get("number=7405").get_json()["teams"][0]
        self.assertEqual(team["name"], "Knightkrawler (claimed)")
        self.assertTrue(team["on_botfolio"])

    def test_a_reference_profile_is_offered_but_not_marked_as_on_botfolio(self):
        # Created by an earlier admin credit: reusable, but nobody has claimed it.
        conn = db.connect()
        conn.execute(
            "INSERT INTO teams(number,name,invite_code,profile_status) "
            "VALUES (654,'Referenced Robotics','code-b','reference')")
        conn.commit()
        conn.close()
        payload = self.get("q=Referenced").get_json()
        self.assertEqual([team["number"] for team in payload["teams"]], [654])
        self.assertFalse(payload["teams"][0]["on_botfolio"])

    def test_a_registry_outage_is_reported_as_an_outage(self):
        with patch.object(ftc_teams, "lookup", outage), patch.object(ftc_teams, "search", outage):
            self.assertEqual(self.client.get(
                "/api/admin/team-credit?number=7405").get_json()["state"], "error")
            self.assertEqual(self.client.get(
                "/api/admin/team-credit?q=robotics").get_json()["state"], "error")

    def test_only_admins_may_resolve_teams(self):
        self.assertEqual(self.get("number=7405", self.sign_in(self.member_id)).status_code, 403)
        self.assertEqual(
            self.application.app.test_client().get(
                "/api/admin/team-credit?number=7405").status_code, 403)


class CreditWithoutATypedNameTests(_CreditCase):
    def test_a_number_alone_credits_the_officially_registered_name(self):
        self.assertIn(self.publish().status_code, (302, 303))
        team = self.credited_team()
        self.assertEqual((team["number"], team["name"]), (7405, "Knightkrawler"))
        self.assertEqual(team["profile_status"], "reference")

    def test_a_name_the_picker_confirmed_is_used_as_posted(self):
        self.publish(admin_team_number="12345", admin_team_name="Example Robotics")
        self.assertEqual(self.credited_team()["name"], "Example Robotics")

    def test_an_unlisted_number_still_credits_under_its_number(self):
        self.publish(admin_team_number="424242")
        team = self.credited_team()
        self.assertEqual((team["number"], team["name"]), (424242, "Team 424242"))

    def test_a_registry_outage_does_not_block_the_upload(self):
        with patch.object(ftc_teams, "lookup", outage), \
             patch.object(self.application, "save_image_upload", return_value="quick.jpg"), \
             patch.object(self.application.infra_storage, "size", return_value=1):
            response = self.client.post("/submit/link", data=credit_form(),
                                        content_type="multipart/form-data")
        self.assertIn(response.status_code, (302, 303))
        self.assertEqual(self.credited_team()["name"], "Team 7405")

    def test_a_claimed_teams_own_name_is_never_overwritten(self):
        conn = db.connect()
        conn.execute(
            "INSERT INTO teams(number,name,invite_code,profile_status) "
            "VALUES (7405,'The Team Itself','code-c','claimed')")
        conn.commit()
        conn.close()
        self.publish()
        self.assertEqual(self.credited_team()["name"], "The Team Itself")

    def test_a_second_credit_lands_on_the_same_team_profile(self):
        self.publish()
        self.publish(title="Another design")
        conn = db.connect()
        count = conn.execute("SELECT COUNT(*) n FROM teams WHERE number=7405").fetchone()["n"]
        conn.close()
        self.assertEqual(count, 1)

    def test_a_missing_number_is_still_refused(self):
        response = self.publish(admin_team_number="")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Enter a valid team number.", response.get_data(as_text=True))


class CreditControlRenderTests(_CreditCase):
    def test_every_upload_form_ships_the_picker(self):
        for url in ("/submit", "/submit/link"):
            page = self.client.get(url).get_data(as_text=True)
            self.assertIn("data-team-credit", page, url)
            self.assertIn("data-credit-toggle", page, url)
            self.assertIn("team-credit.js", page, url)

    def test_the_edit_form_ships_the_picker_with_the_current_team_filled_in(self):
        self.publish()
        conn = db.connect()
        design_id = conn.execute(
            "SELECT id FROM designs WHERE title='Credited design'").fetchone()["id"]
        conn.close()
        page = self.client.get(f"/designs/{design_id}/edit").get_data(as_text=True)
        self.assertIn("data-team-credit", page)
        self.assertIn('value="7405"', page)
        self.assertIn("team-credit.js", page)

    def test_the_name_is_never_a_field_the_admin_has_to_fill_in(self):
        page = self.client.get("/submit").get_data(as_text=True)
        self.assertNotIn('name="admin_team_name" maxlength', page)
        self.assertIn('type="hidden"', page)


if __name__ == "__main__":
    unittest.main()
