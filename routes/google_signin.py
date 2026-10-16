"""Sign in with Google: the account half of the flow.

The protocol lives in services/google_oauth.py. What is left here is the only
interesting question -- what a verified Google identity is allowed to do to a
Botfolio account -- and the answer is deliberately narrow:

    Google is a credential, not a consent authority, and `sub` is the only
    identity key.

So this module never creates a user row inside the OAuth callback and never
mints legal consent. A validated identity resolves to exactly one of four
outcomes:

  * it matches a linked row              -> sign in, mutate nothing
  * it matches an email Botfolio itself
    has proven                           -> attach the credential, sign in
  * it matches an email Botfolio has
    never proven                         -> refuse, and email that inbox a link
                                            to claim the account
  * it matches nothing                    -> park it and collect the same three
                                            legal confirmations registration
                                            collects, before any row exists

The third outcome is what closes the OAuth "pre-hijacking" attack: an attacker
who registered an account under someone else's address gains nothing, because
the claim mail goes to the address's real owner, and their reset deletes the
attacker's sessions.
"""

import hashlib
import hmac
import re
import secrets
import time

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from app import (
    LEGAL_NOTICE_VERSION, PRIVACY_VERSION, TERMS_VERSION, app, current_user, db,
    email_service, login_required, moderate_public_content, ratelimit,
    record_security_event, restore_expired_suspension, safe_next_target,
    start_authenticated_session, suspension_has_expired,
)
from infra.settings import settings
from routes.auth import finish_sign_in
from services import google_oauth

google_bp = Blueprint("google_signin", __name__)

# How long a half-finished flow stays usable. Long enough to read a consent
# screen and pick an account, short enough that an abandoned tab is not a
# standing invitation.
FLOW_TTL_SECONDS = 900
# The completion screen is a longer wait on purpose: it asks somebody to read
# the Terms and the Privacy Policy before ticking three boxes, and timing that
# out underneath them loses the Google identity they already consented to hand
# over, for no security gain -- the identity is held in a signed session the
# browser cannot edit.
PENDING_TTL_SECONDS = 1800
USERNAME_PATTERN = r"[A-Za-z0-9_.-]{3,24}"

RESTRICTED_MESSAGE = (
    "This account is restricted. Contact support if you believe this is an error."
)
GENERIC_FAILURE = "Sign-in could not be completed. Please try again."

# Google's documented callback errors. access_denied is somebody pressing
# Cancel -- an ordinary action, and it must not read like a fault. The
# error_description Google also sends is never shown: it can echo submitted
# values back onto our own page.
ERROR_MESSAGES = {
    "access_denied": "Sign-in with Google was cancelled.",
    "admin_policy_enforced": "Your Google Workspace administrator has blocked this sign-in.",
    "org_internal": "Your Google Workspace administrator has blocked this sign-in.",
    "disallowed_useragent": "Google refused to sign in from this browser. Try opening Botfolio in Chrome, Safari, or Firefox.",
    "server_error": "Google could not complete the sign-in. Please try again.",
    "temporarily_unavailable": "Google sign-in is temporarily unavailable. You can sign in with your password.",
}


# ---------------------------------------------------------------- plumbing


def _require_enabled():
    """A deploy with no credentials behaves as though the feature never shipped."""
    if not settings.google_oauth_enabled:
        abort(404)


def _failure(message, linking=False):
    """Always leave the callback by redirecting, never by rendering.

    The authorization code arrives in the query string. A 302 gets it out of
    the address bar and out of the Referer header of whatever loads next.

    Somebody halfway through connecting Google to an account they are already
    signed into has no business being dropped on the sign-in page, so a link
    flow goes back where it started.
    """
    flash(message, "error")
    if linking and current_user():
        return redirect(url_for("account_settings"))
    return redirect(url_for("login"))


def _begin_flow(extra=None):
    """Mint the one-time values, remember them, and hand back Google's URL."""
    flow = google_oauth.new_flow_secrets()
    pending = dict(flow)
    pending["ts"] = int(time.time())
    pending.update(extra or {})
    session["oauth_google"] = pending
    return redirect(
        google_oauth.authorization_url(flow["state"], flow["nonce"], flow["verifier"]),
        code=302,
    )


def _account_state(user):
    """(user, response) -- the response is set when the account may not sign in.

    Byte-for-byte the check password login performs, applied before any UPDATE
    and before any session. Without it, Google sign-in would be one-click ban
    evasion.
    """
    if suspension_has_expired(user):
        user = restore_expired_suspension(user)
    if user["suspended_at"] or user["banned_at"] or user["deleted_at"]:
        record_security_event("login_rejected_restricted", user["id"])
        return user, _failure(RESTRICTED_MESSAGE)
    return user, None


def _has_real_inbox_proof(user):
    """Did Botfolio itself ever prove this address, or did a backfill say so?

    _ensure_runtime_schema runs, on every boot,

        UPDATE users SET email_verified_at=created_at
         WHERE email_verified_at IS NULL AND accepted_terms_version IS NULL

    which stamps verification onto old rows with no inbox proof whatsoever, so
    the date alone means nothing here. The backfill records that it was the
    author, and this reads that record.

    It is a stored fact and not an inference on purpose. Inferring it from
    "verified but no accepted terms version" was wrong twice over: any later
    legal acknowledgement filled that column in and silently promoted a
    never-proven row to proven, and a row that had genuinely proved itself by
    following a claim link stayed unproven for want of consent it was never
    asked for -- so the claim mail, which promises Google will work
    afterwards, went out again and again.
    """
    return bool(user["email_verified_at"]
                and user["email_verified_source"] != "backfill")


def _notify_link(user):
    """Tell the account holder out-of-band that a new credential now works."""
    email_service.send_email(
        to_email=user["email"],
        to_name=user["username"],
        subject="Google sign-in was connected to your Botfolio account",
        heading="Google sign-in connected",
        message=(
            "You can now sign in to Botfolio with your Google account. Your "
            "password still works and nothing else about your account has "
            "changed. If this was not you, contact support straight away."
        ),
        event_type="security_notice",
    )


def _send_claim_email(conn, user):
    """The existing password-reset machinery, with claim-flavoured copy."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    conn.execute(
        "UPDATE password_reset_tokens SET used_at = datetime('now') "
        "WHERE user_id = ? AND used_at IS NULL",
        (user["id"],),
    )
    conn.execute(
        "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) "
        "VALUES (?, ?, datetime('now', '+30 minutes'))",
        (user["id"], token_hash),
    )
    conn.commit()
    sent = email_service.send_email(
        to_email=user["email"],
        to_name=user["username"],
        subject="Claim your Botfolio account",
        heading="Set a password to claim this account",
        message=(
            "Someone just signed in with Google using this email address, and a "
            "Botfolio account already uses it. Choose a password to claim the "
            "account -- after that, Sign in with Google will work too. This "
            "link expires in 30 minutes and can only be used once. If this was "
            "not you, you can ignore this email; nothing has changed."
        ),
        action_url=url_for("reset_password", token=raw_token, _external=True),
        action_text="Set a password",
        event_type="password_reset",
    )
    if not sent:
        # The person is told the same thing either way, which also hides a
        # broken mailer from the one party who could fix it. Say so in the log.
        app.logger.error("Google claim email could not be sent to user %s", user["id"])


def _suggest_username(conn, email):
    """A starting point only -- always editable, always re-validated server-side."""
    base = re.sub(r"[^a-z0-9_.\-]", "", (email or "").partition("@")[0].lower())[:24]
    if len(base) < 3:
        base = (base + "user")[:24]
    candidate, suffix = base, 1
    while conn.execute(
        "SELECT 1 FROM users WHERE lower(username) = lower(?)", (candidate,)
    ).fetchone():
        suffix += 1
        tail = str(suffix)
        candidate = base[: 24 - len(tail)] + tail
    return candidate


# ------------------------------------------------------------------ routes


@google_bp.route("/auth/google/start")
# methods=("GET",) is not optional: the decorator counts POSTs by default and
# would be a silent no-op on this route. Matched to /login's own allowance,
# because anonymous callers are keyed by IP and a whole school shares one --
# and a sign-in here spends two rate-limited GETs, not one.
@ratelimit.limit("google-start", 12, 300, methods=("GET",))
def google_login():
    """Plain sign-in. This route never links, whatever the session holds."""
    _require_enabled()
    # Linking has its own route, and the marker is discarded here rather than
    # read. Otherwise anything that stranded a marker -- a 429 on the link
    # route, a back button, a closed tab -- would turn the next person's
    # ordinary sign-in click into a silent account link.
    session.pop("google_link_ok", None)
    return _begin_flow({"next": safe_next_target(request.args.get("next")) or ""})


@google_bp.route("/auth/google/start/link")
@login_required
@ratelimit.limit("google-link-start", 5, 3600, methods=("GET",))
def google_link_start():
    """The second leg of an account-initiated link: password already checked."""
    _require_enabled()
    # Set by google_link(). Single use, and only honoured for the account that
    # is signed in right now, so a marker left behind on a shared browser is
    # worthless to whoever sits down next.
    authorized = session.pop("google_link_ok", None)
    viewer = current_user()
    if (authorized and viewer and viewer["id"] == authorized.get("user_id")
            and int(time.time()) - int(authorized.get("ts", 0)) <= FLOW_TTL_SECONDS):
        return _begin_flow({"next": "", "link_user_id": viewer["id"]})
    return _failure(GENERIC_FAILURE, linking=True)


@google_bp.route("/auth/google/callback")
@ratelimit.limit("google-callback", 20, 600, methods=("GET",))
def google_callback():
    _require_enabled()
    pending = session.get("oauth_google") or None
    if not pending:
        return _failure("That sign-in attempt expired. Please try again.")
    # Checked before anything else is read, so an unsolicited callback -- login
    # CSRF, or a forged error= -- is discarded without side effects. Google
    # echoes state on its error responses too, so this ordering costs nothing.
    #
    # And checked before the flow is discarded, not after: a stranger who can
    # make this browser fetch the callback URL must not be able to cancel a
    # sign-in that is legitimately in progress just by guessing wrong.
    if not hmac.compare_digest(
        request.args.get("state") or "", str(pending.get("state") or "")
    ):
        record_security_event("google_oauth_state_mismatch")
        return _failure(GENERIC_FAILURE)
    # The state matched, so this is our own flow coming back. Single use from
    # here on, and gone before start_authenticated_session(), which clears the
    # session anyway.
    session.pop("oauth_google", None)
    linking = bool(pending.get("link_user_id"))
    if int(time.time()) - int(pending.get("ts", 0)) > FLOW_TTL_SECONDS:
        return _failure("That sign-in attempt expired. Please try again.", linking)

    error = request.args.get("error")
    if error:
        record_security_event("google_oauth_error", details={"error": error[:64]})
        return _failure(
            ERROR_MESSAGES.get(error, "Sign-in was not completed."), linking)
    code = request.args.get("code")
    if not code:
        return _failure("Sign-in was not completed.", linking)

    try:
        identity = google_oauth.identity_from_code(
            code, pending.get("verifier") or "", pending.get("nonce") or ""
        )
    except google_oauth.GoogleAuthError as exc:
        return _failure(str(exc), linking)

    if linking:
        return _deliberate_link(pending["link_user_id"], identity)
    return _resolve(identity, safe_next_target(pending.get("next")))


def _resolve(identity, target):
    """Four outcomes, and the callback creates a row in none of them."""
    conn = db.get_db()

    # (a) We have seen this Google account before. sub is the identity; an
    # address that has changed under it is a profile fact about the same
    # person, never a different person -- and users.email is the reset address
    # they may have deliberately chosen, so it is not overwritten from a claim.
    user = conn.execute(
        "SELECT * FROM users WHERE google_sub = ?", (identity["sub"],)
    ).fetchone()
    if user:
        user, refused = _account_state(user)
        if refused:
            return refused
        if (user["email"] or "").lower() != identity["email"]:
            record_security_event("google_signin_email_drift", user["id"])
        record_security_event("google_signin_succeeded", user["id"])
        return finish_sign_in(user, target)

    match = conn.execute(
        "SELECT * FROM users WHERE lower(email) = ? AND deleted_at IS NULL",
        (identity["email"],),
    ).fetchone()
    if match:
        match, refused = _account_state(match)
        if refused:
            return refused
        if _has_real_inbox_proof(match):
            # (b) Botfolio has already proven this inbox, and forgot_password
            # hands whoever controls it the whole account anyway. So linking on
            # the strength of the same proof buys no security to withhold.
            # Nothing else is touched: not the password, not the sessions, not
            # the address. Destroying a credential the person may still be
            # using is not a safety measure.
            cursor = conn.execute(
                "UPDATE users SET google_sub = ? WHERE id = ? AND google_sub IS NULL",
                (identity["sub"], match["id"]),
            )
            conn.commit()
            linked = cursor.rowcount
            if not linked:
                # A concurrent request got there first. Re-read rather than
                # overwrite: if it linked this same Google account the outcome
                # is simply (a), and if it linked a different one this row is
                # already spoken for and must not be taken from it.
                match = conn.execute(
                    "SELECT * FROM users WHERE id = ?", (match["id"],)
                ).fetchone()
                if match["google_sub"] != identity["sub"]:
                    return _failure(
                        "That Botfolio account is already connected to a "
                        "different Google account. Sign in with your password "
                        "instead."
                    )
            record_security_event("google_account_linked", match["id"])
            _notify_link(match)
            return finish_sign_in(
                match, target,
                f"Signed in as {match['username']}. "
                "Google is now connected to this account.",
            )
        # (c) Nobody has ever proven this inbox -- so an attacker may have
        # registered it. Write nothing, and do not dead-end either: Google has
        # just proven the person at the keyboard controls the address, so the
        # claim mail lands in their own hands.
        return _claim_by_email(conn, match, identity["email"])

    # (d) A new person. Park the identity in the signed session -- the browser
    # cannot forge a different email into it -- and go and collect consent.
    session["google_pending"] = {
        "sub": identity["sub"],
        "email": identity["email"],
        "name": identity["name"],
        "next": target or "",
        "ts": int(time.time()),
    }
    return redirect(url_for("google_complete"))


def _claim_by_email(conn, user, email):
    record_security_event("google_link_refused_unverified_email", user["id"])
    # The callback can now send mail to an address its caller chose, so bound
    # it: an unused, unexpired token already in flight is the natural throttle.
    outstanding = conn.execute(
        "SELECT id FROM password_reset_tokens WHERE user_id = ? AND used_at IS NULL "
        "AND expires_at > datetime('now')",
        (user["id"],),
    ).fetchone()
    if not outstanding:
        _send_claim_email(conn, user)
    flash(
        f"An account already uses {email} and that address has never been "
        "verified. We have emailed it a link to set a password and claim the "
        "account -- after that, Sign in with Google will work.",
        "error",
    )
    return redirect(url_for("login"))


def _deliberate_link(user_id, identity):
    """The escape hatch for someone whose Botfolio address is not their Google one."""
    viewer = current_user()
    if not viewer or viewer["id"] != user_id:
        return _failure(GENERIC_FAILURE)
    conn = db.get_db()
    taken = conn.execute(
        "SELECT id FROM users WHERE google_sub = ? AND id <> ?",
        (identity["sub"], user_id),
    ).fetchone()
    if not taken:
        try:
            conn.execute(
                # The unique index on google_sub is the real arbiter; the SELECT
                # above exists only to phrase the common case nicely. Between
                # the two a concurrent link can take the sub, so catch that
                # rather than let the constraint surface as a 500.
                "UPDATE users SET google_sub = ? WHERE id = ?",
                (identity["sub"], user_id),
            )
            conn.commit()
        except db.INTEGRITY_ERRORS:
            conn.rollback()
            taken = True
    if taken:
        flash(
            "That Google account is already connected to another Botfolio account.",
            "error",
        )
        return redirect(url_for("account_settings"))
    record_security_event("google_account_linked", user_id)
    _notify_link(viewer)
    flash("Google is now connected to your account.", "success")
    return redirect(url_for("account_settings"))


@google_bp.route("/auth/google/complete", methods=["GET", "POST"])
# Google must not be a way around the signup limit.
@ratelimit.limit("register", 5, 3600)
def google_complete():
    _require_enabled()
    pending = session.get("google_pending")
    if not pending or int(time.time()) - int(pending.get("ts", 0)) > PENDING_TTL_SECONDS:
        session.pop("google_pending", None)
        return _failure("That sign-in attempt expired. Please try again.")

    conn = db.get_db()
    email = pending["email"]
    username = (request.form.get("username") or "").strip()

    if request.method == "POST":
        error = None
        if not re.fullmatch(USERNAME_PATTERN, username):
            error = "Usernames are 3-24 characters: letters, numbers, _ . - only."
        elif request.form.get("age_13_confirmed") != "yes":
            error = "Botfolio accounts are available only to users age 13 or older."
        elif request.form.get("legal_policies_accepted") != "yes":
            error = "You must agree to the Terms of Use and Privacy Policy."
        elif request.form.get("minor_permission_confirmed") != "yes":
            error = "You must confirm the parent-or-guardian permission requirement."

        if error is None:
            try:
                # It becomes public text the moment the profile exists.
                moderate_public_content(texts=[username], use_api=not app.testing)
            except ValueError as exc:
                error = str(exc)

        if error is None:
            # Re-run the clash query: a local account may have appeared while
            # this screen was open.
            clash = conn.execute(
                "SELECT * FROM users WHERE lower(username) = lower(?) "
                "OR lower(email) = lower(?)",
                (username, email),
            ).fetchone()
            if clash and (clash["email"] or "").lower() == email:
                # Somebody registered this address in the interval, so this is
                # outcome (b) or (c) after all.
                session.pop("google_pending", None)
                return _resolve(
                    {"sub": pending["sub"], "email": email, "name": pending.get("name", "")},
                    safe_next_target(pending.get("next")),
                )
            if clash:
                error = "That username or email is already registered."

        if error is None:
            try:
                cursor = conn.execute(
                    "INSERT INTO users (username,email,password_hash,is_admin,onboarding_complete,"
                    "accepted_terms_version,accepted_privacy_version,accepted_terms_at,accepted_privacy_at,"
                    "acknowledged_legal_version,acknowledged_legal_at,age_13_confirmed,"
                    "minor_permission_confirmed,registration_ip,google_sub,auth_provider,email_verified_at,"
                    # Google proved this inbox, and the column has to say so:
                    # a NULL here is read as "verified before the column
                    # existed", and 'backfill' as "never actually proven".
                    "email_verified_source) "
                    "VALUES (?,?,?,0,0,?,?,datetime('now'),datetime('now'),?,datetime('now'),1,1,?,?,'google',datetime('now'),"
                    "'google')",
                    (
                        username, email,
                        # A real hash of a value nobody holds: it satisfies the
                        # NOT NULL column while check_password_hash can never
                        # pass. Setting a password is a separate, deliberate act.
                        generate_password_hash(secrets.token_urlsafe(32)),
                        TERMS_VERSION, PRIVACY_VERSION, LEGAL_NOTICE_VERSION,
                        request.remote_addr, pending["sub"],
                    ),
                )
                conn.commit()
            except db.INTEGRITY_ERRORS:
                # Two signups racing, or a row the check above could not see.
                # An unhandled raise here is a 500 page shown for what is only
                # ever "that name is taken".
                conn.rollback()
                error = "That username or email is already registered."
            else:
                new_id = cursor.lastrowid
                record_security_event(
                    "account_registered", new_id, details={"provider": "google"}
                )
                target = safe_next_target(pending.get("next"))
                session.pop("google_pending", None)
                # Clears the session, so everything below has to come after it.
                start_authenticated_session(new_id)
                flash(f"Welcome, {username}!", "success")
                if target:
                    session["post_signup_next"] = target
                # onboarding_complete=0 sends them through the existing three
                # screens; no new onboarding code is needed.
                return redirect(url_for("account_setup"))

        flash(error, "error")

    return render_template(
        "google_complete.html",
        google_email=email,
        google_name=pending.get("name") or "",
        suggested_username=username or _suggest_username(conn, email),
    )


@google_bp.route("/account/google/link", methods=["POST"])
@login_required
@ratelimit.limit("google-link", 5, 3600)
def google_link():
    """Connect Google to an account whose Botfolio address is a different one."""
    _require_enabled()
    user = current_user()
    password = request.form.get("password") or ""
    if not check_password_hash(user["password_hash"] or "", password):
        flash("Your current password was incorrect. Google was not connected.", "error")
        return redirect(url_for("account_settings"))
    # Hand off to the GET route rather than redirecting to Google from here.
    # Our CSP sets form-action 'self', and browsers have historically disagreed
    # about whether that also governs a redirect the POST is answered with --
    # so the leg that actually leaves the site is a plain navigation.
    session["google_link_ok"] = {"user_id": user["id"], "ts": int(time.time())}
    return redirect(url_for("google_link_start"))


@google_bp.route("/account/google/unlink", methods=["POST"])
@login_required
# Deliberately not behind _require_enabled(): taking a credential off your own
# account must keep working even after the feature is switched off, or turning
# it off would strand every link it created.
def google_unlink():
    user = current_user()
    if not user["google_sub"]:
        return redirect(url_for("account_settings"))
    if user["auth_provider"] != "password":
        # This account has never had a password set, so disconnecting Google
        # would leave it with no way in at all.
        flash(
            "Set a password first -- disconnecting Google now would leave you "
            "with no way to sign in.",
            "error",
        )
        return redirect(url_for("account_settings"))
    conn = db.get_db()
    conn.execute("UPDATE users SET google_sub=NULL WHERE id=?", (user["id"],))
    conn.commit()
    record_security_event("google_account_unlinked", user["id"])
    flash("Google is no longer connected to your account.", "success")
    return redirect(url_for("account_settings"))
