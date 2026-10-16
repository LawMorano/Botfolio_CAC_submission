"""The upload form remembers what was typed if the page is reloaded.

Publishing a design is a long form, and until now a stray Ctrl+R emptied it.
The text of the whole thing is under a kilobyte, so it is kept in localStorage;
the model file, the captured preview, and the certification checkbox are all
deliberately left out, for reasons the script itself sets out.

The interesting logic lives in JavaScript, so most of it is exercised by
tests/submit_draft_harness.mjs under node. What is checked here is that the
page is wired to it correctly, and that the never-persist list has not quietly
grown a field it should not have.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import db

ROOT = Path(__file__).resolve().parent.parent
DRAFT_SCRIPT = ROOT / "static" / "submit-draft.js"
HARNESS = Path(__file__).parent / "submit_draft_harness.mjs"


class DraftScriptTests(unittest.TestCase):
    """The script's own promises, read off the source."""

    def setUp(self):
        self.source = DRAFT_SCRIPT.read_text(encoding="utf-8")

    def test_the_secret_and_the_legal_confirmation_are_never_persisted(self):
        # A regression here would put a session token in localStorage, or
        # re-affirm an upload certification on the user's behalf.
        self.assertIn("SKIP_NAMES = new Set(['csrf_token', 'upload_certification'])",
                      self.source)

    def test_files_and_hidden_payloads_are_skipped_by_type(self):
        # preview_data_url, camera_json, and model_upload_token are hidden
        # inputs, so one rule covers all three plus anything hidden added later.
        for skipped in ("'file'", "'hidden'", "'password'"):
            with self.subTest(skipped=skipped):
                self.assertIn(skipped, self.source.split("SKIP_TYPES")[1][:120])

    def test_the_draft_is_capped_well_under_the_storage_quota(self):
        self.assertIn("MAX_DRAFT_CHARS = 256_000", self.source)

    def test_the_notice_admits_the_files_did_not_come_back(self):
        # A restored form looks finished and is not: no browser lets script
        # rebuild a File, so the model and pictures have to be picked again.
        self.assertIn("Add the model and pictures again before publishing.",
                      self.source)

    def test_a_draft_expires(self):
        self.assertIn("MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000", self.source)


class DraftWiringTests(unittest.TestCase):
    """That the submit page actually loads the script, and loads it in order."""

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
        conn.commit()
        conn.close()

        self.client = self.application.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
        self.page = self.client.get("/submit").data.decode()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_the_submit_page_loads_the_draft_script(self):
        self.assertIn("submit-draft.js", self.page)

    def test_the_form_names_its_owner(self):
        # Without this a draft would follow the browser rather than the
        # account, and surface under the next person to sign in here.
        self.assertIn(f'data-draft-owner="{self.user_id}"', self.page)

    def test_the_draft_script_runs_before_the_page_module(self):
        """Order is load-bearing, not cosmetic.

        The module's own start-up calls filterArchetypes() and
        syncCadLinkField(), which re-run over the restored values and heal a
        season that has since been deleted. Restoring afterwards would skip
        that and leave the form in a state the page never checks again.
        """
        self.assertLess(self.page.index("submit-draft.js"),
                        self.page.index('<script type="module">'))

    def test_the_quick_share_form_does_not_load_it(self):
        # It is a short form that already round-trips its values through the
        # server on a failed post, so it has nothing to restore.
        self.assertNotIn("submit-draft.js",
                         self.client.get("/submit/link").data.decode())


NODE_BINARY = os.environ.get("BOTFOLIO_NODE_BINARY") or shutil.which("node")


@unittest.skipUnless(NODE_BINARY, "node is not installed")
class DraftBehaviourTests(unittest.TestCase):
    """Run the JavaScript harness and surface its failures here."""

    def test_the_draft_script_behaves(self):
        result = subprocess.run(
            [NODE_BINARY, str(HARNESS)],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0,
                         f"\n{result.stdout}\n{result.stderr}")
        self.assertIn("passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
