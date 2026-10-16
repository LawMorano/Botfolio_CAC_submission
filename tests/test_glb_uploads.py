import io
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.datastructures import FileStorage


def glb_bytes():
    # A minimal GLB header plus an empty JSON document chunk. The upload guard
    # checks the standard magic, version, and declared total length.
    json_chunk = b"{}  "
    payload = b"glTF" + (2).to_bytes(4, "little")
    payload += (12 + 8 + len(json_chunk)).to_bytes(4, "little")
    payload += len(json_chunk).to_bytes(4, "little") + b"JSON" + json_chunk
    return payload


class GlbUploadTests(unittest.TestCase):
    def setUp(self):
        import app as application
        self.application = application

    def test_glb_is_an_uploadable_and_viewable_format(self):
        self.assertIn(".glb", self.application.MODEL_EXTENSIONS)
        self.assertIn(".glb", self.application.VIEWABLE_MODEL_EXTENSIONS)

    def test_glb_header_is_validated(self):
        payload = glb_bytes()
        self.assertTrue(self.application.valid_model_content(
            ".glb", payload, len(payload)
        ))
        self.assertFalse(self.application.valid_model_content(
            ".glb", b"not a glb", 9
        ))

    def test_saved_glb_keeps_the_material_carrying_extension(self):
        payload = glb_bytes()
        upload = FileStorage(io.BytesIO(payload), filename="colored-robot.GLB")
        with patch.object(self.application.infra_storage, "save") as save:
            filename, size, digest = self.application.save_model_upload(upload)
        self.assertTrue(filename.endswith(".glb"), filename)
        self.assertEqual(size, len(payload))
        self.assertEqual(len(digest), 64)
        save.assert_called_once_with("models", filename, payload)

    def test_viewer_uses_gltf_materials_instead_of_flat_grey(self):
        source = Path("static/viewer.js").read_text(encoding="utf-8")
        self.assertIn("new GLTFLoader().parse", source)
        self.assertIn("this._setModel(gltf.scene)", source)
        self.assertNotIn("gltf.scene.traverse((child) => { child.material", source)


if __name__ == "__main__":
    unittest.main()
