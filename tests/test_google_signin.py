"""Sign in with Google, tested at the boundary that actually matters.

Every interesting decision in this feature is about what a Google identity is
allowed to do to a Botfolio account, so most of these tests are about the cases
where the answer is "nothing": an unverified address, a suspended account, a
replayed callback, a token that does not carry our nonce.

Google itself is replaced by a fake urlopen. Nothing here reaches the network,
and nothing here has a real client id -- the three settings are patched on, so
the same test file also proves the feature is invisible when they are not.
"""

import ast
import base64
import hashlib
import json
import re
import sqlite3
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import check_password_hash, generate_password_hash

import db
from services import google_oauth

REPO_ROOT = Path(__file__).resolve().parent.parent

CLIENT_ID = "test-client-id.apps.googleusercontent.com"
CLIENT_SECRET = "test-client-secret"
REDIRECT_URI = "https://botfoliohq.test/auth/google/callback"

PASSWORD = "supersecret1"
GOOGLE_SUB = "115582974336601234567"
GOOGLE_EMAIL = "builder@gmail.com"


def b64url(payload):
    raw = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def id_token(**overrides):
    """A structurally real id_token. The signature is never checked -- see the
    module docstring of services/google_oauth.py for why that is sound here."""
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": GOOGLE_SUB,
        "email": GOOGLE_EMAIL,
        "email_verified": True,
        "name": "Builder Bot",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return f"{b64url({'alg': 'RS256'})}.{b64url(claims)}.fake-signature"


class _Response:
    """Just enough of an http.client.HTTPResponse for urlopen's caller."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self, amount=None):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class GoogleSignInTestCase(unittest.TestCase):
    """A fresh database, the feature switched on, and Google stubbed out."""

    def setUp(self):
        import app as application

        self.application = application
        self.application.app.testing = True
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "test.db"
        conn = sqlite3.connect(path)
        conn.executescript((REPO_ROOT / "schema.sql").read_text(encoding="utf-8"))
        conn.commit()
        conn.close()
        self.db_patch = patch.object(db, "DB_PATH", path)
        self.db_patch.start()

        self.settings_patches = [
            patch.object(google_oauth.settings, "google_client_id", CLIENT_ID),
            patch.object(google_oauth.settings, "google_client_secret", CLIENT_SECRET),
            patch.object(google_oauth.settings, "google_redirect_uri", REDIRECT_URI),
        ]
        for patcher in self.settings_patches:
            patcher.start()

        # In-process counters survive between test methods, and this flow has
        # two rate-limited GETs per sign-in.
        self.application.ratelimit._buckets.clear()
        self.client = self.application.app.test_client()
        self.sent_email = []

    def tearDown(self):
        for patcher in self.settings_patches:
            patcher.stop()
        self.db_patch.stop()
        self.temp.cleanup()
        self.application.app.testing = False

    # -- helpers ----------------------------------------------------------

    def query(self, sql, params=()):
        conn = db.connect()
        try:
            return conn.execute(sql, params).fetchone()
        finally:
            conn.close()

    def run_sql(self, sql, params=()):
        conn = db.connect()
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def make_user(self, username="GearBuilder", email=GOOGLE_EMAIL, verified=True,
                  consented=True, **columns):
        self.run_sql(
            "INSERT INTO users(username,email,password_hash,onboarding_complete,"
            "email_verified_at,accepted_terms_version,acknowledged_legal_version) "
            "VALUES (?,?,?,1,?,?,?)",
            (username, email, generate_password_hash(PASSWORD),
             "2026-01-01 00:00:00" if verified else None,
             self.application.TERMS_VERSION if consented else None,
             self.application.LEGAL_NOTICE_VERSION),
        )
        for column, value in columns.items():
            self.run_sql(f"UPDATE users SET {column}=? WHERE username=?",
                         (value, username))
        return self.query("SELECT * FROM users WHERE username=?", (username,))

    def start_flow(self, next_target=None):
        """Do the /auth/google/start leg and return Google's redirect URL."""
        path = "/auth/google/start"
        if next_target:
            path += "?next=" + urllib.parse.quote(next_target)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 302)
        return response.headers["Location"]

    def flow_state(self):
        with self.client.session_transaction() as browser:
            return dict(browser.get("oauth_google") or {})

    def callback(self, token_payload=None, userinfo=None, state=None, **params):
        """Complete the callback leg with a stubbed token endpoint."""
        query = {"state": state if state is not None else self.flow_state()["state"],
                 "code": "authorization-code"}
        query.update(params)
        payload = token_payload
        if payload is None:
            payload = {"id_token": id_token(), "access_token": "at"}

        responses = [_Response(payload)]
        if userinfo is not None:
            responses.append(_Response(userinfo))

        def fake_urlopen(request, timeout=None, context=None):
            return responses.pop(0)

        with patch("services.google_oauth.urllib.request.urlopen", fake_urlopen), \
                patch.object(self.application.email_service, "send_email",
                             side_effect=self.record_email):
            return self.client.get(
                "/auth/google/callback?" + urllib.parse.urlencode(query),
                follow_redirects=False)

    def record_email(self, **fields):
        self.sent_email.append(fields)
        return True

    def signed_in_user_id(self):
        with self.client.session_transaction() as browser:
            return browser.get("user_id")

    def csrf(self, path):
        self.client.get(path)
        with self.client.session_transaction() as browser:
            return browser["csrf_token"]

    def _complete(self, **kwargs):
        """A whole flow, carrying the nonce the start leg actually minted."""
        self.start_flow()
        with self.client.session_transaction() as browser:
            nonce = browser["oauth_google"]["nonce"]
        return self.callback(token_payload={
            "id_token": id_token(nonce=nonce, **kwargs), "access_token": "at"})

    def _legacy_backfilled_user(self, **columns):
        """A row exactly as the boot-time backfill leaves it.

        Old, consent-less, and carrying a verification date the backfill
        invented rather than earned -- stamped as such in email_verified_source,
        which is the only thing that tells it apart from an address Botfolio
        genuinely proved.
        """
        user = self.make_user(consented=False, **columns)
        self.run_sql(
            "UPDATE users SET created_at = '2020-01-01 00:00:00', "
            "email_verified_at = '2020-01-01 00:00:00', "
            "email_verified_source = 'backfill' WHERE id = ?",
            (user["id"],))
        return self.query("SELECT * FROM users WHERE id = ?", (user["id"],))

    def _claim_token(self, user, raw="claim"):
        """Put a live password-reset token on an account and return its path."""
        self.run_sql(
            "INSERT INTO password_reset_tokens(user_id,token_hash,expires_at) "
            "VALUES (?,?,datetime('now','+30 minutes'))",
            (user["id"], hashlib.sha256(raw.encode("utf-8")).hexdigest()))
        return "/reset-password/" + raw

    def _set_password(self, path, password="brand-new-password"):
        return self.client.post(path, data={
            "password": password, "confirm_password": password,
            "confirmation": password, "csrf_token": self.csrf(path)})


class FeatureFlagTests(GoogleSignInTestCase):
    """Unconfigured must mean absent, not broken."""

    def test_the_button_appears_on_the_sign_in_page_when_configured(self):
        page = self.client.get("/login").get_data(as_text=True)
        self.assertIn("Sign in with Google", page)
        self.assertIn("/auth/google/start", page)

    def test_no_credential_reaches_the_page(self):
        page = self.client.get("/login").get_data(as_text=True)
        self.assertNotIn(CLIENT_ID, page)
        self.assertNotIn(CLIENT_SECRET, page)

    def test_without_credentials_the_button_is_gone_and_the_routes_404(self):
        with patch.object(google_oauth.settings, "google_client_id", ""):
            page = self.client.get("/login").get_data(as_text=True)
            self.assertNotIn("Sign in with Google", page)
            self.assertEqual(self.client.get("/auth/google/start").status_code, 404)
            self.assertEqual(
                self.client.get("/auth/google/callback").status_code, 404)


class AuthorizationRequestTests(GoogleSignInTestCase):
    """What we send Google has to carry every anti-forgery value."""

    def test_the_redirect_carries_pkce_state_and_nonce(self):
        location = self.start_flow()
        self.assertTrue(location.startswith(google_oauth.AUTH_ENDPOINT + "?"))
        params = dict(urllib.parse.parse_qsl(location.partition("?")[2]))
        stored = self.flow_state()
        self.assertEqual(params["client_id"], CLIENT_ID)
        self.assertEqual(params["redirect_uri"], REDIRECT_URI)
        self.assertEqual(params["response_type"], "code")
        self.assertEqual(params["scope"], "openid email profile")
        self.assertEqual(params["state"], stored["state"])
        self.assertEqual(params["nonce"], stored["nonce"])
        self.assertEqual(params["code_challenge_method"], "S256")
        self.assertEqual(params["code_challenge"],
                         google_oauth.pkce_challenge(stored["verifier"]))
        self.assertEqual(params["prompt"], "select_account")

    def test_the_verifier_never_leaves_the_server(self):
        location = self.start_flow()
        self.assertNotIn(self.flow_state()["verifier"], location)

    def test_a_next_target_is_kept_but_only_when_it_is_this_site(self):
        self.start_flow("/gallery")
        self.assertEqual(self.flow_state()["next"], "/gallery")
        self.start_flow("https://evil.example/steal")
        self.assertEqual(self.flow_state()["next"], "")

    def test_each_attempt_gets_fresh_values(self):
        self.start_flow()
        first = self.flow_state()
        self.start_flow()
        self.assertNotEqual(first["state"], self.flow_state()["state"])
        self.assertNotEqual(first["nonce"], self.flow_state()["nonce"])


class CallbackRejectionTests(GoogleSignInTestCase):
    """An unsolicited or tampered callback must change nothing."""

    def test_a_callback_with_no_flow_in_progress_is_refused(self):
        response = self.client.get("/auth/google/callback?state=x&code=y")
        self.assertEqual(response.headers["Location"], "/login")
        self.assertIsNone(self.signed_in_user_id())

    def test_a_mismatched_state_is_refused_before_the_code_is_used(self):
        self.make_user()
        self.start_flow()
        response = self.callback(state="not-the-state")
        self.assertEqual(response.headers["Location"], "/login")
        self.assertIsNone(self.signed_in_user_id())
        self.assertIsNone(self.query("SELECT google_sub FROM users")["google_sub"])

    def test_the_state_is_single_use_so_a_replay_fails(self):
        """The first leg has to succeed, or the second proves nothing.

        A callback carrying no nonce is refused on the nonce, so replaying one
        is a test of the nonce check wearing the state check's name.
        """
        user = self.make_user(google_sub=GOOGLE_SUB)
        self.start_flow()
        pending = self.flow_state()
        first = self.callback(token_payload={
            "id_token": id_token(nonce=pending["nonce"]), "access_token": "at"})
        self.assertEqual(first.headers["Location"], "/")
        self.assertEqual(self.signed_in_user_id(), user["id"])

        # Signing out is a POST; GET /logout only renders the confirmation.
        self.client.post("/logout", data={"csrf_token": self.csrf("/logout")})
        self.assertIsNone(self.signed_in_user_id())
        replay = self.callback(
            state=pending["state"],
            token_payload={"id_token": id_token(nonce=pending["nonce"]),
                           "access_token": "at"})
        self.assertEqual(replay.headers["Location"], "/login")
        self.assertIsNone(self.signed_in_user_id())

    def test_an_expired_flow_is_refused(self):
        self.start_flow()
        with self.client.session_transaction() as browser:
            pending = dict(browser["oauth_google"])
            pending["ts"] = int(time.time()) - 4000
            browser["oauth_google"] = pending
            state = pending["state"]
        response = self.callback(state=state)
        self.assertEqual(response.headers["Location"], "/login")

    def test_a_cancelled_sign_in_reads_as_a_choice_not_a_fault(self):
        self.start_flow()
        response = self.client.get(
            "/auth/google/callback?" + urllib.parse.urlencode(
                {"state": self.flow_state()["state"], "error": "access_denied"}))
        self.assertEqual(response.headers["Location"], "/login")
        page = self.client.get("/login").get_data(as_text=True)
        self.assertIn("cancelled", page)

    def test_googles_error_description_is_never_echoed_back(self):
        self.start_flow()
        self.client.get("/auth/google/callback?" + urllib.parse.urlencode({
            "state": self.flow_state()["state"],
            "error": "invalid_request",
            "error_description": "<script>alert(1)</script>",
        }))
        page = self.client.get("/login").get_data(as_text=True)
        self.assertNotIn("alert(1)", page)


class TokenValidationTests(GoogleSignInTestCase):
    """The claims we act on have to be the ones we asked for."""

    def _reject(self, **overrides):
        self.start_flow()
        # The live nonce unless a case overrides it: otherwise every token is
        # rejected on the nonce and the claim under test is never reached.
        overrides.setdefault("nonce", self.flow_state()["nonce"])
        response = self.callback(
            token_payload={"id_token": id_token(**overrides), "access_token": "at"})
        self.assertEqual(response.headers["Location"], "/login")
        self.assertIsNone(self.signed_in_user_id())
        self.assertIsNone(self.query("SELECT id FROM users"))

    def test_a_token_for_another_client_is_rejected(self):
        self._reject(aud="someone-elses-client-id")

    def test_a_token_for_several_clients_must_name_us_as_the_party(self):
        """OIDC 3.1.3.7 clauses 3-4. Without azp, a token minted for another
        client that merely lists us as an audience would pass as one of ours."""
        self._reject(aud=[CLIENT_ID, "another-client-id"])
        self._reject(aud=[CLIENT_ID, "another-client-id"], azp="another-client-id")

    def test_a_multi_audience_token_that_names_us_is_accepted(self):
        user = self.make_user(google_sub=GOOGLE_SUB)
        self.start_flow()
        self.callback(token_payload={
            "id_token": id_token(nonce=self.flow_state()["nonce"],
                                 aud=[CLIENT_ID, "another-client-id"],
                                 azp=CLIENT_ID),
            "access_token": "at"})
        self.assertEqual(self.signed_in_user_id(), user["id"])

    def test_an_audience_of_the_wrong_shape_is_refused_not_a_500(self):
        """aud is a string or a list of them. list(12345) is a TypeError, and
        a 500 reachable from a response body is a 500 anyone can reach."""
        self._reject(aud=12345)
        self._reject(aud={"client": CLIENT_ID})

    def test_a_token_from_another_issuer_is_rejected(self):
        self._reject(iss="https://accounts.evil.example")

    def test_an_expired_token_is_rejected(self):
        self._reject(exp=int(time.time()) - 3600)

    def test_a_token_minted_for_a_different_flow_is_rejected(self):
        """The replay defence: a real Google token, wrong browser."""
        self.start_flow()
        stolen = id_token(nonce="a-nonce-from-somebody-elses-request")
        response = self.callback(
            token_payload={"id_token": stolen, "access_token": "at"})
        self.assertEqual(response.headers["Location"], "/login")
        self.assertIsNone(self.signed_in_user_id())

    def test_an_unverified_google_address_cannot_match_an_account(self):
        """Otherwise the email-matching rule becomes account takeover: anyone
        can add any address to a throwaway Google account without proving it."""
        self.make_user()
        self.start_flow()
        response = self.callback(token_payload={
            # No access_token, so an unverified address has nowhere to go: the
            # userinfo fallback is not a second chance at the same claim.
            "id_token": id_token(nonce=self.flow_state()["nonce"],
                                 email_verified=False)})
        self.assertEqual(response.headers["Location"], "/login")
        self.assertIsNone(self.signed_in_user_id())
        self.assertIsNone(self.query("SELECT google_sub FROM users")["google_sub"])

    def test_an_unverified_address_from_userinfo_is_refused_too(self):
        self.make_user()
        self.start_flow()
        nonce = self.flow_state()["nonce"]
        claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID,
                  "sub": GOOGLE_SUB, "nonce": nonce, "iat": int(time.time()),
                  "exp": int(time.time()) + 3600}
        response = self.callback(
            token_payload={"id_token": f"h.{b64url(claims)}.s", "access_token": "at"},
            userinfo={"sub": GOOGLE_SUB, "email": GOOGLE_EMAIL,
                      "email_verified": False})
        self.assertEqual(response.headers["Location"], "/login")
        self.assertIsNone(self.signed_in_user_id())
        self.assertIsNone(self.query("SELECT google_sub FROM users")["google_sub"])

    def test_the_string_form_of_email_verified_is_accepted(self):
        """Some Google surfaces have historically sent "true", not true."""
        user = self.make_user()
        self.start_flow()
        self.callback(token_payload={
            "id_token": id_token(nonce=self.flow_state()["nonce"],
                                 email_verified="true"),
            "access_token": "at"})
        self.assertEqual(self.signed_in_user_id(), user["id"])

    def test_a_google_outage_degrades_to_try_again_not_a_500(self):
        self.start_flow()

        def boom(request, timeout=None, context=None):
            raise urllib.error.URLError("connection refused")

        with patch("services.google_oauth.urllib.request.urlopen", boom):
            response = self.client.get("/auth/google/callback?" +
                                       urllib.parse.urlencode({
                                           "state": self.flow_state()["state"],
                                           "code": "authorization-code"}))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/login")

    def test_the_nonce_carries_through_the_real_authorization_url(self):
        """End to end: the value in Google's URL is the value we then require."""
        location = self.start_flow()
        params = dict(urllib.parse.parse_qsl(location.partition("?")[2]))
        self.make_user(google_sub=GOOGLE_SUB)
        response = self.callback(token_payload={
            "id_token": id_token(nonce=params["nonce"]), "access_token": "at"})
        self.assertEqual(response.headers["Location"], "/")


class ExistingAccountTests(GoogleSignInTestCase):
    """Matching an account is where a mistake becomes a takeover."""

    def test_a_linked_account_signs_in(self):
        user = self.make_user(google_sub=GOOGLE_SUB)
        response = self._complete()
        self.assertEqual(response.headers["Location"], "/")
        self.assertEqual(self.signed_in_user_id(), user["id"])

    def test_a_linked_account_keeps_the_email_its_owner_chose(self):
        """sub is the identity; a different Google address is not a new person."""
        self.make_user(email="chosen@botfolio.test", google_sub=GOOGLE_SUB)
        self._complete()
        self.assertEqual(self.query("SELECT email FROM users")["email"],
                         "chosen@botfolio.test")

    def test_a_verified_account_is_linked_and_signed_in(self):
        user = self.make_user()
        response = self._complete()
        self.assertEqual(response.headers["Location"], "/")
        self.assertEqual(self.signed_in_user_id(), user["id"])
        self.assertEqual(self.query("SELECT google_sub FROM users")["google_sub"],
                         GOOGLE_SUB)

    def test_linking_leaves_the_password_and_its_sessions_alone(self):
        user = self.make_user()
        self.run_sql("INSERT INTO user_sessions(token_hash,user_id,expires_at) "
                     "VALUES ('other-device',?,datetime('now','+1 day'))",
                     (user["id"],))
        self._complete()
        row = self.query("SELECT password_hash FROM users")
        self.assertTrue(check_password_hash(row["password_hash"], PASSWORD))
        self.assertIsNotNone(self.query(
            "SELECT user_id FROM user_sessions WHERE token_hash='other-device'"))

    def test_linking_tells_the_account_holder_out_of_band(self):
        self.make_user()
        self._complete()
        self.assertEqual([mail["to_email"] for mail in self.sent_email],
                         [GOOGLE_EMAIL])

    def test_an_unverified_account_is_never_linked(self):
        """The pre-hijacking defence: whoever registered it may not own it."""
        user = self.make_user(verified=False)
        response = self._complete()
        self.assertEqual(response.headers["Location"], "/login")
        self.assertIsNone(self.signed_in_user_id())
        self.assertIsNone(self.query("SELECT google_sub FROM users")["google_sub"])
        self.assertEqual(
            self.query("SELECT COUNT(*) c FROM password_reset_tokens "
                       "WHERE user_id=?", (user["id"],))["c"], 1)
        self.assertEqual(self.sent_email[0]["to_email"], GOOGLE_EMAIL)

    def test_a_backfilled_verification_date_does_not_count_as_proof(self):
        """_ensure_runtime_schema stamps old consent-less rows as verified."""
        user = self._legacy_backfilled_user()
        response = self._complete()
        self.assertEqual(response.headers["Location"], "/login")
        self.assertIsNone(self.query("SELECT google_sub FROM users")["google_sub"])

    def test_acknowledging_a_legal_update_does_not_prove_an_address(self):
        """The two facts move independently, which is why one is not read off
        the other: /legal-updates fills in accepted_terms_version, and inferring
        proof from that column promoted a never-verified row to verified."""
        user = self._legacy_backfilled_user()
        self.run_sql("UPDATE users SET accepted_terms_version=? WHERE id=?",
                     (self.application.TERMS_VERSION, user["id"]))
        response = self._complete()
        self.assertEqual(response.headers["Location"], "/login")
        self.assertIsNone(self.query("SELECT google_sub FROM users")["google_sub"])
        self.assertEqual([mail["subject"] for mail in self.sent_email],
                         ["Claim your Botfolio account"])

    def test_a_second_attempt_does_not_send_a_second_claim_email(self):
        self.make_user(verified=False)
        self._complete()
        self._complete()
        self.assertEqual(len(self.sent_email), 1)

    def test_a_suspended_account_cannot_sign_in_with_google(self):
        self.make_user(google_sub=GOOGLE_SUB, suspended_at="2026-01-01 00:00:00")
        response = self._complete()
        self.assertEqual(response.headers["Location"], "/login")
        self.assertIsNone(self.signed_in_user_id())
        self.assertIn("This account is restricted",
                      self.client.get("/login").get_data(as_text=True))

    def test_a_banned_account_is_not_offered_a_new_one_instead(self):
        """Falling through to account creation would make bans one click deep."""
        self.make_user(banned_at="2026-01-01 00:00:00")
        response = self._complete()
        self.assertEqual(response.headers["Location"], "/login")
        self.assertNotIn("/auth/google/complete", response.headers["Location"])
        self.assertEqual(self.query("SELECT COUNT(*) c FROM users")["c"], 1)

    def test_a_deleted_account_does_not_block_a_fresh_signup(self):
        """delete_account clears google_sub, so the tombstone is not in the way."""
        user = self.make_user(google_sub=GOOGLE_SUB)
        self.run_sql(
            "UPDATE users SET google_sub=NULL, deleted_at=datetime('now'), "
            "email=? WHERE id=?", ("deleted-1@invalid.botfolio", user["id"]))
        response = self._complete()
        self.assertEqual(response.headers["Location"], "/auth/google/complete")

    def test_the_email_claim_never_becomes_a_verification_stamp(self):
        self.make_user(verified=False)
        self._complete()
        self.assertIsNone(
            self.query("SELECT email_verified_at FROM users")["email_verified_at"])


    def test_a_legacy_row_is_not_sent_round_the_claim_loop_twice(self):
        """The claim mail promises Google will work afterwards. Make it true.

        A row the boot-time backfill stamped has a verification date and no
        consent, so the first attempt correctly refuses to link and mails a
        claim link instead. Following that link is real proof -- the second
        attempt has to sign in, not mail the same thing again.
        """
        user = self._legacy_backfilled_user()
        self._complete()
        self.assertEqual([mail["subject"] for mail in self.sent_email],
                         ["Claim your Botfolio account"])
        self.assertIsNone(self.query("SELECT google_sub FROM users")["google_sub"])

        token = self.sent_email[-1]["action_url"].rsplit("/", 1)[-1]
        path = "/reset-password/" + token
        self.client.post(path, data={"password": "a-brand-new-password",
                                     "confirmation": "a-brand-new-password",
                                     "csrf_token": self.csrf(path)})

        self.sent_email.clear()
        self.application.ratelimit._buckets.clear()
        response = self._complete()
        self.assertEqual(response.headers["Location"], "/")
        self.assertEqual(self.signed_in_user_id(), user["id"])
        self.assertEqual(self.query("SELECT google_sub FROM users")["google_sub"],
                         GOOGLE_SUB)
        self.assertNotIn("Claim your Botfolio account",
                         [mail["subject"] for mail in self.sent_email])


class NewAccountTests(GoogleSignInTestCase):
    """No row exists until the same confirmations registration collects."""

    def _park_identity(self):
        self.start_flow()
        with self.client.session_transaction() as browser:
            nonce = browser["oauth_google"]["nonce"]
        return self.callback(token_payload={
            "id_token": id_token(nonce=nonce), "access_token": "at"})

    def _consent(self):
        return {"username": "gearbuilder", "age_13_confirmed": "yes",
                "legal_policies_accepted": "yes",
                "minor_permission_confirmed": "yes"}

    def test_the_callback_alone_creates_nothing(self):
        response = self._park_identity()
        self.assertEqual(response.headers["Location"], "/auth/google/complete")
        self.assertIsNone(self.query("SELECT id FROM users"))
        self.assertIsNone(self.signed_in_user_id())

    def test_the_form_shows_the_google_address_and_a_suggested_username(self):
        self._park_identity()
        page = self.client.get("/auth/google/complete").get_data(as_text=True)
        self.assertIn(GOOGLE_EMAIL, page)
        self.assertIn('value="builder"', page)
        self.assertIn("at least 13 years old", page)

    def test_a_missing_confirmation_creates_nothing(self):
        self._park_identity()
        token = self.csrf("/auth/google/complete")
        for missing in ("age_13_confirmed", "legal_policies_accepted",
                        "minor_permission_confirmed"):
            with self.subTest(missing=missing):
                data = dict(self._consent(), csrf_token=token)
                data.pop(missing)
                self.client.post("/auth/google/complete", data=data)
                self.assertIsNone(self.query("SELECT id FROM users"))

    def test_consent_creates_the_account_and_signs_it_in(self):
        self._park_identity()
        token = self.csrf("/auth/google/complete")
        response = self.client.post("/auth/google/complete",
                                    data=dict(self._consent(), csrf_token=token))
        self.assertEqual(response.headers["Location"], "/account/setup")
        row = self.query("SELECT * FROM users")
        self.assertEqual(row["username"], "gearbuilder")
        self.assertEqual(row["email"], GOOGLE_EMAIL)
        self.assertEqual(row["google_sub"], GOOGLE_SUB)
        self.assertEqual(row["auth_provider"], "google")
        self.assertEqual(row["is_admin"], 0)
        self.assertEqual(row["onboarding_complete"], 0)
        self.assertIsNotNone(row["email_verified_at"])
        self.assertEqual(self.signed_in_user_id(), row["id"])

    def test_the_same_consent_record_registration_writes(self):
        self._park_identity()
        token = self.csrf("/auth/google/complete")
        self.client.post("/auth/google/complete",
                         data=dict(self._consent(), csrf_token=token))
        row = self.query("SELECT * FROM users")
        self.assertEqual(row["accepted_terms_version"],
                         self.application.TERMS_VERSION)
        self.assertEqual(row["accepted_privacy_version"],
                         self.application.PRIVACY_VERSION)
        self.assertEqual(row["acknowledged_legal_version"],
                         self.application.LEGAL_NOTICE_VERSION)
        self.assertEqual(row["age_13_confirmed"], 1)
        self.assertEqual(row["minor_permission_confirmed"], 1)
        self.assertIsNotNone(row["accepted_terms_at"])

    def test_no_password_anybody_holds(self):
        self._park_identity()
        token = self.csrf("/auth/google/complete")
        self.client.post("/auth/google/complete",
                         data=dict(self._consent(), csrf_token=token))
        stored = self.query("SELECT password_hash FROM users")["password_hash"]
        self.assertTrue(stored)
        for guess in ("", GOOGLE_SUB, GOOGLE_EMAIL, PASSWORD):
            self.assertFalse(check_password_hash(stored, guess))

    def test_a_taken_username_is_reported_not_a_500(self):
        self.make_user(username="gearbuilder", email="someone@else.test")
        self._park_identity()
        token = self.csrf("/auth/google/complete")
        response = self.client.post("/auth/google/complete",
                                    data=dict(self._consent(), csrf_token=token),
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("already registered", response.get_data(as_text=True))
        self.assertEqual(self.query("SELECT COUNT(*) c FROM users")["c"], 1)

    def test_a_rejected_form_does_not_strand_the_identity(self):
        self._park_identity()
        token = self.csrf("/auth/google/complete")
        self.client.post("/auth/google/complete",
                         data={"username": "no", "csrf_token": token})
        page = self.client.get("/auth/google/complete").get_data(as_text=True)
        self.assertIn(GOOGLE_EMAIL, page)

    def test_the_form_cannot_choose_its_own_email(self):
        self._park_identity()
        token = self.csrf("/auth/google/complete")
        self.client.post("/auth/google/complete", data=dict(
            self._consent(), csrf_token=token, google_email="admin@botfolio.test",
            email="admin@botfolio.test"))
        self.assertEqual(self.query("SELECT email FROM users")["email"],
                         GOOGLE_EMAIL)

    def test_the_page_is_unreachable_without_a_verified_identity(self):
        response = self.client.get("/auth/google/complete")
        self.assertEqual(response.headers["Location"], "/login")
        token = self.csrf("/login")
        self.client.post("/auth/google/complete",
                         data=dict(self._consent(), csrf_token=token))
        self.assertIsNone(self.query("SELECT id FROM users"))

    def test_no_verification_email_is_sent_for_an_address_google_proved(self):
        """No mail at all, and the row records who did prove it -- a NULL there
        reads as "verified before the column existed" and would be a lie."""
        self._park_identity()
        self.sent_email = []
        token = self.csrf("/auth/google/complete")
        with patch.object(self.application.email_service, "send_email",
                          side_effect=self.record_email):
            self.client.post("/auth/google/complete",
                             data=dict(self._consent(), csrf_token=token))
        self.assertEqual(self.sent_email, [])
        row = self.query("SELECT * FROM users")
        self.assertIsNotNone(row["email_verified_at"])
        self.assertEqual(row["email_verified_source"], "google")


class UserInfoFallbackTests(GoogleSignInTestCase):
    """Granular consent can leave the email claim out of the id_token."""

    def test_the_address_is_fetched_when_the_token_omits_it(self):
        self.start_flow()
        with self.client.session_transaction() as browser:
            nonce = browser["oauth_google"]["nonce"]
        claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID,
                  "sub": GOOGLE_SUB, "nonce": nonce, "iat": int(time.time()),
                  "exp": int(time.time()) + 3600}
        response = self.callback(
            token_payload={"id_token": f"h.{b64url(claims)}.s", "access_token": "at"},
            userinfo={"sub": GOOGLE_SUB, "email": GOOGLE_EMAIL,
                      "email_verified": True, "name": "Builder Bot"})
        self.assertEqual(response.headers["Location"], "/auth/google/complete")
        with self.client.session_transaction() as browser:
            self.assertEqual(browser["google_pending"]["email"], GOOGLE_EMAIL)

    def test_a_userinfo_reply_about_a_different_account_is_ignored(self):
        self.start_flow()
        with self.client.session_transaction() as browser:
            nonce = browser["oauth_google"]["nonce"]
        claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID,
                  "sub": GOOGLE_SUB, "nonce": nonce, "iat": int(time.time()),
                  "exp": int(time.time()) + 3600}
        response = self.callback(
            token_payload={"id_token": f"h.{b64url(claims)}.s", "access_token": "at"},
            userinfo={"sub": "a-different-google-account",
                      "email": "victim@gmail.com", "email_verified": True})
        self.assertEqual(response.headers["Location"], "/login")
        self.assertIsNone(self.signed_in_user_id())


class AccountSettingsTests(GoogleSignInTestCase):
    """A password-less account still has to be able to run its own account."""

    def sign_in(self, user):
        with self.client.session_transaction() as browser:
            browser["user_id"] = user["id"]

    def test_a_google_account_is_offered_a_way_to_set_a_password(self):
        user = self.make_user(auth_provider="google", google_sub=GOOGLE_SUB)
        self.sign_in(user)
        page = self.client.get("/account").get_data(as_text=True)
        self.assertIn("Email me a link to set a password", page)
        self.assertNotIn("Type DELETE to confirm", page)

    def test_a_password_account_keeps_the_ordinary_controls(self):
        self.sign_in(self.make_user())
        page = self.client.get("/account").get_data(as_text=True)
        self.assertIn("Type DELETE to confirm", page)
        self.assertIn("Connect Google", page)

    def test_google_cannot_be_disconnected_while_it_is_the_only_way_in(self):
        user = self.make_user(auth_provider="google", google_sub=GOOGLE_SUB)
        self.sign_in(user)
        token = self.csrf("/account")
        self.client.post("/account/google/unlink", data={"csrf_token": token})
        self.assertEqual(self.query("SELECT google_sub FROM users")["google_sub"],
                         GOOGLE_SUB)

    def test_disconnecting_works_once_a_password_exists(self):
        user = self.make_user(google_sub=GOOGLE_SUB)
        self.sign_in(user)
        token = self.csrf("/account")
        self.client.post("/account/google/unlink", data={"csrf_token": token})
        self.assertIsNone(self.query("SELECT google_sub FROM users")["google_sub"])

    def test_connecting_google_requires_the_current_password(self):
        self.sign_in(self.make_user())
        token = self.csrf("/account")
        response = self.client.post("/account/google/link",
                                    data={"password": "wrong", "csrf_token": token})
        self.assertEqual(response.headers["Location"], "/account")

    def test_setting_a_password_graduates_the_account_out_of_google_only(self):
        user = self.make_user(auth_provider="google", google_sub=GOOGLE_SUB,
                              email_verified_at=None)
        self.run_sql(
            "INSERT INTO password_reset_tokens(user_id,token_hash,expires_at) "
            "VALUES (?,?,datetime('now','+30 minutes'))",
            (user["id"], __import__("hashlib").sha256(b"claim").hexdigest()))
        token = self.csrf("/reset-password/claim")
        self.client.post("/reset-password/claim", data={
            "password": "brand-new-password", "confirm_password": "brand-new-password",
            "confirmation": "brand-new-password", "csrf_token": token})
        row = self.query("SELECT * FROM users")
        self.assertEqual(row["auth_provider"], "password")
        self.assertIsNotNone(row["email_verified_at"])
        self.assertTrue(check_password_hash(row["password_hash"],
                                            "brand-new-password"))


    def test_the_right_password_hands_off_to_the_start_route(self):
        """The leg that leaves the site is a navigation, not a POST redirect.

        Our CSP sets form-action 'self', so /account/google/link only records
        that the password checked out and lets the GET route do the departing.
        """
        user = self.make_user(email="chosen@school.org")
        self.sign_in(user)
        token = self.csrf("/account")
        response = self.client.post("/account/google/link",
                                    data={"password": PASSWORD, "csrf_token": token})
        self.assertEqual(response.headers["Location"], "/auth/google/start/link")
        with self.client.session_transaction() as browser:
            self.assertEqual(browser["google_link_ok"]["user_id"], user["id"])

        departure = self.client.get("/auth/google/start/link")
        self.assertTrue(
            departure.headers["Location"].startswith(google_oauth.AUTH_ENDPOINT))
        self.assertEqual(self.flow_state()["link_user_id"], user["id"])
        # Single use: the marker must not survive into a second departure.
        with self.client.session_transaction() as browser:
            self.assertNotIn("google_link_ok", browser)

    def test_a_link_marker_is_worthless_to_the_next_person_at_the_browser(self):
        owner = self.make_user(email="owner@school.org")
        self.sign_in(owner)
        token = self.csrf("/account")
        self.client.post("/account/google/link",
                         data={"password": PASSWORD, "csrf_token": token})
        # Owner leaves, somebody else signs in on the same browser.
        intruder = self.make_user("Intruder", "intruder@school.org")
        self.sign_in(intruder)
        response = self.client.get("/auth/google/start/link")
        self.assertEqual(response.headers["Location"], "/account")
        self.assertEqual(self.flow_state(), {})

    def test_a_stranded_link_marker_does_not_link_on_a_plain_sign_in(self):
        """A 429 on the link route, a back button, a closed tab -- any of them
        leaves the marker behind. The plain route must throw it away rather
        than read it, or the next ordinary click silently connects Google."""
        user = self.make_user(email="chosen@school.org")
        self.sign_in(user)
        token = self.csrf("/account")
        self.client.post("/account/google/link",
                         data={"password": PASSWORD, "csrf_token": token})
        self.client.get("/auth/google/start")
        self.assertNotIn("link_user_id", self.flow_state())
        with self.client.session_transaction() as browser:
            self.assertNotIn("google_link_ok", browser)

    def test_a_deliberate_link_connects_a_google_account_with_another_address(self):
        """The whole escape hatch, end to end: a Botfolio address that is not
        the Google one, and no email match to fall back on."""
        user = self.make_user(email="chosen@school.org")
        self.sign_in(user)
        token = self.csrf("/account")
        self.client.post("/account/google/link",
                         data={"password": PASSWORD, "csrf_token": token})
        self.client.get("/auth/google/start/link")
        response = self.callback(token_payload={
            "id_token": id_token(nonce=self.flow_state()["nonce"]),
            "access_token": "at"})
        self.assertEqual(response.headers["Location"], "/account")
        row = self.query("SELECT * FROM users WHERE id = ?", (user["id"],))
        self.assertEqual(row["google_sub"], GOOGLE_SUB)
        # The address stays the one they chose; linking is not a rename.
        self.assertEqual(row["email"], "chosen@school.org")
        self.assertEqual([mail["subject"] for mail in self.sent_email],
                         ["Google sign-in was connected to your Botfolio account"])

    def test_a_deliberate_link_refuses_a_google_account_already_used(self):
        self.make_user("Owner", "owner@school.org", google_sub=GOOGLE_SUB)
        user = self.make_user("Other", "chosen@school.org")
        self.sign_in(user)
        token = self.csrf("/account")
        self.client.post("/account/google/link",
                         data={"password": PASSWORD, "csrf_token": token})
        self.client.get("/auth/google/start/link")
        response = self.callback(token_payload={
            "id_token": id_token(nonce=self.flow_state()["nonce"]),
            "access_token": "at"})
        self.assertEqual(response.headers["Location"], "/account")
        self.assertIsNone(
            self.query("SELECT * FROM users WHERE id = ?", (user["id"],))["google_sub"])

    def test_a_reset_takes_back_a_google_credential_somebody_else_bolted_on(self):
        """The claim path is only a rescue if the reset ends the intruder's
        access completely. A Google credential they attached outlives both the
        password and the sessions, so it has to go with them."""
        user = self.make_user(google_sub="the-intruders-google-account")
        self._set_password(self._claim_token(user))
        row = self.query("SELECT * FROM users")
        self.assertIsNone(row["google_sub"])
        self.assertEqual(row["auth_provider"], "password")
        self.assertTrue(check_password_hash(row["password_hash"],
                                            "brand-new-password"))

    def test_a_google_only_account_keeps_google_when_it_gains_a_password(self):
        """The exception: this row is not taking itself back from anybody, and
        clearing the only credential it has would strand it."""
        user = self.make_user(auth_provider="google", google_sub=GOOGLE_SUB,
                              email_verified_at=None)
        self._set_password(self._claim_token(user))
        row = self.query("SELECT * FROM users")
        self.assertEqual(row["google_sub"], GOOGLE_SUB)
        self.assertEqual(row["auth_provider"], "password")

    def test_disconnecting_survives_the_feature_being_switched_off(self):
        """Switching Google off must not strand the accounts it connected."""
        user = self.make_user(google_sub=GOOGLE_SUB)
        self.sign_in(user)
        with patch.object(google_oauth.settings, "google_client_id", ""):
            page = self.client.get("/account").get_data(as_text=True)
            self.assertIn("Disconnect Google", page)
            self.assertNotIn("Connect Google", page)
            self.client.post("/account/google/unlink",
                             data={"csrf_token": self.csrf("/account")})
        self.assertIsNone(self.query("SELECT google_sub FROM users")["google_sub"])

    def test_an_account_already_linked_elsewhere_is_not_taken_over(self):
        """The (b) race: verified email matches, but the row got linked first."""
        self.make_user(google_sub="a-google-account-linked-a-moment-ago")
        self.start_flow()
        response = self.callback(token_payload={
            "id_token": id_token(nonce=self.flow_state()["nonce"]),
            "access_token": "at"})
        self.assertEqual(response.headers["Location"], "/login")
        self.assertIsNone(self.signed_in_user_id())
        self.assertEqual(self.query("SELECT google_sub FROM users")["google_sub"],
                         "a-google-account-linked-a-moment-ago")
        # Not the "never been verified" claim path: no claim mail goes out.
        self.assertEqual(self.sent_email, [])


class SourceGuardTests(unittest.TestCase):
    """Rules that a future edit could quietly undo."""

    def test_the_id_token_decoder_keeps_exactly_one_caller(self):
        """Its trust comes from the channel, not the signature -- see the
        module docstring. A second caller would be a forgery hole."""
        sources = [p.read_text(encoding="utf-8")
                   for p in (REPO_ROOT / "services").glob("*.py")]
        sources += [p.read_text(encoding="utf-8")
                    for p in (REPO_ROOT / "routes").glob("*.py")]
        sources.append((REPO_ROOT / "app.py").read_text(encoding="utf-8"))
        callers = sum(len(re.findall(r"_claims_from_id_token\(", source))
                      for source in sources)
        self.assertEqual(
            callers, 2,
            "_claims_from_id_token must keep one definition and one call site")

    def test_no_google_credential_is_hardcoded(self):
        """This repository is public, so a real client id or secret in a
        tracked file is leaked the moment it is pushed. settings and the
        example env file are in scope: a "temporary" default lands there."""
        for name in ("services/google_oauth.py", "routes/google_signin.py",
                     "infra/settings.py", "app.py", ".env.example",
                     "templates/login.html", "templates/account.html",
                     "templates/google_complete.html"):
            source = (REPO_ROOT / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertNotIn("apps.googleusercontent.com", source)
                self.assertNotIn("GOCSPX", source)

    def test_the_deletion_wipe_clears_the_uniquely_indexed_google_column(self):
        source = (REPO_ROOT / "routes" / "auth.py").read_text(encoding="utf-8")
        wipe = re.search(r"UPDATE users SET username=\?.*?WHERE id=\?", source,
                         re.S)
        self.assertIsNotNone(wipe)
        self.assertIn("google_sub=NULL", wipe.group(0))

    def test_the_flow_secrets_are_never_logged(self):
        """A log line may *name* a token; it may never be handed one.

        Parsed rather than read line by line, and across both modules. The one
        call that logs Google's HTTP status spills onto a continuation line, so
        a per-line scan sees the "logger." and none of the arguments under it
        -- the shape of gap that lets a real leak in unnoticed.

        The format string is exempt: "Google id_token rejected" is fine, and
        `logger.warning(msg, id_token)` is not.
        """
        methods = {"debug", "info", "warning", "error", "exception", "critical"}
        # Bare names, because these are the locals that hold the values.
        # Attributes are judged separately: exc.code is an HTTP status, and the
        # authorization code is a local called code.
        secret_names = {"code", "verifier", "nonce", "state", "claims",
                        "payload", "identity", "pending", "raw_token",
                        "id_token", "access_token", "client_secret"}
        secret_attributes = {"id_token", "access_token", "client_secret",
                             "verifier", "password_hash"}
        for name in ("services/google_oauth.py", "routes/google_signin.py"):
            tree = ast.parse((REPO_ROOT / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                if not isinstance(function, ast.Attribute):
                    continue
                if function.attr not in methods:
                    continue
                if "logger" not in ast.unparse(function.value):
                    continue
                rendered = list(node.args[1:]) + [k.value for k in node.keywords]
                for argument in rendered:
                    for inner in ast.walk(argument):
                        with self.subTest(call=ast.unparse(node)):
                            if isinstance(inner, ast.Name):
                                self.assertNotIn(inner.id, secret_names)
                            if isinstance(inner, ast.Attribute):
                                self.assertNotIn(inner.attr, secret_attributes)


if __name__ == "__main__":
    unittest.main()


class TokenExchangeTests(GoogleSignInTestCase):
    """What we send Google is as much of the protocol as what we accept back."""

    def test_the_exchange_carries_the_code_the_secret_and_the_verifier(self):
        user = self.make_user(google_sub=GOOGLE_SUB)
        self.start_flow()
        pending = self.flow_state()
        seen = {}

        def fake_urlopen(request, timeout=None, context=None):
            seen["url"] = request.full_url
            seen["method"] = request.get_method()
            seen["headers"] = dict(request.headers)
            seen["fields"] = dict(
                urllib.parse.parse_qsl(request.data.decode("ascii")))
            return _Response({"id_token": id_token(nonce=pending["nonce"]),
                              "access_token": "at"})

        with patch("services.google_oauth.urllib.request.urlopen", fake_urlopen), \
                patch.object(self.application.email_service, "send_email",
                             side_effect=self.record_email):
            self.client.get("/auth/google/callback?" + urllib.parse.urlencode(
                {"state": pending["state"], "code": "authorization-code"}))

        self.assertEqual(self.signed_in_user_id(), user["id"])
        self.assertEqual(seen["url"], google_oauth.TOKEN_ENDPOINT)
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["fields"]["grant_type"], "authorization_code")
        self.assertEqual(seen["fields"]["code"], "authorization-code")
        self.assertEqual(seen["fields"]["client_id"], CLIENT_ID)
        self.assertEqual(seen["fields"]["client_secret"], CLIENT_SECRET)
        # Byte-identical to the authorization request, or Google says
        # invalid_grant -- and PKCE is worthless if the verifier is not sent.
        self.assertEqual(seen["fields"]["redirect_uri"], REDIRECT_URI)
        self.assertEqual(seen["fields"]["code_verifier"], pending["verifier"])

    def test_the_access_token_goes_in_a_header_not_the_query_string(self):
        """As a query parameter it lands in every log and proxy on the way."""
        self.start_flow()
        nonce = self.flow_state()["nonce"]
        claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID,
                  "sub": GOOGLE_SUB, "nonce": nonce, "iat": int(time.time()),
                  "exp": int(time.time()) + 3600}
        seen = []

        def fake_urlopen(request, timeout=None, context=None):
            seen.append(request)
            if len(seen) == 1:
                return _Response({"id_token": f"h.{b64url(claims)}.s",
                                  "access_token": "the-access-token"})
            return _Response({"sub": GOOGLE_SUB, "email": GOOGLE_EMAIL,
                              "email_verified": True})

        with patch("services.google_oauth.urllib.request.urlopen", fake_urlopen):
            self.client.get("/auth/google/callback?" + urllib.parse.urlencode(
                {"state": self.flow_state()["state"], "code": "authorization-code"}))

        self.assertEqual(len(seen), 2)
        userinfo = seen[1]
        self.assertEqual(userinfo.full_url, google_oauth.USERINFO_ENDPOINT)
        self.assertNotIn("the-access-token", userinfo.full_url)
        self.assertEqual(userinfo.headers["Authorization"],
                         "Bearer the-access-token")


class RateLimitTests(GoogleSignInTestCase):
    """The limits are decorators, and a wrong argument makes them no-ops."""

    def test_the_start_route_stops_answering_when_it_is_hammered(self):
        """methods=("GET",) is the whole point: the decorator counts POSTs by
        default, and this route only ever answers GET."""
        statuses = [self.client.get("/auth/google/start").status_code
                    for _ in range(20)]
        self.assertEqual(statuses[0], 302)
        self.assertIn(429, statuses)

    def test_the_callback_route_is_limited_too(self):
        statuses = [self.client.get("/auth/google/callback").status_code
                    for _ in range(30)]
        self.assertIn(429, statuses)


class TokenDecoderTests(unittest.TestCase):
    """_claims_from_id_token on its own, for the cases a route cannot stage."""

    def setUp(self):
        self.patcher = patch.object(
            google_oauth.settings, "google_client_id", CLIENT_ID)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_an_empty_expectation_never_matches(self):
        """compare_digest("", "") is true, so an empty expected nonce would
        accept a token carrying none -- the check switching itself off in
        exactly the situation it exists for."""
        with self.assertRaises(google_oauth.GoogleAuthError):
            google_oauth._claims_from_id_token(id_token(), "")

    def test_a_matching_nonce_is_accepted(self):
        claims = google_oauth._claims_from_id_token(
            id_token(nonce="the-nonce"), "the-nonce")
        self.assertEqual(claims["sub"], GOOGLE_SUB)

    def test_a_token_that_is_not_three_parts_is_refused(self):
        for bad in ("", "one.two", "a.b.c.d", "not-a-token"):
            with self.subTest(token=bad):
                with self.assertRaises(google_oauth.GoogleAuthError):
                    google_oauth._claims_from_id_token(bad, "the-nonce")

    def test_a_payload_that_is_not_an_object_is_refused(self):
        token = f"{b64url({'alg': 'RS256'})}.{b64url([1, 2, 3])}.sig"
        with self.assertRaises(google_oauth.GoogleAuthError):
            google_oauth._claims_from_id_token(token, "the-nonce")
