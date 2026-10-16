"""The design edit page can re-orient a stored 3D model and replace the cover.

Covers the "change the 3D view that was set as the picture" feature: an owner
opens the viewer on the edit page, captures a new angle, and submits it as a
data URL. The route stores the new render, swaps designs.image_filename, keeps
the design_images gallery mirror in step, refreshes camera_json, deletes the old
asset, and adjusts storage. A design whose model is not browser-viewable (a STEP
file) offers no such control and ignores a stray preview.
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


def _data_url(color):
    """A tiny, genuinely decodable PNG data URL in the captured-preview shape."""
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class EditDesignRecaptureTests(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        self.storage = application.infra_storage
        application.app.testing = True
        # /designs/<id>/edit is rate limited per user, and each test
        # starts on a fresh database where the owner is again user 1.
        application.ratelimit._buckets.clear()

        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            db, "DB_PATH", Path(self.temp.name) / "recapture.db"
        )
        self.db_patch.start()
        db.init_db()

        # Point local object storage at a scratch dir so the test never writes
        # into the repo's static/uploads, and restore it afterwards.
        self.uploads = Path(self.temp.name) / "uploads"
        self.models = Path(self.temp.name) / "models"
        self.uploads.mkdir()
        self.models.mkdir()
        self._orig_dirs = dict(self.storage._LOCAL_DIRS)
        self.storage.configure(self.uploads, self.models)

        conn = db.connect()
        self.user_id = conn.execute(
            """INSERT INTO users(username,email,password_hash,onboarding_complete,
                       email_verified_at,acknowledged_legal_version)
                 VALUES (?,?,?,1,datetime('now'),?)""",
            (
                "recapture_owner",
                "recapture-owner@example.com",
                generate_password_hash("correct horse", method="pbkdf2:sha256:1"),
                application.LEGAL_NOTICE_VERSION,
            ),
        ).lastrowid
        conn.commit()
        conn.close()

        # A real stored cover so its size can be read and it can be deleted.
        with application.app.app_context():
            self.old_cover = application.save_preview_data_url(_data_url("red"))

        self.viewable_id = self._make_design(
            model_filename="robot.stl",
            model_size_bytes=1000,
            image_filename=self.old_cover,
            camera_json='{"position": [2.2, 1.6, 2.2], "target": [0.0, 0.0, 0.0]}',
        )
        self.step_id = self._make_design(
            model_filename="part.step",
            model_size_bytes=1000,
            image_filename="step-cover.jpg",
            camera_json=None,
        )

        self.client = application.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"

    def tearDown(self):
        self.storage.configure(self._orig_dirs["uploads"], self._orig_dirs["models"])
        self.db_patch.stop()
        self.temp.cleanup()

    def _make_design(self, *, model_filename, model_size_bytes, image_filename, camera_json):
        conn = db.connect()
        design_id = conn.execute(
            """INSERT INTO designs(user_id,program,title,description,cad_software,cad_link,
                       competition_tested,prototype_version,image_filename,model_filename,
                       model_size_bytes,camera_json,storage_bytes)
                 VALUES (?,'ftc','Robot','A design.','onshape',
                         'https://cad.onshape.com/documents/example',1,1,?,?,?,?,?)""",
            (self.user_id, image_filename, model_filename, model_size_bytes,
             camera_json, model_size_bytes),
        ).lastrowid
        conn.execute(
            "INSERT INTO design_images(design_id,filename,position) VALUES (?,?,0)",
            (design_id, image_filename),
        )
        conn.commit()
        conn.close()
        return design_id

    def _edit(self, design_id, **overrides):
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
        return self.client.post(f"/designs/{design_id}/edit", data=data)

    def _design(self, design_id):
        conn = db.connect()
        row = conn.execute(
            "SELECT image_filename,camera_json,storage_bytes FROM designs WHERE id=?",
            (design_id,),
        ).fetchone()
        conn.close()
        return row

    def _cover_mirror(self, design_id):
        conn = db.connect()
        row = conn.execute(
            "SELECT filename FROM design_images WHERE design_id=? AND position=0",
            (design_id,),
        ).fetchone()
        conn.close()
        return row["filename"] if row else None

    def test_form_offers_recapture_for_a_viewable_model(self):
        response = self.client.get(f"/designs/{self.viewable_id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="load-viewer"', response.data)
        self.assertIn(b'name="preview_data_url"', response.data)

    def test_recapture_replaces_cover_and_keeps_gallery_mirror_in_step(self):
        response = self._edit(
            self.viewable_id,
            preview_data_url=_data_url("blue"),
            camera_json='{"position":[1,2,3],"target":[0,0,0]}',
        )
        self.assertEqual(response.status_code, 302)

        design = self._design(self.viewable_id)
        new_cover = design["image_filename"]
        # The cover was swapped for a freshly stored render...
        self.assertNotEqual(new_cover, self.old_cover)
        self.assertTrue(new_cover.endswith(".jpg"))
        self.assertGreater(self.storage.size("uploads", new_cover), 0)
        # ...the gallery mirror points at the same new file...
        self.assertEqual(self._cover_mirror(self.viewable_id), new_cover)
        # ...the replay camera state was refreshed to the new angle...
        self.assertEqual(
            json.loads(design["camera_json"]),
            {"position": [1.0, 2.0, 3.0], "target": [0.0, 0.0, 0.0]},
        )
        # ...and the superseded asset is gone.
        with self.assertRaises(FileNotFoundError):
            self.storage.size("uploads", self.old_cover)

    def test_recapture_survives_a_missing_old_cover(self):
        # A seeded/demo cover only lives in the repo, not the uploads store, so
        # re-reading its size raises (FileNotFoundError on disk, a 404 from S3).
        # That must not crash the save — the storage counter just skips it.
        self.storage.delete("uploads", self.old_cover)
        with self.assertRaises(FileNotFoundError):
            self.storage.size("uploads", self.old_cover)

        response = self._edit(
            self.viewable_id,
            preview_data_url=_data_url("blue"),
            camera_json='{"position":[1,2,3],"target":[0,0,0]}',
        )
        self.assertEqual(response.status_code, 302)

        design = self._design(self.viewable_id)
        self.assertNotEqual(design["image_filename"], self.old_cover)
        self.assertTrue(design["image_filename"].endswith(".jpg"))
        self.assertEqual(
            self._cover_mirror(self.viewable_id), design["image_filename"]
        )
        self.assertGreater(
            self.storage.size("uploads", design["image_filename"]), 0
        )

    def test_edit_without_a_preview_leaves_the_cover_untouched(self):
        response = self._edit(self.viewable_id, title="Renamed Robot")
        self.assertEqual(response.status_code, 302)

        design = self._design(self.viewable_id)
        self.assertEqual(design["image_filename"], self.old_cover)
        self.assertEqual(self._cover_mirror(self.viewable_id), self.old_cover)
        # The original render is still on disk.
        self.assertGreater(self.storage.size("uploads", self.old_cover), 0)

    def test_non_viewable_step_model_has_no_recapture_control(self):
        response = self.client.get(f"/designs/{self.step_id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'id="load-viewer"', response.data)
        self.assertNotIn(b'name="preview_data_url"', response.data)

    def test_non_viewable_step_model_ignores_a_stray_preview(self):
        response = self._edit(self.step_id, preview_data_url=_data_url("green"))
        self.assertEqual(response.status_code, 302)

        design = self._design(self.step_id)
        self.assertEqual(design["image_filename"], "step-cover.jpg")


if __name__ == "__main__":
    unittest.main()
