"""An owner or admin can tell the viewer which way a model actually faces.

An STL carries no axis convention and an OBJ or GLB carries whichever one its
exporter used, so a design can arrive lying on its side with nothing in the file
to say so. The Front button then shows an end cap, and there is no angle anyone
can drag to that fixes it for the next visitor. The orientation sequence in
static/viewer-orientation.js asks somebody who knows the part to point out its
front and its top, works the other four sides out from those, and posts the
result here.

What is checked on this side is the gate (a correction changes what every later
visitor sees, so it is owner-or-admin, exactly like editing), the rebuilding of
the value (it arrives in a request and is echoed back into a <script> block),
and the two edit paths that already wrote to the same column and would otherwise
undo a correction while saving something unrelated.

The geometry itself is JavaScript and lives in tests/viewer_orbit_harness.mjs.
"""
import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from werkzeug.security import generate_password_hash

import db
# app has to finish importing before the blueprint modules it pulls in can be
# imported by name: routes.designs imports app, and app registers routes.designs
# at the end of its own module body.
import app as _app  # noqa: F401
from routes.designs import clean_viewer_state

# A quarter turn about +X: what a Z-up export needs, and what the sequence
# produces from a front of -Y and a top of +Z.
Z_UP_FIX = [0.7071067811865476, 0.0, 0.0, 0.7071067811865476]


def _png_upload(name="shot.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buffer, format="PNG")
    buffer.seek(0)
    return (buffer, name)


def _preview_data_url():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "green").save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _ascii_stl():
    """One triangle, which is all the upload's content check looks for."""
    return (
        b"solid test\n"
        b"facet normal 0 0 1\n"
        b"  outer loop\n"
        b"    vertex 0 0 0\n"
        b"    vertex 1 0 0\n"
        b"    vertex 0 1 0\n"
        b"  endloop\n"
        b"endfacet\n"
        b"endsolid test\n"
    )


class CleanViewerStateTests(unittest.TestCase):
    """Everything the viewer stores about a design, rebuilt from scratch."""

    def test_a_camera_without_a_correction_is_stored_as_it_always_was(self):
        stored = json.loads(clean_viewer_state(
            '{"position":[1,2,3],"target":[0,0,0]}'))
        self.assertEqual(stored, {"position": [1.0, 2.0, 3.0], "target": [0.0, 0.0, 0.0]})
        # Absent rather than null: a design that never ran the sequence should
        # look exactly like one saved before the sequence existed.
        self.assertNotIn("orientation", stored)

    def test_a_correction_is_kept_alongside_the_camera(self):
        stored = json.loads(clean_viewer_state(json.dumps({
            "position": [1, 2, 3], "target": [0, 0, 0], "orientation": Z_UP_FIX,
        })))
        self.assertEqual(stored["position"], [1.0, 2.0, 3.0])
        for got, want in zip(stored["orientation"], Z_UP_FIX):
            self.assertAlmostEqual(got, want)

    def test_a_correction_is_scaled_back_to_length_one(self):
        stored = json.loads(clean_viewer_state(json.dumps({
            "position": [0, 0, 3], "orientation": [0, 0, 0, 5],
        })))
        self.assertEqual(stored["orientation"], [0.0, 0.0, 0.0, 1.0])

    def test_a_correction_that_is_not_a_rotation_is_dropped(self):
        for bad in ([0, 0, 1], [0, 0, 0, 0], "front", {"w": 1},
                    [None, 0, 0, 1], [True, 0, 0, 1], [1e400, 0, 0, 1]):
            with self.subTest(orientation=bad):
                stored = json.loads(clean_viewer_state(json.dumps({
                    "position": [0, 0, 3], "orientation": bad,
                })))
                self.assertNotIn("orientation", stored)

    def test_a_correction_survives_a_save_that_does_not_mention_it(self):
        # Every path that writes this column predates the orientation, so a page
        # served from a stale cache would otherwise quietly undo a correction
        # while saving a new preview angle.
        existing = json.dumps({"position": [0, 0, 3], "orientation": Z_UP_FIX})
        stored = json.loads(clean_viewer_state(
            '{"position":[9,9,9],"target":[0,0,0]}', existing=existing))
        self.assertEqual(stored["position"], [9.0, 9.0, 9.0])
        self.assertEqual(stored["orientation"], Z_UP_FIX)

    def test_a_submitted_correction_beats_the_stored_one(self):
        existing = json.dumps({"orientation": [0, 0, 0, 1]})
        stored = json.loads(clean_viewer_state(
            json.dumps({"position": [0, 0, 3], "orientation": Z_UP_FIX}),
            existing=existing))
        for got, want in zip(stored["orientation"], Z_UP_FIX):
            self.assertAlmostEqual(got, want)

    def test_a_correction_can_be_stored_with_no_camera_at_all(self):
        # This is what a replaced set of photos leaves behind: the preview angle
        # belonged to a cover that is gone, but the mesh nobody touched still
        # faces the way it was told to.
        stored = json.loads(clean_viewer_state(
            None, existing=json.dumps({"position": [0, 0, 3], "orientation": Z_UP_FIX})))
        self.assertEqual(stored, {"orientation": Z_UP_FIX})

    def test_nothing_worth_keeping_is_stored_as_nothing(self):
        for raw in (None, "", "not json", "[1,2,3]", '{"position":"over there"}'):
            with self.subTest(raw=raw):
                self.assertIsNone(clean_viewer_state(raw))


class _DesignFixture:
    """A viewable design, its owner, an admin, and a stranger."""

    def setUp(self):
        import app as application

        self.application = application
        application.app.testing = True
        # The endpoint shares the design-edit bucket, and each test starts on a
        # fresh database where the owner is again user 1.
        application.ratelimit._buckets.clear()

        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            db, "DB_PATH", Path(self.temp.name) / "orientation.db"
        )
        self.db_patch.start()
        db.init_db()

        # Local object storage points at a scratch dir so nothing is written
        # into the repo's static/uploads.
        self.storage = application.infra_storage
        self.uploads = Path(self.temp.name) / "uploads"
        self.models = Path(self.temp.name) / "models"
        self.uploads.mkdir()
        self.models.mkdir()
        self._orig_dirs = dict(self.storage._LOCAL_DIRS)
        self.storage.configure(self.uploads, self.models)

        self.owner_id = self._make_user("orient_owner")
        self.other_id = self._make_user("orient_stranger")
        self.admin_id = self._make_user("orient_admin", is_admin=1)

        self.design_id = self._make_design("robot.stl")
        self.step_id = self._make_design("part.step")

        self.client = application.app.test_client()
        self._sign_in(self.owner_id)

    def tearDown(self):
        self.storage.configure(self._orig_dirs["uploads"], self._orig_dirs["models"])
        self.db_patch.stop()
        self.temp.cleanup()

    def _make_user(self, username, is_admin=0):
        conn = db.connect()
        user_id = conn.execute(
            """INSERT INTO users(username,email,password_hash,onboarding_complete,
                       email_verified_at,acknowledged_legal_version,is_admin)
                 VALUES (?,?,?,1,datetime('now'),?,?)""",
            (username, f"{username}@example.com",
             generate_password_hash("correct horse", method="pbkdf2:sha256:1"),
             self.application.LEGAL_NOTICE_VERSION, is_admin),
        ).lastrowid
        conn.commit()
        conn.close()
        return user_id

    def _make_design(self, model_filename):
        conn = db.connect()
        design_id = conn.execute(
            """INSERT INTO designs(user_id,program,title,description,cad_software,cad_link,
                       competition_tested,prototype_version,image_filename,model_filename,
                       model_size_bytes,camera_json,storage_bytes)
                 VALUES (?,'ftc','Robot','A design.','onshape',
                         'https://cad.onshape.com/documents/example',1,1,
                         'cover.jpg',?,1000,NULL,1000)""",
            (self.owner_id, model_filename),
        ).lastrowid
        conn.execute(
            "INSERT INTO design_images(design_id,filename,position) VALUES (?,'cover.jpg',0)",
            (design_id,),
        )
        conn.commit()
        conn.close()
        return design_id

    def _sign_in(self, user_id):
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["csrf_token"] = "test-csrf"

    def _post(self, design_id, payload, csrf="test-csrf"):
        headers = {"X-CSRF-Token": csrf} if csrf else {}
        return self.client.post(
            f"/designs/{design_id}/orientation",
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers,
        )

    def _stored(self, design_id):
        conn = db.connect()
        row = conn.execute(
            "SELECT camera_json FROM designs WHERE id=?", (design_id,)
        ).fetchone()
        conn.close()
        return json.loads(row["camera_json"]) if row["camera_json"] else None


class DesignOrientationRouteTests(_DesignFixture, unittest.TestCase):
    def test_the_owner_can_set_which_way_the_model_faces(self):
        response = self._post(self.design_id, {
            "position": [0, 0, 3], "target": [0, 0, 0], "orientation": Z_UP_FIX,
        })
        self.assertEqual(response.status_code, 200)
        stored = self._stored(self.design_id)
        self.assertEqual(stored["position"], [0.0, 0.0, 3.0])
        for got, want in zip(stored["orientation"], Z_UP_FIX):
            self.assertAlmostEqual(got, want)

    def test_an_admin_can_fix_somebody_elses_design(self):
        self._sign_in(self.admin_id)
        response = self._post(self.design_id, {
            "position": [0, 0, 3], "orientation": Z_UP_FIX,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("orientation", self._stored(self.design_id))

    def test_a_stranger_cannot_change_what_everyone_else_sees(self):
        self._sign_in(self.other_id)
        response = self._post(self.design_id, {
            "position": [0, 0, 3], "orientation": Z_UP_FIX,
        })
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self._stored(self.design_id))

    def test_a_signed_out_visitor_is_sent_to_sign_in(self):
        with self.client.session_transaction() as session:
            session.clear()
            session["csrf_token"] = "test-csrf"
        response = self._post(self.design_id, {"orientation": Z_UP_FIX})
        self.assertIn(response.status_code, (302, 401, 403))
        self.assertIsNone(self._stored(self.design_id))

    def test_a_post_without_the_csrf_token_is_refused(self):
        response = self._post(self.design_id, {"orientation": Z_UP_FIX}, csrf=None)
        self.assertGreaterEqual(response.status_code, 400)
        self.assertIsNone(self._stored(self.design_id))

    def test_a_design_with_no_viewable_model_has_nothing_to_orient(self):
        response = self._post(self.step_id, {"orientation": Z_UP_FIX})
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self._stored(self.step_id))

    def test_a_correction_can_be_taken_back_off(self):
        # The sequence's undo. This one write has to be able to clear the
        # column, which is why it does not merge with what is already stored.
        self._post(self.design_id, {"position": [0, 0, 3], "orientation": Z_UP_FIX})
        response = self._post(self.design_id, {"position": [2.2, 1.6, 2.2]})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("orientation", self._stored(self.design_id))

    def test_a_correction_that_is_not_a_rotation_is_not_stored(self):
        response = self._post(self.design_id, {
            "position": [0, 0, 3], "orientation": ["north", 0, 0, 1],
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("orientation", self._stored(self.design_id))

    def test_a_body_that_is_not_an_object_is_refused(self):
        for payload in ([1, 2, 3], "front", 7):
            with self.subTest(payload=payload):
                response = self._post(self.design_id, payload)
                self.assertEqual(response.status_code, 400)

    def test_the_button_is_offered_to_the_owner_and_not_to_a_visitor(self):
        page = self.client.get(f"/designs/{self.design_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'id="viewer-orient-start"', page.data)
        self.assertIn(b"Reset viewer sequence", page.data)

        self._sign_in(self.other_id)
        page = self.client.get(f"/designs/{self.design_id}")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b'id="viewer-orient-start"', page.data)

    def test_every_face_the_sequence_derives_has_a_button(self):
        # Four of the six are never set by hand. If the pages do not offer them
        # there is no way to see that pointing out two faces fixed the rest.
        page = self.client.get(f"/designs/{self.design_id}")
        for face in ("front", "back", "left", "right", "top", "bottom"):
            with self.subTest(face=face):
                self.assertIn(f'data-view="{face}"'.encode(), page.data)


class OrientationSurvivesEditingTests(_DesignFixture, unittest.TestCase):
    """The edit form writes the same column and must not undo a correction."""

    def setUp(self):
        super().setUp()
        self._post(self.design_id, {
            "position": [1, 2, 3], "target": [0, 0, 0], "orientation": Z_UP_FIX,
        })

    def _edit(self, **overrides):
        data = {
            "csrf_token": "test-csrf",
            "full_mode": "1",
            "title": "Robot",
            "description": "A design.",
            "program": "ftc",
            "cad_software": "onshape",
            "cad_link": "https://cad.onshape.com/documents/example",
            "season_id": "",
            "archetype_id": "",
            "competition_tested": "1",
            "prototype_version": "1",
        }
        data.update(overrides)
        return self.client.post(
            f"/designs/{self.design_id}/edit", data=data,
            content_type="multipart/form-data",
        )

    def test_a_recapture_from_a_page_that_predates_the_sequence_keeps_it(self):
        response = self._edit(
            preview_data_url=_preview_data_url(),
            camera_json='{"position":[9,9,9],"target":[0,0,0]}',
        )
        self.assertEqual(response.status_code, 302)
        stored = self._stored(self.design_id)
        self.assertEqual(stored["position"], [9.0, 9.0, 9.0])
        self.assertEqual(stored["orientation"], Z_UP_FIX)

    def test_replacing_the_photos_drops_the_preview_angle_but_not_the_correction(self):
        # New photos say nothing about the mesh's axes; the angle they were
        # framed at belongs to a cover that is gone.
        response = self._edit(image_files=_png_upload())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._stored(self.design_id), {"orientation": Z_UP_FIX})

    def test_replacing_the_model_clears_the_correction_with_the_camera(self):
        # A correction names two faces of one particular mesh. Carried onto a
        # different file it would confidently point at the wrong ones, and
        # nothing on the page would suggest it was wrong.
        response = self._edit(model_file=(io.BytesIO(_ascii_stl()), "robot.stl"))
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self._stored(self.design_id))


if __name__ == "__main__":
    unittest.main()
