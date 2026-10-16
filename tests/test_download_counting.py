"""Getting a design's CAD: who may, how often, and what gets counted.

Two rules meet here. The counter must count people rather than requests --
before that, every HEAD probe, resumed transfer, cache revalidation and repeat
click added a row, and a missing file counted a download that served nothing.
And getting the CAD at all now needs an account and fits inside a daily
allowance, whether it arrives as an uploaded file or a link out to the CAD host.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Response
from werkzeug.security import generate_password_hash

import db


class DownloadTestCase(unittest.TestCase):
    """Shared fixture: a temp database, an owner, a plain downloader, an admin."""

    def setUp(self):
        import app as application

        self.application = application
        self.application.app.testing = True
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", Path(self.temp.name) / "test.db")
        self.db_patch.start()
        db.init_db()
        # Counters live in a module-level dict for the life of the process, so
        # without this every test after the first inherits the previous one's
        # hits and eventually gets a 429 that has nothing to do with it.
        self.application.ratelimit._buckets.clear()

        conn = db.connect()
        self.owner_id = self.add_user(conn, "owner", "owner@example.com")
        self.downloader_id = self.add_user(conn, "downloader", "downloader@example.com")
        self.admin_id = self.add_user(conn, "boss", "boss@example.com", is_admin=1)
        self.design_id = self.add_design(conn, model_filename="robot.stl")
        conn.commit()
        conn.close()

        self.client = self.application.app.test_client()
        self.url = f"/designs/{self.design_id}/download"
        # The seeded designs name a model but nothing wrote one to storage, so
        # the transfer itself is stubbed. Tests that care about a failed send
        # patch this with their own side effect.
        self.send_patch = patch.object(
            self.application.infra_storage, "send",
            side_effect=lambda *args, **kwargs: Response(b"solid x\nendsolid x\n"),
        )
        self.send_patch.start()

    def tearDown(self):
        self.send_patch.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    # -- fixture helpers ---------------------------------------------------

    def add_user(self, conn, username, email, is_admin=0, password="correct-horse"):
        # A deliberately cheap hash: the real one is scrypt, and three of these
        # per test turns a fast suite into a slow one for no extra coverage.
        return conn.execute(
            "INSERT INTO users(username,email,password_hash,is_admin,onboarding_complete,"
            "email_verified_at,acknowledged_legal_version) "
            "VALUES (?,?,?,?,1,datetime('now'),?)",
            (username, email, generate_password_hash(password, method="pbkdf2:sha256:1"), is_admin,
             self.application.LEGAL_NOTICE_VERSION),
        ).lastrowid

    def add_design(self, conn, model_filename=None, cad_link=None, onshape_link=None,
                   owner_id=None, title="Intake"):
        return conn.execute(
            "INSERT INTO designs(user_id,title,description,image_filename,model_filename,"
            "cad_link,onshape_link,upload_status) VALUES (?,?,'Competition intake','preview.jpg',?,?,?,'approved')",
            (owner_id or self.owner_id, title, model_filename, cad_link, onshape_link),
        ).lastrowid

    def seed(self, **kwargs):
        conn = db.connect()
        try:
            design_id = self.add_design(conn, **kwargs)
            conn.commit()
            return design_id
        finally:
            conn.close()

    def login(self, user_id):
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["csrf_token"] = "test-csrf"

    def rows(self, design_id=None):
        conn = db.connect()
        try:
            if design_id is None:
                return conn.execute("SELECT * FROM design_downloads ORDER BY id").fetchall()
            return conn.execute(
                "SELECT * FROM design_downloads WHERE design_id=? ORDER BY id", (design_id,)
            ).fetchall()
        finally:
            conn.close()

    def download_count(self, design_id=None):
        return len(self.rows(design_id if design_id is not None else self.design_id))


class DownloadCountingTests(DownloadTestCase):
    """One person deciding to take a design is one row, however many requests."""

    def setUp(self):
        super().setUp()
        self.login(self.downloader_id)

    def test_a_head_request_is_charged_like_any_other(self):
        # HEAD used to be free, which made the allowance bypassable with
        # curl -I: on bucket storage and on the CAD route the whole payload is
        # a header, so HEAD hands over exactly what GET does.
        self.assertEqual(self.client.head(self.url).status_code, 200)
        self.assertEqual(self.download_count(), 1)

    def test_repeated_downloads_by_one_visitor_count_once(self):
        for _ in range(5):
            self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.download_count(), 1)

    def test_downloaded_design_appears_in_the_downloaders_library(self):
        # End-to-end: taking a design through the real download route surfaces it
        # in the downloader's private My Library (the /library page reached from
        # the top-bar account menu).
        self.assertEqual(self.client.get(self.url).status_code, 200)
        page = self.client.get("/library").get_data(as_text=True)
        self.assertIn("Download Library", page)
        self.assertIn('<a href="#downloads">Downloads <span>1</span></a>', page)
        section = page[page.index('id="downloads"'):]
        self.assertIn('href="/designs/%d"' % self.design_id, section)

    def test_a_range_request_counts_because_it_delivers_the_file(self):
        # "Range: bytes=0-" returns the whole file with a 206, so treating 206
        # as "not really a download" handed out every model for free.
        with patch.object(self.application.infra_storage, "send",
                          side_effect=lambda *a, **k: Response(status=206)):
            self.client.get(self.url, headers={"Range": "bytes=0-"})
        self.assertEqual(self.download_count(), 1)

    def test_a_resumed_transfer_is_still_one_download(self):
        # Counting 206 must not turn one interrupted download into several:
        # the one-row-per-person-per-design rule is what prevents that.
        with patch.object(self.application.infra_storage, "send",
                          side_effect=lambda *a, **k: Response(status=206)):
            for chunk in ("bytes=0-3", "bytes=4-7", "bytes=8-"):
                self.client.get(self.url, headers={"Range": chunk})
        self.assertEqual(self.download_count(), 1)

    def test_a_revalidated_response_does_not_count(self):
        # 304 carries no bytes at all: the browser already has the file, from a
        # request that was counted when it happened.
        with patch.object(self.application.infra_storage, "send",
                          side_effect=lambda *a, **k: Response(status=304)):
            self.client.get(self.url, headers={"If-None-Match": "etag"})
        self.assertEqual(self.download_count(), 0)

    def test_missing_stored_file_leaves_no_download_row(self):
        from werkzeug.exceptions import NotFound

        with patch.object(self.application.infra_storage, "send", side_effect=NotFound()):
            self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.download_count(), 0)

    def test_signed_storage_redirect_counts_once(self):
        with patch.object(self.application.infra_storage, "send",
                          side_effect=lambda *a, **k: Response(status=302, headers={"Location": "https://storage.example/robot.stl"})):
            self.assertEqual(self.client.get(self.url).status_code, 302)
            self.client.get(self.url)
        self.assertEqual(self.download_count(), 1)

    def test_separate_accounts_are_counted_separately(self):
        self.client.get(self.url)
        other = self.application.app.test_client()
        with other.session_transaction() as session:
            session["user_id"] = self.admin_id
        other.get(self.url)
        self.assertEqual(self.download_count(), 2)

    def test_download_records_who_downloaded(self):
        self.client.get(self.url)
        row = self.rows(self.design_id)[0]
        self.assertEqual(row["user_id"], self.downloader_id)
        self.assertEqual(row["visitor_key"], f"u:{self.downloader_id}")
        self.assertEqual(row["kind"], "file")

    def test_a_download_outside_the_cooldown_counts_again(self):
        self.client.get(self.url)
        conn = db.connect()
        conn.execute(
            "UPDATE design_downloads SET downloaded_at=datetime('now', ?)",
            (f"-{self.application.DOWNLOAD_COOLDOWN_MINUTES + 1} minutes",),
        )
        conn.commit()
        conn.close()
        self.client.get(self.url)
        self.assertEqual(self.download_count(), 2)

    def test_robots_txt_keeps_crawlers_off_the_ways_out(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        self.assertIn("Disallow: /designs/*/download", body)
        self.assertIn("Disallow: /designs/*/cad", body)
        self.assertIn("Disallow: /designs/*/model", body)

    def test_existing_database_gains_the_new_columns(self):
        conn = db.connect()
        conn.execute("DROP TABLE design_downloads")
        conn.execute("CREATE TABLE design_downloads (id INTEGER PRIMARY KEY AUTOINCREMENT, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, downloaded_at TEXT NOT NULL DEFAULT (datetime('now')))")
        conn.execute("INSERT INTO design_downloads(design_id,user_id) VALUES (?,NULL)", (self.design_id,))
        conn.commit()
        self.application._ensure_runtime_schema(conn)
        conn.commit()
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(design_downloads)")}
        legacy = conn.execute("SELECT visitor_key,kind FROM design_downloads").fetchone()
        conn.close()
        self.assertIn("visitor_key", columns)
        self.assertIn("kind", columns)
        # The pre-existing row keeps its place in the count and simply carries
        # no identity, so it can never suppress a later real download. Nothing
        # but stored files existed back then, so 'file' is what it was.
        self.assertEqual(legacy["visitor_key"], "")
        self.assertEqual(legacy["kind"], "file")
        self.assertEqual(self.download_count(), 1)


class SignInGateTests(DownloadTestCase):
    """Downloading needs an account, and signing in returns you to it."""

    def test_signed_out_download_is_sent_to_sign_in(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], f"/login?next={self.url}")
        self.assertEqual(self.download_count(), 0)

    def test_signed_out_cad_link_is_sent_to_sign_in(self):
        design_id = self.seed(cad_link="https://cad.onshape.com/documents/abc")
        response = self.client.get(f"/designs/{design_id}/cad")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], f"/login?next=/designs/{design_id}/cad")
        self.assertEqual(self.download_count(design_id), 0)

    def test_the_sign_in_page_says_why_it_asked(self):
        page = self.client.get(self.url, follow_redirects=True)
        self.assertIn("Sign in to download this design.", page.data.decode())

    def test_signing_in_lands_back_on_the_download(self):
        self.client.get(self.url)  # arrive at sign-in the way a person would
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-csrf"
        response = self.client.post(
            "/login",
            data={"username": "downloader", "password": "correct-horse",
                  "next": self.url, "csrf_token": "test-csrf"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], self.url)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.download_count(), 1)

    def test_sign_in_will_not_be_bounced_off_site(self):
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-csrf"
        response = self.client.post(
            "/login",
            data={"username": "downloader", "password": "correct-horse",
                  "next": "//evil.example.com/", "csrf_token": "test-csrf"},
        )
        self.assertEqual(response.headers["Location"], "/")

    def test_registering_from_the_gate_offers_the_download_back(self):
        with patch.object(self.application, "send_verification_email", return_value=True):
            with self.client.session_transaction() as session:
                session["csrf_token"] = "test-csrf"
            self.client.post(
                f"/register?next={self.url}",
                data={"username": "newcomer", "email": "newcomer@example.com",
                      "password": "correct-horse", "age_13_confirmed": "yes",
                      "legal_policies_accepted": "yes",
                      "minor_permission_confirmed": "yes",
                      "next": self.url, "csrf_token": "test-csrf"},
            )
        with self.client.session_transaction() as session:
            self.assertEqual(session.get("post_signup_next"), self.url)

        # Onboarding is three screens long; the offer waits at the end of it.
        conn = db.connect()
        conn.execute("UPDATE users SET onboarding_complete=1 WHERE username='newcomer'")
        conn.commit()
        conn.close()
        page = self.client.get("/welcome/explore")
        self.assertIn(f'href="{self.url}"', page.data.decode())

    def test_a_registration_cannot_be_pointed_off_site(self):
        with patch.object(self.application, "send_verification_email", return_value=True):
            with self.client.session_transaction() as session:
                session["csrf_token"] = "test-csrf"
            self.client.post(
                "/register",
                data={"username": "wanderer", "email": "wanderer@example.com",
                      "password": "correct-horse", "age_13_confirmed": "yes",
                      "legal_policies_accepted": "yes",
                      "minor_permission_confirmed": "yes",
                      "next": "//evil.example.com/", "csrf_token": "test-csrf"},
            )
        with self.client.session_transaction() as session:
            self.assertIsNone(session.get("post_signup_next"))


class CadLinkTests(DownloadTestCase):
    """Opening the CAD where it lives goes through the same door as the file."""

    def setUp(self):
        super().setUp()
        self.login(self.downloader_id)
        self.cad_design_id = self.seed(cad_link="https://cad.onshape.com/documents/abc")
        self.cad_url = f"/designs/{self.cad_design_id}/cad"

    def test_opening_the_cad_hands_over_the_real_link(self):
        response = self.client.get(self.cad_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://cad.onshape.com/documents/abc")

    def test_opening_the_cad_is_recorded_as_a_link(self):
        self.client.get(self.cad_url)
        row = self.rows(self.cad_design_id)[0]
        self.assertEqual(row["kind"], "cad_link")
        self.assertEqual(row["user_id"], self.downloader_id)

    def test_opening_the_same_cad_twice_counts_once(self):
        self.client.get(self.cad_url)
        self.client.get(self.cad_url)
        self.assertEqual(self.download_count(self.cad_design_id), 1)

    def test_taking_one_design_both_ways_is_still_one_download(self):
        design_id = self.seed(model_filename="arm.stl",
                              cad_link="https://cad.onshape.com/documents/xyz")
        self.client.get(f"/designs/{design_id}/cad")
        self.client.get(f"/designs/{design_id}/download")
        self.assertEqual(self.download_count(design_id), 1)

    def test_a_design_with_no_cad_link_has_nothing_to_open(self):
        self.assertEqual(self.client.get(f"/designs/{self.design_id}/cad").status_code, 404)

    def test_a_legacy_link_with_an_unusable_scheme_is_refused(self):
        # onshape_link predates the upload form's URL validation, so old rows
        # can hold anything at all. This site will not bounce anyone to it.
        design_id = self.seed(onshape_link="javascript:alert(1)")
        self.assertEqual(self.client.get(f"/designs/{design_id}/cad").status_code, 404)
        self.assertEqual(self.download_count(design_id), 0)

    def test_a_legacy_onshape_link_still_works(self):
        design_id = self.seed(onshape_link="https://cad.onshape.com/documents/old")
        response = self.client.get(f"/designs/{design_id}/cad")
        self.assertEqual(response.headers["Location"], "https://cad.onshape.com/documents/old")

    def test_the_design_page_hands_out_the_route_not_the_link(self):
        page = self.client.get(f"/designs/{self.cad_design_id}").data.decode()
        self.assertIn(f'href="{self.cad_url}"', page)
        # The CAD host's own URL is no longer sitting in the page for anyone
        # who never signs in, or for anything that scrapes it.
        self.assertNotIn("cad.onshape.com/documents/abc", page)

    def test_a_signed_out_visitor_is_not_sent_to_sign_in_in_a_new_tab(self):
        stranger = self.application.app.test_client()
        page = stranger.get(f"/designs/{self.cad_design_id}").data.decode()
        self.assertIn(f'href="{self.cad_url}"', page)
        self.assertNotIn(f'href="{self.cad_url}" target="_blank"', page)
        # Signed in, it still opens away from the page they were reading.
        signed_in = self.client.get(f"/designs/{self.cad_design_id}").data.decode()
        self.assertIn(f'href="{self.cad_url}" target="_blank"', signed_in)

    def test_a_hidden_design_is_not_opened_for_strangers(self):
        conn = db.connect()
        conn.execute("UPDATE designs SET is_hidden=1 WHERE id=?", (self.cad_design_id,))
        conn.commit()
        conn.close()
        self.assertEqual(self.client.get(self.cad_url).status_code, 404)


class DailyAllowanceTests(DownloadTestCase):
    """Five different designs a day, and repeats of them are free."""

    def setUp(self):
        super().setUp()
        self.login(self.downloader_id)
        self.limit = self.application.DAILY_DOWNLOAD_LIMIT
        self.spare_ids = [self.seed(model_filename=f"part{n}.stl", title=f"Part {n}")
                          for n in range(self.limit + 1)]

    def spend_the_allowance(self):
        for design_id in self.spare_ids[:self.limit]:
            self.assertEqual(self.client.get(f"/designs/{design_id}/download").status_code, 200)

    def test_the_allowance_is_spent_one_design_at_a_time(self):
        self.spend_the_allowance()
        self.assertEqual(len(self.rows()), self.limit)

    def test_one_design_past_the_allowance_is_refused(self):
        self.spend_the_allowance()
        extra_id = self.spare_ids[self.limit]
        response = self.client.get(f"/designs/{extra_id}/download")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], f"/designs/{extra_id}")
        self.assertEqual(self.download_count(extra_id), 0)
        self.assertEqual(len(self.rows()), self.limit)

    def test_the_refusal_says_how_many_and_when(self):
        self.spend_the_allowance()
        page = self.client.get(f"/designs/{self.spare_ids[self.limit]}/download",
                               follow_redirects=True).data.decode()
        self.assertIn(f"That is all {self.limit} of your downloads for today", page)
        self.assertIn("in about 24 hours", page)

    def test_the_allowance_covers_cad_links_too(self):
        self.spend_the_allowance()
        design_id = self.seed(cad_link="https://cad.onshape.com/documents/abc")
        response = self.client.get(f"/designs/{design_id}/cad")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], f"/designs/{design_id}")
        self.assertEqual(self.download_count(design_id), 0)

    def test_a_design_already_taken_today_can_still_be_fetched_again(self):
        self.spend_the_allowance()
        already = self.spare_ids[0]
        self.assertEqual(self.client.get(f"/designs/{already}/download").status_code, 200)
        self.assertEqual(len(self.rows()), self.limit)

    def test_the_allowance_is_per_account(self):
        self.spend_the_allowance()
        other = self.application.app.test_client()
        with other.session_transaction() as session:
            session["user_id"] = self.admin_id
        self.assertEqual(
            other.get(f"/designs/{self.spare_ids[self.limit]}/download").status_code, 200)

    def test_yesterdays_downloads_do_not_count_against_today(self):
        self.spend_the_allowance()
        conn = db.connect()
        conn.execute("UPDATE design_downloads SET downloaded_at=datetime('now', ?)",
                     (f"-{self.application.DOWNLOAD_COOLDOWN_MINUTES + 1} minutes",))
        conn.commit()
        conn.close()
        self.assertEqual(
            self.client.get(f"/designs/{self.spare_ids[self.limit]}/download").status_code, 200)

    def test_an_uploader_is_never_locked_out_of_their_own_work(self):
        self.login(self.owner_id)
        for design_id in self.spare_ids:
            self.assertEqual(self.client.get(f"/designs/{design_id}/download").status_code, 200)

    def test_fetching_your_own_uploads_does_not_spend_your_allowance(self):
        self.login(self.owner_id)
        for design_id in self.spare_ids:
            self.client.get(f"/designs/{design_id}/download")
        someone_elses = self.seed(model_filename="theirs.stl", owner_id=self.admin_id)
        self.assertEqual(
            self.client.get(f"/designs/{someone_elses}/download").status_code, 200)

    def test_the_renewal_estimate_rounds_towards_waiting_longer(self):
        self.spend_the_allowance()
        extra_url = f"/designs/{self.spare_ids[self.limit]}/download"
        for minutes_ago, expected in ((1435, "within the hour"),
                                      (1395, "in about an hour"),
                                      (1335, "in about 2 hours")):
            conn = db.connect()
            conn.execute("UPDATE design_downloads SET downloaded_at=datetime('now', ?)",
                         (f"-{minutes_ago} minutes",))
            conn.commit()
            conn.close()
            page = self.client.get(extra_url, follow_redirects=True).data.decode()
            self.assertIn(expected, page)

    def test_an_admin_can_keep_opening_reported_uploads(self):
        self.login(self.admin_id)
        for design_id in self.spare_ids:
            self.assertEqual(self.client.get(f"/designs/{design_id}/download").status_code, 200)


class BypassTests(DownloadTestCase):
    """The ways around the gate, each one of which used to work.

    Every test here is a reproduction: an adversarial review of the gate found
    all of them against the running app, so they are written as the attack
    rather than as the fix.
    """

    def setUp(self):
        super().setUp()
        self.login(self.downloader_id)
        self.limit = self.application.DAILY_DOWNLOAD_LIMIT
        self.spare_ids = [self.seed(model_filename=f"part{n}.stl", title=f"Part {n}",
                                    cad_link=f"https://cad.onshape.com/documents/D{n}")
                          for n in range(self.limit + 3)]

    def test_range_requests_cannot_outrun_the_allowance(self):
        # `curl -H 'Range: bytes=0-'` returns 206 with the entire file. While
        # 206 went uncounted that fetched the whole library on one account.
        with patch.object(self.application.infra_storage, "send",
                          side_effect=lambda *a, **k: Response(b"x" * 64, status=206)):
            served = [self.client.get(f"/designs/{design_id}/download",
                                      headers={"Range": "bytes=0-"}).status_code
                      for design_id in self.spare_ids]
        self.assertEqual(served.count(206), self.limit)
        self.assertEqual(len(self.rows()), self.limit)

    def test_head_requests_cannot_outrun_the_allowance_on_the_cad_route(self):
        # A HEAD response to /cad still carries the real CAD URL in Location,
        # so `curl -I` used to walk the whole gallery for nothing.
        handed_out = []
        for design_id in self.spare_ids:
            response = self.client.head(f"/designs/{design_id}/cad")
            if "onshape.com" in (response.headers.get("Location") or ""):
                handed_out.append(design_id)
        self.assertEqual(len(handed_out), self.limit)
        self.assertEqual(len(self.rows()), self.limit)

    def test_the_viewer_route_is_not_an_anonymous_way_to_the_same_bytes(self):
        # /model serves what /download serves, differing only in
        # Content-Disposition, so leaving it open made the gate decorative.
        stranger = self.application.app.test_client()
        response = stranger.get(f"/designs/{self.design_id}/model")
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"/login?next=/designs/{self.design_id}/model",
                      response.headers["Location"])

    def test_viewing_in_3d_while_signed_in_is_free(self):
        # The account is the point, not a second allowance: looking at designs
        # on their own pages is browsing, and five of those is an ordinary
        # afternoon.
        for design_id in self.spare_ids:
            self.assertEqual(
                self.client.get(f"/designs/{design_id}/model").status_code, 200)
        self.assertEqual(len(self.rows()), 0)

    def test_a_signed_out_visitor_is_offered_the_way_into_the_viewer(self):
        stranger = self.application.app.test_client()
        page = stranger.get(f"/designs/{self.design_id}").data.decode()
        self.assertIn("Sign in to view in 3D", page)
        self.assertNotIn('id="view-3d"', page)

    def test_the_search_api_does_not_publish_the_cad_links(self):
        # /api/search answers anyone and embedded whole `SELECT d.*` rows, so it
        # served the very URLs the CAD button now asks for an account before
        # handing over.
        self.seed(model_filename="api.stl", title="Zorbotron",
                  cad_link="https://cad.onshape.com/documents/SHOULDNOTLEAK")
        stranger = self.application.app.test_client()
        body = stranger.get("/api/search?q=Zorbotron").data.decode()
        self.assertIn("Zorbotron", body)
        self.assertNotIn("SHOULDNOTLEAK", body)

    def test_a_link_that_only_looks_like_botfolio_is_refused(self):
        # urlparse reads the whole of "botfolio.example.com@evil.example" as the
        # netloc, so scheme and netloc alone said yes while the browser went to
        # evil.example -- and this route is reached seconds after someone types
        # their real password.
        design_id = self.seed(
            cad_link="https://botfolio.example.com@evil.example/session-expired")
        self.assertEqual(self.client.get(f"/designs/{design_id}/cad").status_code, 404)
        self.assertEqual(len(self.rows(design_id)), 0)

    def test_a_link_with_a_newline_in_it_is_refused_rather_than_crashing(self):
        # urlparse strips CR and LF before parsing, so this passed validation
        # and then raised inside Werkzeug as it built the Location header.
        design_id = self.seed(cad_link="https://cad.example.com/doc\r\nX-Injected: yes")
        self.assertEqual(self.client.get(f"/designs/{design_id}/cad").status_code, 404)

    def test_a_next_target_cannot_be_smuggled_past_with_a_backslash(self):
        # Browsers normalise "/\\host" to "//host" while resolving http(s)
        # URLs, and post_signup_next is rendered into an href rather than
        # handed to redirect(), so nothing else would have caught it.
        self.assertIsNone(self.application.safe_next_target("/\\evil.example.com/phish"))
        self.assertIsNone(self.application.safe_next_target("//evil.example.com"))
        self.assertIsNone(self.application.safe_next_target("https://evil.example.com"))
        self.assertEqual(
            self.application.safe_next_target("/designs/7/download"),
            "/designs/7/download")


if __name__ == "__main__":
    unittest.main()
