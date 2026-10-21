import copy
import html as html_lib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from academy.catalog import CATALOG, PATHWAYS, get_course, validate_catalog


LIVE_SLUGS = ("quick-start-cad-mental-model", "parallel-plate-drivetrain")
RETIRED_SLUGS = ("sketching-and-parameters", "parts-components-ftc-libraries", "assemblies-and-motion")


class AcademyTests(unittest.TestCase):
    def setUp(self):
        import app
        app.app.testing = True
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "academy.db")
        self.db_patch.start()
        db.init_db()
        self.client = app.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_two_course_catalog_and_public_routes(self):
        self.assertTrue(validate_catalog())
        self.assertIn("two-course roadmap", self.client.get("/learn").get_data(as_text=True))
        sitemap = self.client.get("/sitemap.xml").get_data(as_text=True)
        for platform in PATHWAYS:
            self.assertEqual(tuple(course["slug"] for course in CATALOG[platform]), LIVE_SLUGS)
            roadmap = self.client.get(f"/learn/{platform}").get_data(as_text=True)
            for slug in LIVE_SLUGS:
                self.assertIn(f"/learn/{platform}/{slug}", roadmap)
                self.assertIn(f"/learn/{platform}/{slug}", sitemap)
                self.assertEqual(self.client.get(f"/learn/{platform}/{slug}").status_code, 200)
            for slug in RETIRED_SLUGS:
                self.assertIsNone(get_course(platform, slug))
                self.assertNotIn(slug, roadmap)
                self.assertNotIn(slug, sitemap)
                self.assertEqual(self.client.get(f"/learn/{platform}/{slug}").status_code, 404)

    def test_ordered_plan_and_focused_step_in_both_editions(self):
        for platform in PATHWAYS:
            for course_number, course in enumerate(CATALOG[platform], 1):
                plan = self.client.get(f"/learn/{platform}/{course['slug']}").get_data(as_text=True)
                self.assertIn("Lesson plan", plan)
                for lesson_number, lesson in enumerate(course["lessons"], 1):
                    base = f"/learn/{platform}/{course['slug']}/lessons/{lesson['id']}"
                    self.assertEqual(self.client.get(base).location, base + "/steps/1")
                    self.assertIn(lesson["title"], plan)
                    for step_number, step in enumerate(lesson["steps"], 1):
                        path = base + f"/steps/{step_number}"
                        self.assertIn(f'href="{path}"', plan)
                        html = html_lib.unescape(self.client.get(path).get_data(as_text=True))
                        self.assertIn('/static/academy.css', html)
                        self.assertIn('/static/academy.js', html)
                        label = f"{course_number}.{lesson_number}.{chr(96 + step_number)}"
                        self.assertIn(label, html)
                        self.assertIn(step["action"], html)
                        self.assertIn(step["reason"], html)
                        self.assertIn(step["result"], html)
                        self.assertIn('aria-current="step"', html)
                        self.assertIn("Steps in this lesson", html)
                        if step_number < len(lesson["steps"]):
                            self.assertNotIn(lesson["steps"][step_number]["action"], html)
                            self.assertIn(base + f"/steps/{step_number + 1}", html)
                            self.assertIn("Continue", html)
                        else:
                            self.assertNotIn("Continue →", html)
                            self.assertIn("Sign in to mark lesson complete", html)
                    self.assertEqual(self.client.get(base + "/steps/0").status_code, 404)
                    self.assertEqual(self.client.get(base + f"/steps/{len(lesson['steps']) + 1}").status_code, 404)

    def test_edition_step_switch_and_recommendation(self):
        for platform in PATHWAYS:
            other = PATHWAYS[platform]["other"]
            quick = CATALOG[platform][0]
            lesson = quick["lessons"][0]
            path = f"/learn/{platform}/{quick['slug']}/lessons/{lesson['id']}/steps/2"
            html = self.client.get(path).get_data(as_text=True)
            self.assertIn(f"/learn/{other}/{quick['slug']}/lessons/{lesson['id']}/steps/2", html)
            plan = self.client.get(f"/learn/{platform}/{quick['slug']}").get_data(as_text=True)
            self.assertIn("Parallel-Plate Drivetrain", plan)
            self.assertNotIn("Sketching and Parameters/Variables", plan)

    def test_catalog_validation_rejects_broken_step(self):
        catalog = {platform: copy.deepcopy(courses) for platform, courses in CATALOG.items()}
        catalog["onshape"][0]["lessons"][0]["steps"][0]["action"] = ""
        with self.assertRaises(ValueError):
            validate_catalog(catalog)

    def test_step_media_precedes_instructions_and_missing_media_is_omitted(self):
        for platform in PATHWAYS:
            course = CATALOG[platform][0]
            lesson = course["lessons"][0]
            path = f"/learn/{platform}/{course['slug']}/lessons/{lesson['id']}/steps/1"
            self.assertNotIn('aria-label="Step media"', self.client.get(path).get_data(as_text=True))
            media = ({"path": "images/academy/under-vs-fully-constrained.svg",
                      "alt": "Existing sketch constraint diagram", "caption": "Diagram rendering fixture"},)
            with patch.dict(lesson["steps"][0], {"media": media, "note": "Check dimensions before building."}):
                html = self.client.get(path).get_data(as_text=True)
                self.assertLess(html.index('aria-label="Step media"'), html.index('class="academy__focused-step"'))
                self.assertIn('alt="Existing sketch constraint diagram"', html)
                self.assertIn("Check dimensions before building.", html)


if __name__ == "__main__":
    unittest.main()
