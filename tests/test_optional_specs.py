"""Physical specifications are optional, and travel as a set.

Plenty of designs are worth sharing before anyone has reached for a set of
calipers, so the upload form no longer holds a publish hostage to a bounding
box. The three dimensions stay all-or-nothing, though: a box with a side
missing describes nothing, and the design page only prints the row when it has
all three, so a partial triple would be stored and then never shown.

Motor and servo counts are untouched — those really are independent, and were
already optional one at a time.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import db


def submit_form(**overrides):
    """A publishable /submit body. Pass a field as None to leave it out."""
    data = {
        "csrf_token": "test-csrf",
        "team_id": "individual",
        "title": "Unmeasured bracket",
        "description": "A part shared before anyone reached for the calipers.",
        "prototype_version": "1",
        "competition_tested": "0",
        "length_in": "18",
        "width_in": "18",
        "height_in": "14",
        "preview_data_url": "data:image/png;base64,test",
        "upload_certification": "accepted",
    }
    data.update(overrides)
    return {key: value for key, value in data.items() if value is not None}


class DimensionValidatorTests(unittest.TestCase):
    """dimension_error on its own, before any of it reaches a route."""

    def setUp(self):
        import app as application
        self.check = application.dimension_error

    def test_a_blank_triple_is_accepted(self):
        self.assertIsNone(self.check(["", "", ""], (None, None, None)))

    def test_a_complete_triple_is_accepted(self):
        self.assertIsNone(self.check(["18", "18", "14"], (18.0, 18.0, 14.0)))

    def test_a_partial_triple_is_refused_as_a_set(self):
        for raws, values in (
            (["18", "18", ""], (18.0, 18.0, None)),
            (["18", "", ""], (18.0, None, None)),
            (["", "", "14"], (None, None, 14.0)),
        ):
            with self.subTest(raws=raws):
                self.assertIn("all three", self.check(raws, values))

    def test_a_supplied_dimension_is_still_range_checked(self):
        # Relaxing "absent" must not relax "present but nonsense".
        for raws, values in (
            (["0", "18", "14"], (0.0, 18.0, 14.0)),
            (["-3", "18", "14"], (-3.0, 18.0, 14.0)),
            (["1001", "18", "14"], (1001.0, 18.0, 14.0)),
        ):
            with self.subTest(raws=raws):
                self.assertIn("positive number", self.check(raws, values))

    def test_a_dimension_that_is_not_a_number_is_refused(self):
        # A filled box that will not parse is not the same as an empty one.
        self.assertIn("positive number", self.check(["wide", "18", "14"],
                                                    (None, 18.0, 14.0)))

    def test_whitespace_alone_counts_as_blank(self):
        self.assertIsNone(self.check(["", "", ""], (None, None, None)))


class OptionalSpecRouteTests(unittest.TestCase):
    """Publishing and editing a design that carries no measurements."""

    def setUp(self):
        import app as application
        self.application = application
        self.application.app.testing = True
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "test.db")
        self.db_patch.start()
        db.init_db()
        self.application.ratelimit._buckets.clear()

        conn = db.connect()
        self.user_id = conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete,"
            "email_verified_at,acknowledged_legal_version) "
            "VALUES (?,?,?,1,datetime('now'),?)",
            ("builder", "builder@example.com",
             generate_password_hash("correct horse", method="pbkdf2:sha256:1"),
             self.application.LEGAL_NOTICE_VERSION),
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
        with patch.object(self.application, "save_preview_data_url",
                          return_value="preview.jpg"), \
             patch.object(self.application.infra_storage, "size", return_value=1_024):
            return self.client.post("/submit", data=submit_form(**overrides),
                                    follow_redirects=True,
                                    content_type="multipart/form-data")

    def stored(self, title):
        conn = db.connect()
        row = conn.execute(
            "SELECT id,length_in,width_in,height_in,dimension_unit FROM designs WHERE title=?",
            (title,),
        ).fetchone()
        conn.close()
        return row

    def add_design(self, title, dimensions=(None, None, None)):
        """A full (non-quick) design, so editing it opens the full form."""
        conn = db.connect()
        design_id = conn.execute(
            "INSERT INTO designs(user_id,title,description,image_filename,"
            "prototype_version,competition_tested,length_in,width_in,height_in,"
            "upload_status) VALUES (?,?,'Competition part','preview.jpg',1,0,?,?,?,"
            "'approved')",
            (self.user_id, title, *dimensions),
        ).lastrowid
        conn.commit()
        conn.close()
        return design_id

    def edit_form(self, **overrides):
        """The full edit body. A browser posts every box, blank ones included."""
        data = {
            "csrf_token": "test-csrf",
            "title": "Renamed bracket",
            "description": "Still a competition part.",
            "cad_software": "other",
            "prototype_version": "1",
            "competition_tested": "0",
            "length_in": "18",
            "width_in": "18",
            "height_in": "14",
            "full_mode": "1",
        }
        data.update(overrides)
        return {key: value for key, value in data.items() if value is not None}

    # -- publishing ----------------------------------------------------------

    def test_a_design_publishes_with_no_dimensions_at_all(self):
        page = self.publish(title="Unmeasured bracket",
                            length_in=None, width_in=None, height_in=None)
        self.assertEqual(page.status_code, 200)
        design = self.stored("Unmeasured bracket")
        self.assertIsNotNone(design, page.data.decode()[:400])
        self.assertIsNone(design["length_in"])
        self.assertIsNone(design["width_in"])
        self.assertIsNone(design["height_in"])

    def test_blank_dimension_boxes_publish_the_same_as_absent_ones(self):
        # What a browser actually posts when the fields are left untouched.
        self.publish(title="Blank boxes", length_in="", width_in="", height_in="")
        design = self.stored("Blank boxes")
        self.assertIsNotNone(design)
        self.assertIsNone(design["length_in"])

    def test_dimensions_are_still_stored_when_they_are_given(self):
        self.publish(title="Measured bracket")
        design = self.stored("Measured bracket")
        self.assertEqual(
            (design["length_in"], design["width_in"], design["height_in"]),
            (18.0, 18.0, 14.0),
        )

    def test_millimeters_are_accepted_and_normalized(self):
        self.publish(title="Metric bracket", dimension_unit="mm",
                     length_in="457.2", width_in="457.2", height_in="355.6")
        design = self.stored("Metric bracket")
        self.assertEqual(design["dimension_unit"], "mm")
        self.assertEqual(
            (design["length_in"], design["width_in"], design["height_in"]),
            (18.0, 18.0, 14.0),
        )

    def test_a_partial_triple_is_refused_rather_than_half_stored(self):
        page = self.publish(title="Half measured", height_in=None)
        self.assertIn("Enter all three dimensions", page.data.decode())
        self.assertIsNone(self.stored("Half measured"))

    def test_a_supplied_dimension_is_still_range_checked(self):
        page = self.publish(title="Impossible bracket", length_in="0")
        self.assertIn("positive number", page.data.decode())
        self.assertIsNone(self.stored("Impossible bracket"))

    # -- the form itself -----------------------------------------------------

    def test_the_submit_form_no_longer_demands_dimensions(self):
        page = self.client.get("/submit").data.decode()
        block = page[page.index("design-dimensions"):]
        block = block[:block.index("</div>")]
        self.assertIn('name="length_in"', block)
        self.assertNotIn("required", block)

    def test_the_form_says_the_specifications_may_be_skipped(self):
        page = self.client.get("/submit").data.decode()
        self.assertIn("Optional. Skip them if nothing is measured yet", page)

    def test_the_submit_form_offers_millimeters(self):
        page = self.client.get("/submit").data.decode()
        self.assertIn('name="dimension_unit"', page)
        self.assertIn('<option value="mm">Millimeters (mm)</option>', page)

    # -- asynchronous reactions --------------------------------------------

    def test_like_requests_can_update_without_a_redirect(self):
        design_id = self.add_design("Likeable bracket")
        response = self.client.post(
            f"/designs/{design_id}/like",
            data={"csrf_token": "test-csrf"},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"liked": True, "like_count": 1})

        response = self.client.post(
            f"/designs/{design_id}/like",
            data={"csrf_token": "test-csrf"},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.get_json(), {"liked": False, "like_count": 0})

    def test_tag_votes_can_update_without_a_redirect(self):
        design_id = self.add_design("Tagged bracket")
        conn = db.connect()
        tag_id = conn.execute(
            "INSERT INTO tags(name,key,created_by) VALUES ('intake','intake',?)",
            (self.user_id,),
        ).lastrowid
        conn.execute(
            "INSERT INTO design_tags(design_id,tag_id,added_by) VALUES (?,?,?)",
            (design_id, tag_id, self.user_id),
        )
        conn.commit()
        conn.close()

        response = self.client.post(
            f"/designs/{design_id}/tags/{tag_id}/vote",
            data={"csrf_token": "test-csrf", "value": "1"},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"score": 1, "my_vote": 1})

        response = self.client.post(
            f"/designs/{design_id}/tags/{tag_id}/vote",
            data={"csrf_token": "test-csrf", "value": "1"},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.get_json(), {"score": 0, "my_vote": None})

    def test_design_page_marks_reactions_for_async_submission(self):
        design_id = self.add_design("Interactive bracket")
        page = self.client.get(f"/designs/{design_id}").data.decode()
        self.assertIn("data-async-like", page)
        self.assertIn('id="design-like-count"', page)
        self.assertIn("event.preventDefault()", page)

    # -- editing -------------------------------------------------------------

    def test_a_design_without_dimensions_can_still_be_edited(self):
        """The retroactive half: quick shares have had NULL dimensions all along."""
        design_id = self.add_design("Unmeasured original")
        # Three empty boxes: exactly what the form renders for a design that
        # has never been measured, and what the browser posts back untouched.
        response = self.client.post(f"/designs/{design_id}/edit",
                                    data=self.edit_form(length_in="", width_in="",
                                                        height_in=""),
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        design = self.stored("Renamed bracket")
        self.assertIsNotNone(design, "the title change did not take")
        self.assertIsNone(design["length_in"])

    def test_clearing_every_dimension_removes_them(self):
        design_id = self.add_design("Measured original", (18.0, 18.0, 14.0))
        self.client.post(f"/designs/{design_id}/edit",
                         data=self.edit_form(length_in="", width_in="",
                                             height_in=""),
                         follow_redirects=True)
        design = self.stored("Renamed bracket")
        self.assertIsNotNone(design)
        self.assertIsNone(design["length_in"])
        self.assertIsNone(design["height_in"])

    def test_clearing_only_one_dimension_is_refused(self):
        design_id = self.add_design("Measured original", (18.0, 18.0, 14.0))
        response = self.client.post(f"/designs/{design_id}/edit",
                                    data=self.edit_form(height_in=""),
                                    follow_redirects=True)
        self.assertIn("Enter all three dimensions", response.data.decode())
        conn = db.connect()
        design = conn.execute("SELECT title,height_in FROM designs WHERE id=?",
                              (design_id,)).fetchone()
        conn.close()
        self.assertEqual(design["title"], "Measured original")
        self.assertEqual(design["height_in"], 14.0)

    def test_editing_in_millimeters_remembers_the_unit(self):
        design_id = self.add_design("Measured original", (18.0, 18.0, 14.0))
        self.client.post(
            f"/designs/{design_id}/edit",
            data=self.edit_form(dimension_unit="mm", length_in="254",
                                width_in="127", height_in="63.5"),
            follow_redirects=True,
        )
        design = self.stored("Renamed bracket")
        self.assertEqual(design["dimension_unit"], "mm")
        self.assertEqual(
            (design["length_in"], design["width_in"], design["height_in"]),
            (10.0, 5.0, 2.5),
        )
        page = self.client.get(f"/designs/{design_id}").data.decode()
        self.assertIn("254.0 &times; 127.0 &times; 63.5 mm", page)

    # -- reading -------------------------------------------------------------

    def test_the_design_page_simply_omits_the_dimensions_row(self):
        design_id = self.add_design("Unmeasured original")
        page = self.client.get(f"/designs/{design_id}").data.decode()
        self.assertEqual(self.client.get(f"/designs/{design_id}").status_code, 200)
        self.assertNotIn("<dt>Dimensions</dt>", page)
        self.assertNotIn("None", page)

    def test_the_design_page_still_prints_a_measured_box(self):
        design_id = self.add_design("Measured original", (18.0, 18.0, 14.0))
        page = self.client.get(f"/designs/{design_id}").data.decode()
        self.assertIn("<dt>Dimensions</dt>", page)


if __name__ == "__main__":
    unittest.main()
