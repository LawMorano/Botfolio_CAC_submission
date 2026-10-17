import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from academy.catalog import CATALOG, PATHWAYS, get_course, validate_catalog


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

    def test_landing_navigation_and_pages_are_public(self):
        response = self.client.get("/learn")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Onshape", html)
        self.assertIn("Fusion 360", html)
        self.assertIn('href="/learn"', html)
        self.assertIn("Robot Integration and Strategy", html)
        self.assertNotIn("Sign in to", html)

        for platform in PATHWAYS:
            course = get_course(platform, "quick-start-cad-mental-model")
            lesson_url = f"/learn/{platform}/{course['slug']}/lessons/{course['lessons'][0]['id']}"
            self.assertEqual(self.client.get(lesson_url).status_code, 200)

        conn = db.connect()
        user_id = conn.execute(
            "INSERT INTO users(username,email,password_hash,onboarding_complete,email_verified_at) "
            "VALUES ('learner','learner@example.com','hash',0,datetime('now'))"
        ).lastrowid
        conn.commit()
        conn.close()
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
        self.assertEqual(self.client.get("/learn/onshape").status_code, 200)
        self.assertEqual(
            self.client.get("/learn/onshape/quick-start-cad-mental-model/lessons/parametric-thinking").status_code,
            200,
        )

    def test_expected_course_statuses_and_invalid_paths(self):
        planned = {
            "parts-components-ftc-libraries", "assemblies-and-motion",
            "robot-integration-strategy",
        }
        for platform in PATHWAYS:
            with self.subTest(platform=platform):
                response = self.client.get(f"/learn/{platform}")
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                for slug in ("quick-start-cad-mental-model", "sketching-and-parameters", "parallel-plate-drivetrain"):
                    self.assertEqual(get_course(platform, slug)["status"], "Live")
                    self.assertIn(f'href="/learn/{platform}/{slug}"', html)
                    self.assertEqual(self.client.get(f"/learn/{platform}/{slug}").status_code, 200)
                for slug in planned:
                    self.assertEqual(get_course(platform, slug)["status"], "Planned")
                    self.assertNotIn(f'href="/learn/{platform}/{slug}"', html)
                    self.assertEqual(self.client.get(f"/learn/{platform}/{slug}").status_code, 404)
                    self.assertEqual(self.client.get(f"/learn/{platform}/{slug}/lessons/anything").status_code, 404)
                self.assertEqual(self.client.get(f"/learn/{platform}/unknown").status_code, 404)
                self.assertEqual(self.client.get(f"/learn/{platform}/parallel-plate-drivetrain/lessons/unknown").status_code, 404)
        self.assertEqual(self.client.get("/learn/solidworks").status_code, 404)
        self.assertEqual(self.client.get("/learn/solidworks/course/lessons/lesson").status_code, 404)

    def test_every_live_course_has_lessons_and_working_routes(self):
        for platform, courses in CATALOG.items():
            for course in courses:
                if course["status"] != "Live":
                    continue
                self.assertTrue(course["lessons"])
                overview = self.client.get(f"/learn/{platform}/{course['slug']}")
                self.assertEqual(overview.status_code, 200)
                overview_html = overview.get_data(as_text=True)
                for lesson in course["lessons"]:
                    url = f"/learn/{platform}/{course['slug']}/lessons/{lesson['id']}"
                    self.assertIn(f'href="{url}"', overview_html)
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_previous_next_and_course_navigation(self):
        for platform, courses in CATALOG.items():
            for course in (item for item in courses if item["status"] == "Live"):
                lessons = course["lessons"]
                for index, lesson in enumerate(lessons):
                    response = self.client.get(
                        f"/learn/{platform}/{course['slug']}/lessons/{lesson['id']}"
                    )
                    html = response.get_data(as_text=True)
                    self.assertIn(f'href="/learn/{platform}/{course["slug"]}"', html)
                    if index:
                        previous = lessons[index - 1]
                        self.assertIn(f'/lessons/{previous["id"]}', html)
                        self.assertIn("Previous lesson", html)
                    else:
                        self.assertNotIn("Previous lesson", html)
                    if index + 1 < len(lessons):
                        following = lessons[index + 1]
                        self.assertIn(f'/lessons/{following["id"]}', html)
                        self.assertIn("Next lesson", html)
                    else:
                        self.assertNotIn("Next lesson", html)

    def test_platform_switchers_and_terminology(self):
        terms = {
            "onshape": ("Part Studio", "Fusion 360 edition", "user parameters"),
            "fusion-360": ("user parameters", "Onshape edition", "Part Studio"),
        }
        for platform, courses in CATALOG.items():
            other = PATHWAYS[platform]["other"]
            own_term, switch_label, foreign_term = terms[platform]
            for course in (item for item in courses if item["status"] == "Live"):
                other_course = get_course(other, course["equivalent_slug"])
                self.assertEqual(course["outcome"], other_course["outcome"])
                self.assertEqual(course["challenge"], other_course["challenge"])
                self.assertEqual(course["rubric"], other_course["rubric"])
                overview = self.client.get(f"/learn/{platform}/{course['slug']}").get_data(as_text=True)
                self.assertIn(f'href="/learn/{other}/{other_course["slug"]}"', overview)
                for lesson in course["lessons"]:
                    html = self.client.get(
                        f"/learn/{platform}/{course['slug']}/lessons/{lesson['id']}"
                    ).get_data(as_text=True)
                    self.assertIn('/static/academy.css', html)
                    self.assertIn(switch_label, html)
                    self.assertIn(
                        f'/learn/{other}/{other_course["slug"]}/lessons/{lesson["id"]}', html
                    )
                combined = " ".join(
                    str({key: value for key, value in lesson.items()
                         if key not in {"title", "summary"}})
                    for lesson in course["lessons"]
                )
                self.assertIn(own_term, combined)
                self.assertNotIn(foreign_term, combined)

    def test_sketching_course_alignment_depth_and_self_checks(self):
        editions = [get_course(platform, "sketching-and-parameters") for platform in PATHWAYS]
        expected_ids = (
            "intent-planes-origin", "construction-references", "geometric-constraints",
            "dimensions-fully-defined", "symmetry-patterns", "parameters-expressions",
            "diagnose-repair-adapt",
        )
        for course in editions:
            self.assertEqual(course["status"], "Live")
            self.assertGreaterEqual(course["duration_minutes"], 100)
            self.assertLessEqual(course["duration_minutes"], 120)
            self.assertEqual(tuple(lesson["id"] for lesson in course["lessons"]), expected_ids)
            for lesson in course["lessons"]:
                self.assertGreaterEqual(len(lesson["steps"]), 5)
                self.assertGreaterEqual(len(lesson["checkpoints"]), 2)
                self.assertGreaterEqual(len(lesson["common_mistakes"]), 2)
                self.assertTrue(lesson["practice"])
                self.assertTrue(lesson["completion_checklist"])
                self.assertTrue(lesson["self_check"])
                response = self.client.get(
                    f"/learn/{course['platform']}/{course['slug']}/lessons/{lesson['id']}"
                )
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn("<details>", html)
                self.assertIn("Self-check", html)
        self.assertEqual(editions[0]["outcome"], editions[1]["outcome"])
        self.assertEqual(editions[0]["challenge"], editions[1]["challenge"])
        self.assertEqual(
            tuple(lesson["outcome"] for lesson in editions[0]["lessons"]),
            tuple(lesson["outcome"] for lesson in editions[1]["lessons"]),
        )

    def test_foundation_course_relationships_and_diagrams(self):
        for platform in PATHWAYS:
            quick = get_course(platform, "quick-start-cad-mental-model")
            sketching = get_course(platform, "sketching-and-parameters")
            drivetrain = get_course(platform, "parallel-plate-drivetrain")
            self.assertIn("sketching-and-parameters", quick["related"])
            self.assertEqual(
                sketching["related"],
                ("quick-start-cad-mental-model", "parts-components-ftc-libraries"),
            )
            self.assertIn("Quick Start and CAD Mental Model", drivetrain["prerequisites"])
            self.assertIn("Sketching and Parameters/Variables", drivetrain["prerequisites"])
            quick_html = self.client.get(f"/learn/{platform}/{quick['slug']}").get_data(as_text=True)
            self.assertIn(f'href="/learn/{platform}/sketching-and-parameters"', quick_html)
            sketch_html = self.client.get(f"/learn/{platform}/{sketching['slug']}").get_data(as_text=True)
            self.assertNotIn(f'href="/learn/{platform}/parts-components-ftc-libraries"', sketch_html)
            lesson_html = self.client.get(
                f"/learn/{platform}/sketching-and-parameters/lessons/dimensions-fully-defined"
            ).get_data(as_text=True)
            self.assertIn("/static/images/academy/under-vs-fully-constrained.svg", lesson_html)
            self.assertIn("alt=", lesson_html)

    def test_quick_start_scope_and_drivetrain_depth(self):
        for platform in PATHWAYS:
            quick = get_course(platform, "quick-start-cad-mental-model")
            self.assertGreaterEqual(quick["duration_minutes"], 75)
            self.assertLessEqual(quick["duration_minutes"], 100)
            self.assertEqual(len(quick["lessons"]), 6)
            drivetrain = get_course(platform, "parallel-plate-drivetrain")
            self.assertEqual(len(drivetrain["lessons"]), 5)
            self.assertTrue(all(len(lesson["steps"]) >= 5 for lesson in drivetrain["lessons"]))
            required_specs = set(drivetrain["reference_specifications"])
            self.assertIn("Wheel diameter and width", required_specs)
            self.assertIn("Maximum drivetrain envelope", required_specs)

    def test_search_and_sitemap_include_live_course_overviews_only(self):
        response = self.client.get("/search?q=drivetrain")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Parallel-Plate Drivetrain", html)
        self.assertIn('/learn/onshape/parallel-plate-drivetrain', html)

        sitemap = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("/learn/onshape/quick-start-cad-mental-model", sitemap)
        self.assertIn("/learn/onshape/sketching-and-parameters", sitemap)
        self.assertIn("/learn/onshape/parallel-plate-drivetrain", sitemap)
        self.assertNotIn("/learn/onshape/parts-components-ftc-libraries", sitemap)
        self.assertNotIn("/lessons/", sitemap)

        search = self.client.get("/search?q=sketching").get_data(as_text=True)
        self.assertIn("Sketching and Parameters/Variables", search)
        self.assertIn("/learn/onshape/sketching-and-parameters", search)

    def test_validation_rejects_incomplete_course_lesson_and_step_data(self):
        def copy_catalog():
            return {platform: [copy.deepcopy(course) for course in courses]
                    for platform, courses in CATALOG.items()}

        mutations = (
            lambda data: data["onshape"].append(copy.deepcopy(data["onshape"][0])),
            lambda data: data.update({"unsupported": []}),
            lambda data: data["onshape"][0].pop("summary"),
            lambda data: data["onshape"][0].update(duration_minutes=-1),
            lambda data: data["onshape"][0].update(status="Maybe"),
            lambda data: data["onshape"][0].update(lessons=()),
            lambda data: data["onshape"][0]["lessons"][0].update(id=""),
            lambda data: data["onshape"][0]["lessons"][1].update(id=data["onshape"][0]["lessons"][0]["id"]),
            lambda data: data["onshape"][0]["lessons"][0].update(title=""),
            lambda data: data["onshape"][0]["lessons"][0].update(outcome=""),
            lambda data: data["onshape"][0]["lessons"][0].update(estimated_minutes=0),
            lambda data: data["onshape"][0]["lessons"][0].update(steps=()),
            lambda data: data["onshape"][0]["lessons"][0]["steps"][0].update(action=""),
            lambda data: data["onshape"][0]["lessons"][0]["steps"][0].update(reason=""),
            lambda data: data["onshape"][0]["lessons"][0]["steps"][0].update(result=""),
            lambda data: data["onshape"][0]["lessons"][0].update(checkpoints=()),
            lambda data: data["onshape"][1]["lessons"][0].update(common_mistakes=()),
            lambda data: data["onshape"][1]["lessons"][0].update(self_check=()),
            lambda data: data["onshape"][1]["lessons"][0].update(self_check=({"question": "", "answer": "answer"},)),
            lambda data: data["onshape"][1]["lessons"][0].update(self_check=({"question": "Question?"},)),
            lambda data: data["fusion-360"][0].update(equivalent_slug="missing"),
            lambda data: data["fusion-360"][0].update(lessons=(
                {**data["fusion-360"][0]["lessons"][0], "id": "different"},
                *data["fusion-360"][0]["lessons"][1:],
            )),
            lambda data: data["fusion-360"][0]["lessons"][0]["steps"][0].update(action="Open a Part Studio"),
        )
        for mutate in mutations:
            data = copy_catalog()
            mutate(data)
            with self.subTest(mutation=mutate):
                with self.assertRaises(ValueError):
                    validate_catalog(data)


if __name__ == "__main__":
    unittest.main()
