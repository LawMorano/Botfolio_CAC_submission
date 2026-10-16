"""Accepting STEP files alongside the mesh formats.

STEP is what teams actually hand each other in CAD: real solids that reopen as
editable geometry, rather than the frozen triangle soup an STL export is.
Nothing in the browser can tessellate a boundary representation without an
OpenCascade kernel, so a STEP upload is stored, listed, and downloaded like any
other model while the viewer stays out of its way — the download-only path a
model over 500 MB already takes, given a reason of its own.
"""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Response
from werkzeug.datastructures import FileStorage
from werkzeug.security import generate_password_hash

import db

# A minimal but structurally real ISO 10303-21 part file.
STEP_BYTES = (
    b"ISO-10303-21;\n"
    b"HEADER;\n"
    b"FILE_DESCRIPTION((''),'2;1');\n"
    b"FILE_NAME('intake.step','2026-08-20T09:00:00',(''),(''),'','','');\n"
    b"FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 -1 1 5 4 }'));\n"
    b"ENDSEC;\n"
    b"DATA;\n"
    b"#1=CARTESIAN_POINT('',(0.,0.,0.));\n"
    b"ENDSEC;\n"
    b"END-ISO-10303-21;\n"
)


class StepValidationTests(unittest.TestCase):
    """The header check that decides whether a .step upload is really STEP."""

    def setUp(self):
        import app as application
        self.application = application

    def test_step_and_stp_are_accepted_uploads(self):
        self.assertIn(".step", self.application.MODEL_EXTENSIONS)
        self.assertIn(".stp", self.application.MODEL_EXTENSIONS)

    def test_step_is_never_offered_to_the_browser_viewer(self):
        # The viewer has no CAD kernel, so STEP is an upload format only.
        self.assertNotIn(".step", self.application.VIEWABLE_MODEL_EXTENSIONS)
        self.assertNotIn(".stp", self.application.VIEWABLE_MODEL_EXTENSIONS)
        self.assertEqual(self.application.VIEWABLE_MODEL_EXTENSIONS,
                         {".stl", ".obj", ".glb"})

    def test_accepts_a_structured_step_file(self):
        for extension in (".step", ".stp"):
            with self.subTest(extension=extension):
                self.assertTrue(self.application.valid_model_content(
                    extension, STEP_BYTES, len(STEP_BYTES)))

    def test_accepts_a_step_file_written_with_a_byte_order_mark(self):
        payload = b"\xef\xbb\xbf" + STEP_BYTES
        self.assertTrue(self.application.valid_model_content(
            ".step", payload, len(payload)))

    def test_accepts_a_step_file_that_spaces_out_its_tokens(self):
        # Part 21 lets whitespace sit before a terminating semicolon, and some
        # exporters use it. The tag still has to be the first thing in the file.
        payload = b"ISO-10303-21 ;\nHEADER ;\nFILE_SCHEMA(('AP214'));\nENDSEC;\n"
        self.assertTrue(self.application.valid_model_content(
            ".step", payload, len(payload)))

    def test_rejects_an_executable_renamed_as_step(self):
        self.assertFalse(self.application.valid_model_content(
            ".step", b"MZ\x00\x00program", 12))

    def test_rejects_a_mesh_renamed_as_step(self):
        # An STL is a valid model, but it is not a valid STEP file.
        payload = b"solid part\nfacet normal 0 0 1\nendsolid part\n"
        self.assertFalse(self.application.valid_model_content(
            ".step", payload, len(payload)))

    def test_rejects_a_step_file_missing_its_header_section(self):
        payload = b"ISO-10303-21;\nDATA;\n#1=CARTESIAN_POINT('',(0.,0.,0.));\n"
        self.assertFalse(self.application.valid_model_content(
            ".step", payload, len(payload)))

    def test_unknown_formats_are_still_refused_by_name(self):
        upload = FileStorage(io.BytesIO(b"whatever"), filename="robot.f3d")
        with self.assertRaises(ValueError) as raised:
            self.application.save_model_upload(upload)
        self.assertIn(".step", str(raised.exception))

    def test_a_saved_step_upload_keeps_its_extension(self):
        upload = FileStorage(io.BytesIO(STEP_BYTES), filename="intake.STEP")
        with patch.object(self.application.infra_storage, "save") as save:
            filename, size, digest = self.application.save_model_upload(upload)
        self.assertTrue(filename.endswith(".step"), filename)
        self.assertEqual(size, len(STEP_BYTES))
        self.assertEqual(len(digest), 64)
        save.assert_called_once_with("models", filename, STEP_BYTES)

    def test_viewability_gates_on_both_format_and_size(self):
        viewable = self.application.model_is_viewable
        self.assertTrue(viewable("robot.stl", 1_000))
        self.assertTrue(viewable("robot.glb", None))
        self.assertFalse(viewable("robot.stl", 600_000_000))
        self.assertFalse(viewable("robot.step", 1_000))
        self.assertFalse(viewable("robot.stp", None))
        self.assertFalse(viewable(None, None))


class StepDesignPageTests(unittest.TestCase):
    """What the pages do with a design whose model is CAD source."""

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
        self.step_id = self.add_design(conn, "Swerve module", "module.step")
        self.mesh_id = self.add_design(conn, "Intake roller", "roller.stl")
        conn.commit()
        conn.close()

        self.client = self.application.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def add_design(self, conn, title, model_filename):
        return conn.execute(
            "INSERT INTO designs(user_id,title,description,image_filename,"
            "model_filename,model_size_bytes,upload_status) "
            "VALUES (?,?,'Competition part','preview.jpg',?,?,'approved')",
            (self.user_id, title, model_filename, 4_096),
        ).lastrowid

    def test_detail_page_offers_the_download_rather_than_the_viewer(self):
        page = self.client.get(f"/designs/{self.step_id}").data.decode()
        self.assertNotIn("View in 3D", page)
        self.assertIn("Download User-Submitted File", page)
        self.assertIn("STEP", page)

    def test_detail_page_still_offers_the_viewer_for_a_mesh(self):
        page = self.client.get(f"/designs/{self.mesh_id}").data.decode()
        self.assertIn("View in 3D", page)

    def test_gallery_card_badges_a_step_design_as_a_download(self):
        page = self.client.get("/gallery").data.decode()
        title = page.index("<h3>Swerve module")
        card = page[page.rindex('class="card-slot"', 0, title):title]
        self.assertIn("badge--download", card)
        self.assertNotIn("badge--3d", card)

    def test_the_viewer_route_refuses_to_stream_cad_source(self):
        response = self.client.get(f"/designs/{self.step_id}/model")
        self.assertEqual(response.status_code, 415)
        self.assertIn(b"STEP", response.data)

    def test_the_viewer_route_still_streams_a_mesh(self):
        with patch.object(self.application.infra_storage, "send",
                          return_value=Response(b"solid x\nendsolid x\n")):
            response = self.client.get(f"/designs/{self.mesh_id}/model")
        self.assertEqual(response.status_code, 200)

    def test_publishing_a_step_file_stores_it_and_offers_the_download(self):
        """The whole loop: pick a .step, publish, land on a page offering it."""
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-csrf"
        data = {
            "csrf_token": "test-csrf",
            "team_id": "individual",
            "title": "Published swerve",
            "description": "A drivetrain module published as CAD source.",
            "prototype_version": "1",
            "competition_tested": "0",
            "length_in": "1",
            "width_in": "1",
            "height_in": "1",
            "preview_data_url": "data:image/png;base64,test",
            "upload_certification": "accepted",
            "model_file": (io.BytesIO(STEP_BYTES), "swerve.step"),
        }
        with patch.object(self.application, "save_preview_data_url", return_value="preview.jpg"), \
             patch.object(self.application.infra_storage, "save") as save, \
             patch.object(self.application.infra_storage, "size", return_value=len(STEP_BYTES)):
            page = self.client.post("/submit", data=data, follow_redirects=True,
                                    content_type="multipart/form-data")

        self.assertEqual(page.status_code, 200)
        conn = db.connect()
        design = conn.execute(
            "SELECT model_filename,model_size_bytes FROM designs WHERE title='Published swerve'"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(design, page.data.decode()[:400])
        self.assertTrue(design["model_filename"].endswith(".step"), design["model_filename"])
        self.assertEqual(design["model_size_bytes"], len(STEP_BYTES))
        save.assert_any_call("models", design["model_filename"], STEP_BYTES)
        self.assertIn("Download User-Submitted File", page.data.decode())
        self.assertNotIn("View in 3D", page.data.decode())

    def test_the_upload_forms_accept_step_files(self):
        submit = self.client.get("/submit").data.decode()
        self.assertIn(".step", submit)
        self.assertIn(".stp", submit)


if __name__ == "__main__":
    unittest.main()
