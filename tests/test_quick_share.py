"""The quick-share (link-only) publish path and the matching quick edit form."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import db


def image_upload(name="photo.png"):
    return (io.BytesIO(b"fake-image-bytes"), name)


def quick_share_form(**overrides):
    data = {
        "csrf_token": "test-csrf",
        "team_id": "individual",
        "title": "Quick Shared Design",
        "description": "Linked from elsewhere.",
        "cad_software": "onshape",
        "cad_link": "https://cad.onshape.com/documents/example",
        "competition_tested": "1",
        "archetype_id": None,
        "tags": None,
        "upload_certification": "accepted",
        "image_files": image_upload(),
    }
    data.update(overrides)
    return {key: value for key, value in data.items() if value is not None}


class QuickShareCompetitionTestedTests(unittest.TestCase):
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
        cursor = conn.execute(
            """INSERT INTO users(username,email,password_hash,onboarding_complete,
                       accepted_terms_version,accepted_privacy_version,accepted_terms_at,
                       age_13_confirmed,minor_permission_confirmed,email_verified_at)
                 VALUES (?,?,?,1,'test','test',datetime('now'),1,1,datetime('now'))""",
            ("quick_sharer", "quick@example.com", generate_password_hash("correct horse")),
        )
        self.user_id = cursor.lastrowid
        season = conn.execute(
            "INSERT INTO seasons(name,year_label,slug,sort_order) VALUES('DECODE','2025-26','decode',4)"
        )
        self.season_id = season.lastrowid
        # One season-scoped model type and one cross-season one, so the tests
        # cover both halves of the browser-side narrowing.
        self.turret_id = conn.execute(
            "INSERT INTO archetypes(season_id,name,slug) VALUES (?,'Turreted Shooter','turreted-shooter')",
            (self.season_id,),
        ).lastrowid
        self.full_robot_id = conn.execute(
            "INSERT INTO archetypes(season_id,name,slug) VALUES (NULL,'Full Robot','full-robot')"
        ).lastrowid
        conn.commit()
        conn.close()
        self.client = self.application.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def publish(self, **overrides):
        with patch.object(self.application, "save_image_upload", return_value="quick.jpg"), \
             patch.object(self.application.infra_storage, "size", return_value=1):
            return self.client.post(
                "/submit/link", data=quick_share_form(**overrides),
                content_type="multipart/form-data",
            )

    def design(self, title="Quick Shared Design"):
        conn = db.connect()
        row = conn.execute("SELECT * FROM designs WHERE title=?", (title,)).fetchone()
        conn.close()
        return row

    def test_form_offers_the_competition_tested_choice(self):
        page = self.client.get("/submit/link")
        self.assertIn(b'name="competition_tested" required', page.data)
        self.assertIn(b"Yes, used in competition", page.data)

    def test_publishing_stores_a_yes_answer(self):
        response = self.publish(competition_tested="1")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.design()["competition_tested"], 1)

    def test_publishing_stores_a_no_answer(self):
        response = self.publish(competition_tested="0")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.design()["competition_tested"], 0)

    def test_missing_answer_is_rejected(self):
        response = self.publish(competition_tested=None)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.design())

    def test_out_of_range_answer_is_rejected(self):
        response = self.publish(competition_tested="maybe")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.design())

    def test_quick_edit_keeps_the_answer_editable(self):
        self.publish(competition_tested="0")
        design_id = self.design()["id"]

        form = self.client.get(f"/designs/{design_id}/edit")
        self.assertIn(b'name="competition_tested" required', form.data)
        # A quick design still hides the full-upload-only fields.
        self.assertNotIn(b'name="prototype_version"', form.data)

        response = self.client.post(
            f"/designs/{design_id}/edit",
            data={
                "csrf_token": "test-csrf", "full_mode": "0",
                "title": "Quick Shared Design", "description": "Linked from elsewhere.",
                "cad_software": "onshape",
                "cad_link": "https://cad.onshape.com/documents/example",
                "competition_tested": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        updated = self.design()
        self.assertEqual(updated["competition_tested"], 1)
        # The full-only columns are still untouched by a quick edit.
        self.assertIsNone(updated["prototype_version"])


if __name__ == "__main__":
    unittest.main()


class QuickShareModelTypeAndTagTests(QuickShareCompetitionTestedTests):
    """The model type catalog and free-form tags on the quick-share path."""

    def tags_on(self, design_id):
        conn = db.connect()
        rows = conn.execute(
            "SELECT t.name FROM design_tags dt JOIN tags t ON t.id=dt.tag_id "
            "WHERE dt.design_id=? ORDER BY t.name", (design_id,)
        ).fetchall()
        conn.close()
        return [row["name"] for row in rows]

    def test_form_offers_the_whole_model_type_catalog(self):
        page = self.client.get("/submit/link").data
        self.assertIn(b'name="archetype_id"', page)
        self.assertIn(b"Turreted Shooter", page)
        self.assertIn(b"Full Robot", page)
        # The season a model type belongs to travels with it so the browser can
        # narrow the list; a cross-season one carries an empty marker.
        self.assertIn(f'data-season="{self.season_id}"'.encode(), page)
        self.assertIn(b'data-season=""', page)

    def test_form_offers_a_tag_field(self):
        page = self.client.get("/submit/link").data
        self.assertIn(b'name="tags"', page)
        self.assertIn(b'id="tag-suggestions"', page)

    def test_publishing_stores_the_chosen_model_type(self):
        response = self.publish(archetype_id=str(self.turret_id))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.design()["archetype_id"], self.turret_id)

    def test_no_model_type_chosen_is_stored_as_none(self):
        self.assertEqual(self.publish().status_code, 302)
        self.assertIsNone(self.design()["archetype_id"])

    def test_unknown_model_type_is_dropped_not_stored(self):
        response = self.publish(archetype_id="99999")
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.design()["archetype_id"])

    def test_publishing_attaches_the_typed_tags(self):
        response = self.publish(tags="turret, passthrough ,")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.tags_on(self.design()["id"]), ["passthrough", "turret"])

    def test_no_tags_typed_attaches_nothing(self):
        self.assertEqual(self.publish().status_code, 302)
        self.assertEqual(self.tags_on(self.design()["id"]), [])

    def test_a_rejected_tag_undoes_the_whole_publish(self):
        import app as application
        too_long = "x" * (application.MAX_TAG_LENGTH + 1)
        response = self.publish(tags=too_long)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/submit/link", response.headers["Location"])
        self.assertIsNone(self.design())

    def test_quick_edit_keeps_the_model_type_editable(self):
        self.publish(archetype_id=str(self.turret_id))
        design_id = self.design()["id"]

        form = self.client.get(f"/designs/{design_id}/edit")
        self.assertIn(b'name="archetype_id"', form.data)

        response = self.client.post(
            f"/designs/{design_id}/edit",
            data={
                "csrf_token": "test-csrf", "full_mode": "0",
                "title": "Quick Shared Design", "description": "Linked from elsewhere.",
                "cad_software": "onshape",
                "cad_link": "https://cad.onshape.com/documents/example",
                "competition_tested": "1",
                "archetype_id": str(self.full_robot_id),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.design()["archetype_id"], self.full_robot_id)
