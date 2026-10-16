"""An administrator must be able to find an account by typing a name.

The public People search hides suspended, banned and deleted accounts and never
looks at an email address, so it cannot find the one thing an administrator
actually needs to find: somebody locked out of an account the site insists
already exists. These tests cover the page that can.

They run against SQLite built in the *Postgres* shape -- COLLATE NOCASE removed,
the lower() unique indexes added -- because that is the arrangement production
runs on, and the one where a stray capital letter hides a row.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from tests.test_user_lookup_case import build_postgres_shaped_db


class AccountSearchTests(unittest.TestCase):
    # username, email, verified, deleted, banned, suspended, display name
    PEOPLE = [
        ("Friend_Nine", "Friend@Gmail.com", "2026-01-02", None, None, None, "Sam Okafor"),
        ("dotted_one", "F.r.i.end+ftc@GoogleMail.com", "2026-01-03", None, None, None, ""),
        ("banned_one", "banned@example.com", "2026-01-04", None, "2026-02-01", "2026-02-01", ""),
        ("gone_one", "deleted-9@invalid.botfolio", None, "2026-02-02", None, None, ""),
        ("homoglyph", "friеnd4@gmail.com", None, None, None, None, ""),
        ("spacey", "friend5@gmail.com ", None, None, None, None, ""),
        ("unrelated", "someone@example.com", "2026-01-05", None, None, None, "Dana Reyes"),
        # Spells f-r-i-e-n-d out in order, so the coarse net that catches
        # "F.r.i.end+ftc@..." catches this too. It is a different person.
        ("frida_enderby", "frida.enderby@example.com", "2026-01-06", None, None, None, ""),
    ]

    def setUp(self):
        import app as application

        self.application = application
        self.application.app.testing = True
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "test.db"
        build_postgres_shaped_db(path)
        self.db_patch = patch.object(db, "DB_PATH", path)
        self.db_patch.start()

        conn = db.connect()
        self.admin_id = conn.execute(
            "INSERT INTO users(username,email,password_hash,is_admin,onboarding_complete)"
            " VALUES ('site_admin','admin@example.com','hash',1,1)").lastrowid
        for name, email, verified, deleted, banned, suspended, display in self.PEOPLE:
            conn.execute(
                "INSERT INTO users(username,email,password_hash,onboarding_complete,"
                "email_verified_at,deleted_at,banned_at,suspended_at,display_name)"
                " VALUES (?,?,'hash',1,?,?,?,?,?)",
                (name, email, verified, deleted, banned, suspended, display))
        self.member_id = conn.execute(
            "SELECT id FROM users WHERE username='unrelated'").fetchone()["id"]
        conn.commit()
        conn.close()
        self.client = self.application.app.test_client()

    def tearDown(self):
        self.application.app.testing = False
        self.db_patch.stop()
        self.temp.cleanup()

    def _sign_in(self, user_id):
        with self.client.session_transaction() as browser_session:
            browser_session["user_id"] = user_id

    def _search(self, query):
        self._sign_in(self.admin_id)
        response = self.client.get("/admin/users", query_string={"q": query})
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def _accounts(self, query):
        conn = db.connect()
        try:
            return self.application.find_accounts(conn, query)
        finally:
            conn.close()

    def _names(self, query):
        return [account["user"]["username"] for account in self._accounts(query)]

    # -- who may look -----------------------------------------------------

    def test_an_ordinary_member_may_not_open_the_page(self):
        self._sign_in(self.member_id)
        self.assertEqual(self.client.get("/admin/users").status_code, 403)

    def test_a_signed_out_visitor_may_not_open_the_page(self):
        self.assertEqual(self.client.get("/admin/users").status_code, 403)

    def test_account_lookup_lives_in_moderation_not_the_menu(self):
        self._sign_in(self.member_id)
        self.assertNotIn("Find an account",
                         self.client.get("/").get_data(as_text=True))
        self._sign_in(self.admin_id)
        menu = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("Find an account", menu)
        self.assertNotIn("Invite a Team", menu)
        self.assertIn("Moderation", menu)
        self.assertIn("Find an account", self.client.get("/moderation/comments").get_data(as_text=True))

    def test_moderation_lists_twenty_accounts_and_expands(self):
        conn = db.connect()
        for number in range(25):
            conn.execute("INSERT INTO users(username,email,password_hash) VALUES (?,?,?)",
                         (f"listed{number:02}", f"listed{number:02}@example.com", "hash"))
        conn.commit()
        conn.close()
        self._sign_in(self.admin_id)
        from flask import template_rendered
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, self.application.app):
            response = self.client.get("/moderation/comments")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(contexts[-1]["user_results"]), 20)
            self.assertIn("See all", response.get_data(as_text=True))
            response = self.client.get("/moderation/comments?accounts=all")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(contexts[-1]["user_results"]), len(self.PEOPLE) + 26)
            self.assertIn("Show fewer", response.get_data(as_text=True))
            response = self.client.get("/moderation/comments?user=listed&accounts=all")
            self.assertEqual(len(contexts[-1]["user_results"]), 25)

    def test_moderation_preserves_advanced_account_matching(self):
        self._sign_in(self.admin_id)
        page = self.client.get("/moderation/comments?user=friend@gmail.com").get_data(as_text=True)
        self.assertIn("dotted_one", page)
        self.assertIn("the same inbox, written differently", page)
        self.assertNotIn("frida_enderby", page)
        page = self.client.get("/moderation/comments?user=gone_one").get_data(as_text=True)
        self.assertIn("gone_one", page)
        self.assertIn("Deleted", page)

    def test_moderation_search_is_admin_only(self):
        self.assertEqual(self.client.get("/moderation/comments").status_code, 403)
        self._sign_in(self.member_id)
        self.assertEqual(self.client.get("/moderation/comments").status_code, 403)

    # -- searching by name, which is the whole point ----------------------

    def test_part_of_a_username_is_enough(self):
        self.assertIn("Friend_Nine", self._names("friend_n"))

    def test_capitals_do_not_matter(self):
        self.assertIn("Friend_Nine", self._names("FRIEND_NINE"))

    def test_a_display_name_is_searched_too(self):
        self.assertIn("Friend_Nine", self._names("okafor"))

    # -- searching by address ---------------------------------------------

    def test_an_address_stored_with_capitals_is_found_in_lower_case(self):
        self.assertIn("Friend_Nine", self._names("friend@gmail.com"))

    def test_a_gmail_address_written_with_dots_and_a_tag_is_the_same_inbox(self):
        self.assertIn("dotted_one", self._names("friend@gmail.com"))

    def test_googlemail_is_not_a_different_provider(self):
        self.assertIn("dotted_one", self._names("friend@googlemail.com"))

    def test_the_wide_net_does_not_drag_in_unrelated_accounts(self):
        # frida.enderby@ is exactly what the coarse net over-matches: it spells
        # the mailbox out in order and reaches an entirely different person.
        found = self._names("friend@gmail.com")
        self.assertNotIn("frida_enderby", found)
        self.assertNotIn("unrelated", found)

    # -- accounts the public search refuses to show ------------------------

    def test_banned_suspended_and_deleted_accounts_are_all_included(self):
        self.assertIn("banned_one", self._names("banned"))
        self.assertIn("gone_one", self._names("gone_one"))

    def test_the_state_says_why_an_account_is_not_behaving(self):
        states = {account["user"]["username"]: account["state"]
                  for account in self._accounts("n")}
        self.assertEqual(states["banned_one"], "banned")
        self.assertEqual(states["gone_one"], "deleted")
        self.assertEqual(states["spacey"], "email never verified")
        self.assertEqual(states["Friend_Nine"], "active")

    # -- the things that look like correct typing but are not --------------

    def test_a_homoglyph_in_the_address_is_called_out(self):
        why = {account["user"]["username"]: account["why"]
               for account in self._accounts("homoglyph")}["homoglyph"]
        self.assertIn("holds characters that only look like plain letters", why)

    def test_surrounding_whitespace_is_called_out(self):
        why = {account["user"]["username"]: account["why"]
               for account in self._accounts("spacey")}["spacey"]
        self.assertIn("stored with surrounding whitespace", why)

    def test_every_result_says_why_it_matched(self):
        for account in self._accounts("friend"):
            self.assertTrue(account["why"][0], account["user"]["username"])

    # -- the page itself ---------------------------------------------------

    def test_the_page_shows_a_match_and_links_to_the_profile(self):
        page = self._search("friend@gmail.com")
        self.assertIn("Friend_Nine", page)
        self.assertIn("/u/Friend_Nine", page)
        self.assertIn("the same inbox, written differently", page)

    def test_an_empty_query_renders_the_form_and_no_table(self):
        page = self._search("")
        self.assertIn("Find an account", page)
        self.assertNotIn("Why it matched", page)

    def test_a_query_that_matches_nothing_says_so(self):
        self.assertIn("Nothing matched", self._search("zzzznobody"))


class CanonicalInboxTests(unittest.TestCase):
    def setUp(self):
        import app as application
        self.canonical = application.canonical_inbox

    def test_gmail_ignores_dots_and_tags_and_googlemail(self):
        for spelling in ("friend@gmail.com", "F.r.i.end@Gmail.com",
                         "friend+ftc@gmail.com", "fri.end+a+b@googlemail.com"):
            self.assertEqual(self.canonical(spelling), "friend@gmail.com", spelling)

    def test_other_providers_keep_their_dots_and_tags(self):
        self.assertEqual(self.canonical("First.Last@Example.com"),
                         "first.last@example.com")
        self.assertEqual(self.canonical("first+tag@example.com"),
                         "first+tag@example.com")

    def test_something_that_is_not_an_address_has_no_inbox(self):
        self.assertEqual(self.canonical("friend_nine"), "")
        self.assertEqual(self.canonical(""), "")
        self.assertEqual(self.canonical(None), "")


if __name__ == "__main__":
    unittest.main()
