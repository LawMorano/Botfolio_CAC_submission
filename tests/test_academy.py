import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from academy.catalog import CATALOG, OBJECTIVES, RUBRIC, validate_catalog


class AcademyTests(unittest.TestCase):
    def setUp(self):
        import app as application

        self.application = application
        self.application.app.testing = True
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "academy.db")
        self.db_patch.start()
        db.init_db()
        self.client = self.application.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_landing_navigation_and_public_access(self):
        response = self.client.get("/learn")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Onshape", html)
        self.assertIn("Fusion 360", html)
        self.assertIn('href="/learn"', html)
        self.assertIn("Robot Integration and Strategy", html)
        self.assertNotIn("Sign in to", html)

        conn = db.connect()
        user_id = conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete,email_verified_at) "
            "VALUES ('learner','learner@example.com','hash',1,datetime('now'))"
        ).lastrowid
        conn.commit()
        conn.close()
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
        self.assertEqual(self.client.get("/learn/onshape").status_code, 200)
        self.assertEqual(self.client.get("/learn/fusion-360/parallel-plate-drivetrain").status_code, 200)

    def test_pathways_planned_cards_and_invalid_paths(self):
        for platform in ("onshape", "fusion-360"):
            with self.subTest(platform=platform):
                response = self.client.get(f"/learn/{platform}")
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn("Coming next", html)
                self.assertIn("Planned", html)
                self.assertNotIn(f'href="/learn/{platform}/quick-start-cad-mental-model"', html)
                self.assertIn(f'href="/learn/{platform}/parallel-plate-drivetrain"', html)
                self.assertEqual(self.client.get(f"/learn/{platform}/unknown").status_code, 404)
                self.assertEqual(self.client.get(f"/learn/{platform}/quick-start-cad-mental-model").status_code, 404)
        self.assertEqual(self.client.get("/learn/solidworks").status_code, 404)
        self.assertEqual(self.client.get("/learn/solidworks/parallel-plate-drivetrain").status_code, 404)

    def test_course_editions_share_assessment_and_switch(self):
        for platform, other, own_word, foreign_word in (
            ("onshape", "fusion-360", "Part Studio", "user parameters"),
            ("fusion-360", "onshape", "user parameters", "Part Studio"),
        ):
            with self.subTest(platform=platform):
                response = self.client.get(f"/learn/{platform}/parallel-plate-drivetrain")
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn(f'href="/learn/{other}/parallel-plate-drivetrain"', html)
                self.assertIn(own_word, html)
                self.assertNotIn(foreign_word, html)
                for objective in OBJECTIVES:
                    self.assertIn(objective, html)
                for row in RUBRIC:
                    self.assertIn(row["criterion"], html)
                    self.assertIn(row["evidence"], html)
                self.assertIn("Portfolio artifact requirements", html)

    def test_search_and_sitemap(self):
        response = self.client.get("/search?q=academy")
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/learn"', response.get_data(as_text=True))
        sitemap = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("/learn/onshape/parallel-plate-drivetrain", sitemap)
        self.assertNotIn("/learn/onshape/quick-start-cad-mental-model", sitemap)

    def test_validation_rejects_bad_data(self):
        mutations = (
            lambda data: data["onshape"].append(copy.deepcopy(data["onshape"][0])),
            lambda data: data.update({"unsupported": []}),
            lambda data: data["onshape"][0].pop("summary"),
            lambda data: data["onshape"][0].update(duration_minutes=-1),
            lambda data: data["onshape"][0].update(status="Maybe"),
            lambda data: data["onshape"][0].update(difficulty="Unknown"),
            lambda data: data["onshape"][4]["lessons"][0].update(id=""),
            lambda data: data["onshape"][4]["lessons"][0].update(title=""),
        )
        for mutate in mutations:
            data = {platform: [copy.deepcopy(course) for course in courses]
                    for platform, courses in CATALOG.items()}
            mutate(data)
            with self.assertRaises(ValueError):
                validate_catalog(data)


if __name__ == "__main__":
    unittest.main()
