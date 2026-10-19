import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from academy.catalog import get_course
from academy.progress import completed_lessons, course_progress, dashboard_data, pathway_progress


class AcademyProgressTests(unittest.TestCase):
    def setUp(self):
        import app
        self.app = app
        app.app.testing = True
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "progress.db")
        self.db_patch.start()
        db.init_db()
        self.client = app.app.test_client()
        conn = db.connect()
        self.users = []
        for name in ("learner_a", "learner_b"):
            self.users.append(conn.execute(
                "INSERT INTO users(username,email,password_hash,email_verified_at) "
                "VALUES (?,?,?,datetime('now'))", (name, f"{name}@example.com", "hash")
            ).lastrowid)
        conn.commit()
        conn.close()
        self.course = get_course("onshape", "quick-start-cad-mental-model")
        self.lesson = self.course["lessons"][0]["id"]
        self.path = f"/learn/onshape/{self.course['slug']}/lessons/{self.lesson}"
        self.post_path = self.path + "/completion"

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def sign_in(self, index=0):
        with self.client.session_transaction() as session:
            session["user_id"] = self.users[index]
            session["csrf_token"] = "test-token"

    def submit(self, action="complete", path=None, token="test-token"):
        return self.client.post(path or self.post_path,
                                data={"action": action, "csrf_token": token})

    def rows(self):
        conn = db.connect()
        rows = conn.execute("SELECT * FROM academy_lesson_progress").fetchall()
        conn.close()
        return rows

    def test_public_read_login_and_csrf(self):
        self.assertEqual(self.client.get(self.path).status_code, 200)
        self.assertIn("Sign in to save your progress", self.client.get(self.path).get_data(as_text=True))
        self.assertEqual(self.client.get("/learn/my-progress").status_code, 302)
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-token"
        self.assertEqual(self.submit().status_code, 302)
        self.sign_in()
        self.assertEqual(self.submit(token="wrong").status_code, 400)
        self.assertEqual(len(self.rows()), 0)

    def test_completion_idempotence_reversal_and_isolation(self):
        self.sign_in()
        self.assertEqual(self.submit().status_code, 302)
        self.assertEqual(self.submit().status_code, 302)
        self.assertEqual(len(self.rows()), 1)
        self.assertIn("Lesson complete", self.client.get(self.path).get_data(as_text=True))
        self.sign_in(1)
        self.assertNotIn("✓ Lesson complete", self.client.get(self.path).get_data(as_text=True))
        self.submit("incomplete")
        self.assertEqual(len(self.rows()), 1)
        self.sign_in()
        self.submit("incomplete")
        self.submit("incomplete")
        self.assertEqual(len(self.rows()), 0)

    def test_invalid_and_planned_content(self):
        self.sign_in()
        for path in (
            self.post_path.replace("/onshape/", "/other/"),
            self.post_path.replace(self.course["slug"], "missing"),
            self.post_path.replace(self.lesson, "missing"),
            self.post_path.replace(self.course["slug"], "robot-integration-strategy"),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.submit(path=path).status_code, 404)
        self.assertEqual(self.submit(action="other").status_code, 400)
        self.assertEqual(len(self.rows()), 0)

    def test_platform_totals_resume_review_and_private_dashboard(self):
        self.sign_in()
        self.submit()
        conn = db.connect()
        completed = completed_lessons(conn, self.users[0])
        state = course_progress("onshape", self.course, completed)
        self.assertEqual((state["completed"], state["total"]), (1, 6))
        self.assertEqual(state["percentage"], 17)
        self.assertEqual(state["first_incomplete"]["id"], self.course["lessons"][1]["id"])
        self.assertEqual(course_progress("fusion-360", get_course("fusion-360", self.course["slug"]), completed)["completed"], 0)
        self.assertEqual(pathway_progress("onshape", completed)["total"], 32)
        self.assertEqual(dashboard_data(completed)["completed"], 1)
        for lesson in self.course["lessons"][1:]:
            conn.execute("INSERT INTO academy_lesson_progress(user_id,platform,course_slug,lesson_id) VALUES (?,?,?,?)",
                         (self.users[0], "onshape", self.course["slug"], lesson["id"]))
        conn.commit()
        complete_state = course_progress("onshape", self.course, completed_lessons(conn, self.users[0]))
        self.assertTrue(complete_state["complete"])
        self.assertEqual(complete_state["action"], "Review course")
        self.assertIsNone(complete_state["first_incomplete"])
        conn.close()
        self.assertIn("My Learning", self.client.get("/learn/my-progress").get_data(as_text=True))
        self.sign_in(1)
        self.assertIn("0 of 64 lessons complete", self.client.get("/learn/my-progress").get_data(as_text=True))

    def test_stale_rows_cascade_and_runtime_migration(self):
        conn = db.connect()
        conn.execute("INSERT INTO academy_lesson_progress(user_id,platform,course_slug,lesson_id) VALUES (?,?,?,?)",
                     (self.users[0], "onshape", self.course["slug"], "removed-lesson"))
        conn.execute("INSERT INTO academy_lesson_progress(user_id,platform,course_slug,lesson_id) VALUES (?,?,?,?)",
                     (self.users[0], "onshape", "robot-integration-strategy", "removed-lesson"))
        conn.commit()
        self.assertEqual(completed_lessons(conn, self.users[0]), {})
        conn.execute("DELETE FROM users WHERE id=?", (self.users[0],))
        conn.commit()
        self.assertEqual(conn.execute("SELECT COUNT(*) n FROM academy_lesson_progress").fetchone()["n"], 0)
        conn.execute("DROP TABLE academy_lesson_progress")
        conn.execute("DELETE FROM schema_migrations WHERE version=8")
        conn.commit()
        self.app._ensure_runtime_schema(conn)
        conn.commit()
        self.assertIsNotNone(conn.execute("SELECT 1 FROM schema_migrations WHERE version=8").fetchone())
        self.assertIsNotNone(conn.execute("SELECT id FROM users WHERE id=?", (self.users[1],)).fetchone())
        conn.close()

    def test_progress_sql_is_portable(self):
        from infra.database import translate
        sql = ("INSERT INTO academy_lesson_progress(user_id,platform,course_slug,lesson_id) "
               "VALUES (?,?,?,?) ON CONFLICT(user_id,platform,course_slug,lesson_id) DO NOTHING")
        translated = translate(sql)
        self.assertIn("ON CONFLICT(user_id,platform,course_slug,lesson_id) DO NOTHING", translated)
        self.assertEqual(translated.count("%s"), 4)
        ddl = translate("CREATE TABLE academy_lesson_progress (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE)")
        self.assertIn("ON DELETE CASCADE", ddl)


if __name__ == "__main__":
    unittest.main()
