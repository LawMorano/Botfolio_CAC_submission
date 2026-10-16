import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import db
import production_boot
from production_boot import prepare_volume


class ProductionBootTests(unittest.TestCase):
    def test_fresh_volume_initializes_once_and_keeps_existing_rows(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temporary:
            root = Path(temporary)
            app_root = root / "app"
            volume = root / "data"
            volume.mkdir()
            for name in ("uploads", "models"):
                folder = app_root / "static" / name
                folder.mkdir(parents=True)
                (folder / ".gitkeep").touch()

            with patch.dict(os.environ, {"BOTFOLIO_DATA_DIR": str(volume)}, clear=False), \
                    patch.object(db, "DB_PATH", volume / "designhub.db"), \
                    patch.object(production_boot, "_link_empty_image_directory"):
                prepare_volume(volume, app_root)
                self.assertTrue(db.db_is_initialized())
                self.assertTrue((volume / "uploads").is_dir())
                with closing(db.connect()) as connection:
                    connection.execute("CREATE TABLE boot_proof (value TEXT)")
                    connection.execute("INSERT INTO boot_proof VALUES ('preserved')")
                    connection.commit()
                prepare_volume(volume, app_root)
                with closing(db.connect()) as connection:
                    self.assertEqual(connection.execute("SELECT value FROM boot_proof").fetchone()[0], "preserved")

    def test_existing_uninitialized_database_is_never_reset(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temporary:
            root = Path(temporary)
            app_root = root / "app"
            volume = root / "data"
            volume.mkdir()
            database = volume / "designhub.db"
            database.write_bytes(b"existing")
            for name in ("uploads", "models"):
                (app_root / "static" / name).mkdir(parents=True)
            with patch.dict(os.environ, {"BOTFOLIO_DATA_DIR": str(volume)}, clear=False), \
                    patch.object(db, "DB_PATH", database):
                with self.assertRaises(Exception):
                    prepare_volume(volume, app_root)
            self.assertEqual(database.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
