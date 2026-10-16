"""The owner of a design can replace its stored 3D model from the edit page.

Until now the model a design was published with was permanent: the edit form
only offered to *attach* one to a design that had none, and told everyone else
to delete the design and re-publish. This covers the replacement path — the new
file takes over, the storage counters move across rather than adding up, the
superseded file is deleted, and the saved camera angle (measured against the old
geometry, and replayed verbatim by the viewer) is cleared so the new model does
not open off-screen.
"""
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import db


def stl_bytes(triangles=1):
    """A binary STL that passes valid_model_content: 84 + 50 per triangle."""
    payload = b"botfolio test model".ljust(80, b"\0")
    payload += triangles.to_bytes(4, "little")
    payload += (b"\0" * 50) * triangles
    return payload


STEP_BYTES = b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((''),'');\nENDSEC;\n"
OLD_MODEL = stl_bytes(2)
NEW_MODEL = stl_bytes(5)
COVER_BYTES = 1000


class EditDesignModelSwapTests(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        self.storage = application.infra_storage
        application.app.testing = True
        # The edit route is rate limited per user, and every test here starts
        # from a fresh database where the owner is again user 1.
        application.ratelimit._buckets.clear()

        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            db, "DB_PATH", Path(self.temp.name) / "model-swap.db"
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

        self.user_id = self._make_user("swap_owner")
        self.stranger_id = self._make_user("swap_stranger")

        self.storage.save("models", "old-robot.stl", OLD_MODEL)
        self.mesh_id = self._make_design(
            model_filename="old-robot.stl",
            model_size_bytes=len(OLD_MODEL),
            storage_bytes=len(OLD_MODEL) + COVER_BYTES,
            camera_json='{"position": [2.2, 1.6, 2.2], "target": [0.0, 0.0, 0.0]}',
        )
        self._set_user_storage(len(OLD_MODEL) + COVER_BYTES)

        self.client = application.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["csrf_token"] = "test-csrf"

    def tearDown(self):
        self.storage.configure(self._orig_dirs["uploads"], self._orig_dirs["models"])
        self.db_patch.stop()
        self.temp.cleanup()

    # -- fixtures ---------------------------------------------------------

    def _make_user(self, username):
        conn = db.connect()
        user_id = conn.execute(
            """INSERT INTO users(username,email,password_hash,onboarding_complete,
                       email_verified_at,acknowledged_legal_version)
                 VALUES (?,?,?,1,datetime('now'),?)""",
            (
                username,
                f"{username}@example.com",
                generate_password_hash("correct horse", method="pbkdf2:sha256:1"),
                self.application.LEGAL_NOTICE_VERSION,
            ),
        ).lastrowid
        conn.commit()
        conn.close()
        return user_id

    def _set_user_storage(self, total):
        conn = db.connect()
        conn.execute(
            "UPDATE users SET storage_used_bytes=? WHERE id=?", (total, self.user_id)
        )
        conn.commit()
        conn.close()

    def _make_design(self, *, model_filename, model_size_bytes, storage_bytes,
                     camera_json=None, quick=False):
        conn = db.connect()
        design_id = conn.execute(
            """INSERT INTO designs(user_id,program,title,description,cad_software,cad_link,
                       competition_tested,prototype_version,image_filename,model_filename,
                       model_size_bytes,camera_json,storage_bytes)
                 VALUES (?,'ftc','Robot','A design.','onshape',
                         'https://cad.onshape.com/documents/example',1,?,'cover.jpg',?,?,?,?)""",
            (self.user_id, None if quick else 1, model_filename, model_size_bytes,
             camera_json, storage_bytes),
        ).lastrowid
        conn.execute(
            "INSERT INTO design_images(design_id,filename,position) VALUES (?,'cover.jpg',0)",
            (design_id,),
        )
        conn.commit()
        conn.close()
        return design_id

    def _edit(self, design_id, follow=False, **overrides):
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
            f"/designs/{design_id}/edit", data=data, follow_redirects=follow
        )

    def _swap(self, design_id, payload=NEW_MODEL, filename="new-robot.stl",
              follow=False, **extra):
        return self._edit(
            design_id, follow=follow,
            model_file=(io.BytesIO(payload), filename), **extra
        )

    def _design(self, design_id):
        conn = db.connect()
        row = conn.execute(
            "SELECT model_filename,model_size_bytes,model_sha256,camera_json,"
            "storage_bytes,image_filename FROM designs WHERE id=?", (design_id,)
        ).fetchone()
        conn.close()
        return row

    def _user_storage(self):
        conn = db.connect()
        used = conn.execute(
            "SELECT storage_used_bytes FROM users WHERE id=?", (self.user_id,)
        ).fetchone()["storage_used_bytes"]
        conn.close()
        return used

    # -- the form ---------------------------------------------------------

    def test_owner_is_offered_a_replacement_upload(self):
        response = self.client.get(f"/designs/{self.mesh_id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="model_file"', response.data)
        self.assertIn(b'name="model_upload_token"', response.data)
        self.assertIn(b"Choose a replacement model", response.data)

    def test_quick_design_edit_still_offers_no_model_control(self):
        quick_id = self._make_design(
            model_filename=None, model_size_bytes=0, storage_bytes=0, quick=True
        )
        response = self.client.get(f"/designs/{quick_id}/edit")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'name="model_file"', response.data)

    def test_a_stranger_cannot_open_the_edit_form(self):
        other = self.application.app.test_client()
        with other.session_transaction() as session:
            session["user_id"] = self.stranger_id
            session["csrf_token"] = "test-csrf"
        self.assertEqual(other.get(f"/designs/{self.mesh_id}/edit").status_code, 403)

    # -- the swap ---------------------------------------------------------

    def test_swap_stores_the_new_model_and_deletes_the_old_one(self):
        response = self._swap(self.mesh_id)
        self.assertEqual(response.status_code, 302)

        design = self._design(self.mesh_id)
        self.assertNotEqual(design["model_filename"], "old-robot.stl")
        self.assertTrue(design["model_filename"].endswith(".stl"))
        self.assertEqual(design["model_size_bytes"], len(NEW_MODEL))
        self.assertEqual(design["model_sha256"], hashlib.sha256(NEW_MODEL).hexdigest())
        self.assertEqual(
            self.storage.read("models", design["model_filename"]), NEW_MODEL
        )
        with self.assertRaises(FileNotFoundError):
            self.storage.size("models", "old-robot.stl")

    def test_swap_moves_the_storage_accounting_across(self):
        self._swap(self.mesh_id)

        expected = len(NEW_MODEL) + COVER_BYTES
        self.assertEqual(self._design(self.mesh_id)["storage_bytes"], expected)
        self.assertEqual(self._user_storage(), expected)

    def test_swap_floors_the_subtraction_for_an_uncounted_model(self):
        # A seeded demo, or a row from before the storage columns existed,
        # carries a model whose bytes were never added to either counter.
        # Subtracting them would drive both negative.
        conn = db.connect()
        conn.execute("UPDATE designs SET storage_bytes=0 WHERE id=?", (self.mesh_id,))
        conn.commit()
        conn.close()
        self._set_user_storage(0)

        self._swap(self.mesh_id)

        self.assertEqual(self._design(self.mesh_id)["storage_bytes"], len(NEW_MODEL))
        self.assertEqual(self._user_storage(), len(NEW_MODEL))

    def test_swap_clears_the_camera_measured_against_the_old_mesh(self):
        self._swap(self.mesh_id)
        self.assertIsNone(self._design(self.mesh_id)["camera_json"])

    def test_swap_clears_the_camera_even_when_an_angle_is_captured_too(self):
        # The viewer on the edit page is still showing the model being replaced,
        # so an angle captured in the same save is just as stale.
        self._swap(self.mesh_id, camera_json='{"position":[1,2,3],"target":[0,0,0]}')
        self.assertIsNone(self._design(self.mesh_id)["camera_json"])

    def test_swapping_cad_source_for_a_mesh_turns_the_viewer_on(self):
        self.storage.save("models", "part.step", STEP_BYTES)
        step_id = self._make_design(
            model_filename="part.step",
            model_size_bytes=len(STEP_BYTES),
            storage_bytes=len(STEP_BYTES),
        )
        # A STEP file has no in-browser viewer, so there is no angle to re-aim...
        before = self.client.get(f"/designs/{step_id}/edit")
        self.assertNotIn(b'id="load-viewer"', before.data)
        self.assertIn(b'name="model_file"', before.data)

        self.assertEqual(self._swap(step_id).status_code, 302)

        # ...but the mesh that replaced it can be opened and re-aimed.
        after = self.client.get(f"/designs/{step_id}/edit")
        self.assertIn(b'id="load-viewer"', after.data)
        self.assertEqual(self._design(step_id)["model_size_bytes"], len(NEW_MODEL))

    # -- everything left alone --------------------------------------------

    def test_edit_without_a_file_keeps_the_model_and_its_camera(self):
        response = self._edit(self.mesh_id, title="Renamed Robot")
        self.assertEqual(response.status_code, 302)

        design = self._design(self.mesh_id)
        self.assertEqual(design["model_filename"], "old-robot.stl")
        self.assertEqual(design["storage_bytes"], len(OLD_MODEL) + COVER_BYTES)
        self.assertEqual(self._user_storage(), len(OLD_MODEL) + COVER_BYTES)
        self.assertIsNotNone(design["camera_json"])
        self.assertGreater(self.storage.size("models", "old-robot.stl"), 0)

    def test_a_rejected_file_leaves_the_stored_model_in_place(self):
        response = self._swap(
            self.mesh_id, payload=b"this is not a model", filename="notes.txt"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"3D models must be one of", response.data)

        design = self._design(self.mesh_id)
        self.assertEqual(design["model_filename"], "old-robot.stl")
        self.assertEqual(design["model_size_bytes"], len(OLD_MODEL))
        self.assertEqual(design["storage_bytes"], len(OLD_MODEL) + COVER_BYTES)
        self.assertEqual(self._user_storage(), len(OLD_MODEL) + COVER_BYTES)
        self.assertIsNotNone(design["camera_json"])
        self.assertEqual(self.storage.read("models", "old-robot.stl"), OLD_MODEL)

    def test_a_truncated_stl_is_rejected_and_nothing_is_orphaned(self):
        response = self._swap(
            self.mesh_id, payload=stl_bytes(5)[:-10], filename="broken.stl"
        )
        self.assertEqual(response.status_code, 200)

        self.assertEqual(self._design(self.mesh_id)["model_filename"], "old-robot.stl")
        self.assertEqual(
            sorted(p.name for p in self.models.iterdir()), ["old-robot.stl"]
        )


if __name__ == "__main__":
    unittest.main()
