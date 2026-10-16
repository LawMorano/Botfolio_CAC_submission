"""Account registration, sign-in, onboarding, and account settings."""

import hashlib
import re
import secrets

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app import (
    ADMIN_EMAIL, ADMIN_USERNAME, FTC_ROLES, LEGAL_CHANGE_SUMMARY,
    LEGAL_NOTICE_VERSION, MODEL_DIR, ONBOARDING_INTERESTS, PRIVACY_VERSION,
    TERMS_VERSION, UPLOAD_DIR, app, current_user, db, delete_asset,
    email_service, login_required, moderate_public_content, ratelimit,
    record_security_event, restore_expired_suspension,
    revoke_authenticated_session, safe_next_target, save_image_upload,
    send_verification_email, start_authenticated_session,
    suspension_has_expired,
)


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/verify-email/<token>")
def verify_email(token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    conn = db.get_db()
    row = conn.execute("SELECT * FROM email_verification_tokens WHERE token_hash=? AND used_at IS NULL AND expires_at>datetime('now')", (token_hash,)).fetchone()
    if row is None:
        flash("That verification link is invalid or expired.", "error")
        return redirect(url_for("login"))
    conn.execute("UPDATE users SET email_verified_at=datetime('now'),email_verified_source='verification' WHERE id=?", (row["user_id"],))
    conn.execute("UPDATE email_verification_tokens SET used_at=datetime('now') WHERE id=?", (row["id"],))
    conn.commit()
    flash("Your email address is verified.", "success")
    return redirect(url_for("index"))

@auth_bp.route("/resend-verification", methods=["GET", "POST"])
@ratelimit.limit("resend-verification", 3, 3600)
@login_required
def resend_verification():
    user = current_user()
    if user["email_verified_at"]:
        return redirect(url_for("index"))
    if request.method == "POST":
        sent = send_verification_email(
            user["id"], user["email"], user["username"]
        )
        if sent:
            flash("A new verification link has been sent.", "success")
        else:
            flash(
                "We could not send the verification email. Please try again "
                "in a few minutes or contact support.",
                "error",
            )
    return render_template("verify_email.html")

@auth_bp.route("/register", methods=["GET", "POST"])
# Each registration sends a verification email. Unlimited, that is a way to use
# this site to send mail to strangers.
@ratelimit.limit("register", 5, 3600)
def register():
    if request.method == "POST":
        if (request.form.get("company") or "").strip():
            # Honeypot: a decoy field hidden from real people (off-screen, not
            # tab-reachable, aria-hidden). Automated signup scripts fill every
            # input they see and trip it. Behave as though it succeeded — no
            # error, no account — so the bot gets no signal to adapt.
            return redirect(url_for("login"))
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        age_13_confirmed = request.form.get("age_13_confirmed") == "yes"
        legal_policies_accepted = request.form.get("legal_policies_accepted") == "yes"
        minor_permission_confirmed = request.form.get("minor_permission_confirmed") == "yes"

        error = None
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,24}", username):
            error = "Usernames are 3-24 characters: letters, numbers, _ . - only."
        elif "@" not in email:
            error = "Please enter a valid email address."
        elif len(password) < 8:
            error = "Passwords must be at least 8 characters."
        elif not age_13_confirmed:
            error = "Botfolio accounts are available only to users age 13 or older."
        elif not legal_policies_accepted:
            error = "You must agree to the Terms of Use and Privacy Policy."
        elif not minor_permission_confirmed:
            error = "You must confirm the parent-or-guardian permission requirement."

        if error is None:
            try:
                moderate_public_content(texts=[username], use_api=not app.testing)
            except ValueError as exc:
                error = str(exc)

        if error is None:
            conn = db.get_db()
            clash = conn.execute(
                "SELECT id FROM users WHERE lower(username) = lower(?) "
                "OR lower(email) = lower(?)",
                (username, email),
            ).fetchone()
            if clash:
                error = "That username or email is already registered."
            else:
                is_admin = int(email.lower() == ADMIN_EMAIL.lower() and username.lower() == ADMIN_USERNAME.lower())
                try:
                    cur = conn.execute(
                        "INSERT INTO users (username,email,password_hash,is_admin,onboarding_complete,accepted_terms_version,accepted_privacy_version,accepted_terms_at,accepted_privacy_at,acknowledged_legal_version,acknowledged_legal_at,age_13_confirmed,minor_permission_confirmed,registration_ip) "
                        "VALUES (?,?,?,?,0,?,?,datetime('now'),datetime('now'),?,datetime('now'),1,1,?)",
                        (username, email, generate_password_hash(password), is_admin,
                         TERMS_VERSION, PRIVACY_VERSION, LEGAL_NOTICE_VERSION, request.remote_addr),
                    )
                    conn.commit()
                except db.INTEGRITY_ERRORS:
                    # The check above and the database's own uniqueness rule can
                    # still disagree: two signups racing, or a row the check
                    # could not see. The database raises rather than returning a
                    # row, and an unhandled raise is a 500 page shown for what is
                    # only ever "that name is taken".
                    conn.rollback()
                    flash("That username or email is already registered.", "error")
                    return render_template("register.html")
                record_security_event("account_registered", cur.lastrowid)
                start_authenticated_session(cur.lastrowid)
                sent = send_verification_email(cur.lastrowid, email, username)
                if sent:
                    flash(f"Welcome, {username}!", "success")
                else:
                    flash(
                        "Your account was created, but the verification email "
                        "could not be sent. You can retry it from your profile.",
                        "error",
                    )
                # Most people who register mid-click were sent here by something
                # that needed an account — a download, usually. Onboarding is
                # three screens long, so remember where they were headed and
                # offer it back at the end instead of stranding them on the home
                # page with no memory of why they signed up.
                target = safe_next_target(
                    request.args.get("next") or request.form.get("next"))
                if target:
                    session["post_signup_next"] = target
                return redirect(url_for("account_setup"))

        flash(error, "error")

    return render_template("register.html")


@auth_bp.route("/account/setup", methods=["GET", "POST"])
@login_required
def account_setup():
    user = current_user()
    if user["onboarding_complete"]:
        return redirect(url_for("profile", username=user["username"]))

    if request.method == "POST":
        display_name = (request.form.get("display_name") or "").strip()[:80]
        bio = (request.form.get("bio") or "").strip()
        try:
            moderate_public_content(texts=[display_name, bio], use_api=not app.testing)
            image = user["profile_image"]
            upload = request.files.get("profile_image")
            if upload and upload.filename:
                image = save_image_upload(upload)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("account_setup"))
        conn = db.get_db()
        conn.execute(
            "UPDATE users SET display_name=?, bio=?, profile_image=? WHERE id=?",
            (display_name, bio, image, user["id"]),
        )
        conn.commit()
        return redirect(url_for("account_setup_interests"))

    return render_template("account_setup.html")


@auth_bp.route("/account/setup/interests", methods=["GET", "POST"])
@login_required
def account_setup_interests():
    user = current_user()
    if user["onboarding_complete"]:
        return redirect(url_for("profile", username=user["username"]))

    if request.method == "POST":
        interests = [
            value for value in request.form.getlist("interests")
            if value in ONBOARDING_INTERESTS
        ]
        if not interests:
            flash("Choose at least one robotics interest.", "error")
        else:
            conn = db.get_db()
            conn.execute(
                "UPDATE users SET interests=? WHERE id=?",
                (", ".join(interests), user["id"]),
            )
            conn.commit()
            return redirect(url_for("account_setup_role"))

    selected_interests = {
        value.strip() for value in (user["interests"] or "").split(",") if value.strip()
    }
    return render_template(
        "account_setup_interests.html",
        interest_choices=ONBOARDING_INTERESTS,
        selected_interests=selected_interests,
    )


@auth_bp.route("/account/setup/role", methods=["GET", "POST"])
@login_required
def account_setup_role():
    user = current_user()
    if user["onboarding_complete"]:
        return redirect(url_for("profile", username=user["username"]))

    if request.method == "POST":
        role = request.form.get("ftc_role")
        if role not in FTC_ROLES:
            flash("Choose the option that best describes your robotics role.", "error")
        else:
            conn = db.get_db()
            conn.execute(
                "UPDATE users SET ftc_role=? WHERE id=?",
                (role, user["id"]),
            )
            conn.commit()
            return redirect(url_for("account_setup_team"))

    return render_template("account_setup_role.html", roles=FTC_ROLES)


@auth_bp.route("/account/setup/team", methods=["GET", "POST"])
@login_required
def account_setup_team():
    """Final onboarding step: ask whether the person competes on an FTC team and,
    if so, which one. The number is stored as their self-declared affiliation so the
    next screen can offer to connect them to that team's Botfolio page. This step
    marks onboarding complete."""
    user = current_user()
    if user["onboarding_complete"]:
        return redirect(url_for("profile", username=user["username"]))

    if request.method == "POST":
        on_team = request.form.get("on_team")
        team_number = None
        if on_team == "yes":
            raw = (request.form.get("ftc_team_number") or "").strip()
            if not raw.isdigit() or not (1 <= int(raw) <= 99999):
                flash("Enter your FTC team number (1–99999), or choose “Not right now”.", "error")
                return render_template("account_setup_team.html")
            team_number = int(raw)
        elif on_team != "no":
            flash("Let us know whether you're on an FTC team.", "error")
            return render_template("account_setup_team.html")

        conn = db.get_db()
        conn.execute(
            "UPDATE users SET ftc_team_number=?, onboarding_complete=1 WHERE id=?",
            (team_number, user["id"]),
        )
        conn.commit()
        flash("Your personal profile is ready.", "success")
        return redirect(url_for("onboarding_team"))

    return render_template("account_setup_team.html")


@auth_bp.route("/welcome/team")
@login_required
def onboarding_team():
    """Onboarding step 2: connect to a team (or skip). Reached after the personal
    profile is created; the person-vs-team distinction is set by the product flow.
    If the person declared an FTC team number during setup, offer a one-click way to
    request to join that team's Botfolio page."""
    user = current_user()
    declared_number = user["ftc_team_number"]
    declared_team = None
    declared_state = None  # member | pending | joinable | unowned | absent
    if declared_number:
        conn = db.get_db()
        declared_team = conn.execute(
            "SELECT * FROM teams WHERE program='ftc' AND number=?", (declared_number,)
        ).fetchone()
        if declared_team is None:
            declared_state = "absent"
        elif conn.execute(
            "SELECT 1 FROM memberships WHERE team_id=? AND user_id=?",
            (declared_team["id"], user["id"]),
        ).fetchone():
            declared_state = "member"
        elif conn.execute(
            """SELECT 1 FROM team_membership_requests
                WHERE team_id=? AND user_id=? AND status='pending'""",
            (declared_team["id"], user["id"]),
        ).fetchone():
            declared_state = "pending"
        elif declared_team["owner_id"] is None:
            declared_state = "unowned"
        else:
            declared_state = "joinable"
    return render_template(
        "onboarding_team.html",
        declared_number=declared_number,
        declared_team=declared_team,
        declared_state=declared_state,
    )


@auth_bp.route("/welcome/explore")
@login_required
def onboarding_explore():
    """Onboarding step 3: suggested next actions once the profile (and optionally a
    team) are set."""
    return render_template("onboarding_explore.html",
                           post_signup_next=session.get("post_signup_next"))


def finish_sign_in(user, target, message=None):
    """Start the session and send the user on, identically for every credential.

    Extracted from login() so that "a Google sign-in ends exactly the way a
    password sign-in ends" is true by construction rather than by review: both
    callers run this same body, so the legal-acknowledgement gate and the
    next-target handling cannot drift apart.

    start_authenticated_session() clears the Flask session first -- that is the
    session-fixation defence -- so nothing may be stashed in the session, and
    nothing may be flashed, before it runs.
    """
    start_authenticated_session(user["id"])
    flash(message or f"Signed in as {user['username']}.", "success")
    if user["acknowledged_legal_version"] != LEGAL_NOTICE_VERSION:
        if target:
            session["legal_update_next"] = target
        return redirect(url_for("legal_updates"))
    # Only ever redirect within this site.
    if target:
        return redirect(target)
    return redirect(url_for("index"))


@auth_bp.route("/login", methods=["GET", "POST"])
# Password guessing is the whole reason this limit exists. Twelve attempts per
# five minutes is far more than a person who has forgotten their password
# needs, and far less than a script needs to be worth running.
@ratelimit.limit("login", 12, 300)
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        user = db.get_db().execute(
            "SELECT * FROM users WHERE lower(username) = lower(?) "
            "OR lower(email) = lower(?)",
            (username, username),
        ).fetchone()

        if user and suspension_has_expired(user):
            user = restore_expired_suspension(user)

        if user and (user["suspended_at"] or user["banned_at"] or user["deleted_at"]):
            record_security_event("login_rejected_restricted", user["id"])
            flash("This account is restricted. Contact support if you believe this is an error.", "error")
        elif user and check_password_hash(user["password_hash"], password):
            record_security_event("login_succeeded", user["id"])
            return finish_sign_in(user, safe_next_target(
                request.args.get("next") or request.form.get("next")))
        else:
            record_security_event("login_failed", user["id"] if user else None)

        flash("Incorrect username or password.", "error")

    return render_template("login.html")


@auth_bp.route("/legal-updates", methods=["GET", "POST"])
@login_required
def legal_updates():
    user = current_user()
    if request.method == "POST":
        conn = db.get_db()
        conn.execute(
            """UPDATE users SET acknowledged_legal_version=?,acknowledged_legal_at=datetime('now'),
                   accepted_terms_version=?,accepted_terms_at=datetime('now'),
                   accepted_privacy_version=?,accepted_privacy_at=datetime('now') WHERE id=?""",
            (LEGAL_NOTICE_VERSION, TERMS_VERSION, PRIVACY_VERSION, user["id"]),
        )
        conn.commit()
        flash("Legal update acknowledged.", "success")
        return redirect(session.pop("legal_update_next", None) or url_for("index"))
    return render_template(
        "legal_updates.html", legal_version=LEGAL_NOTICE_VERSION,
        change_summary=LEGAL_CHANGE_SUMMARY,
    )


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
# Same reasoning as /register: this one posts an address and this site emails
# it. The limit is what stops that being a free mailing service.
@ratelimit.limit("forgot-password", 5, 3600)
def forgot_password():
    if request.method == "POST":
        # Honeypot: a decoy field hidden from real people. A bot that fills every
        # input trips it. Fall through to the same generic response below without
        # touching the database or sending mail, so it looks identical to a
        # normal request and the bot learns nothing.
        tripped_honeypot = bool((request.form.get("company") or "").strip())
        email = (request.form.get("email") or "").strip()
        conn = db.get_db()
        user = None if tripped_honeypot else conn.execute(
            "SELECT * FROM users WHERE lower(email) = lower(?)", (email,)
        ).fetchone()

        if user:
            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            conn.execute(
                "UPDATE password_reset_tokens SET used_at = datetime('now') "
                "WHERE user_id = ? AND used_at IS NULL",
                (user["id"],),
            )
            conn.execute(
                "INSERT INTO password_reset_tokens "
                "(user_id, token_hash, expires_at) "
                "VALUES (?, ?, datetime('now', '+30 minutes'))",
                (user["id"], token_hash),
            )
            conn.commit()
            reset_url = url_for("reset_password", token=raw_token, _external=True)
            sent = email_service.send_email(
                to_email=user["email"],
                to_name=user["username"],
                subject="Reset your Botfolio password",
                heading="Password reset requested",
                message=(
                    "Use the button below to choose a new password. This link "
                    "expires in 30 minutes and can only be used once."
                ),
                action_url=reset_url,
                action_text="Reset password",
                event_type="password_reset",
            )
            if not sent:
                # The reply below is identical whether or not mail went out,
                # which also hides a broken mailer from the one person who
                # could fix it. Say so in the log at least.
                app.logger.error(
                    "Password reset email could not be sent to user %s",
                    user["id"],
                )

        # Always show the same response so attackers cannot discover accounts.
        flash(
            "If an account uses that email, a password-reset link has been sent.",
            "success",
        )
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    conn = db.get_db()
    reset = conn.execute(
        """
        SELECT prt.*, u.username, u.email
          FROM password_reset_tokens prt
          JOIN users u ON u.id = prt.user_id
         WHERE prt.token_hash = ?
           AND prt.used_at IS NULL
           AND prt.expires_at > datetime('now')
        """,
        (token_hash,),
    ).fetchone()

    if reset is None:
        flash("That password-reset link is invalid or has expired.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password") or ""
        confirmation = request.form.get("confirmation") or ""
        if len(password) < 8:
            flash("Passwords must be at least 8 characters.", "error")
        elif password != confirmation:
            flash("The passwords do not match.", "error")
        else:
            conn.execute(
                # email_verified_at: following this link is proof the address
                # reaches its owner, which is the whole point of the claim
                # flow. Stamped unconditionally, not COALESCEd: an old row may
                # already carry a date the boot-time backfill invented, and
                # keeping that would leave a genuinely proven address still
                # wearing the backfill's signature. auth_provider: a
                # Google-born account that sets a password graduates out of
                # the password-less state, so the "set a password first" guard
                # on unlinking stops firing.
                "UPDATE users SET password_hash = ?, "
                "email_verified_at = datetime('now'), "
                "email_verified_source = 'reset', "
                # A reset evicts an intruder from the account, and it already
                # deletes their sessions below. A Google credential they bolted
                # on is a way back in that outlives both, so it goes too. The
                # exception is a row whose only credential IS Google: that one
                # is graduating to a password, not taking itself back from
                # anybody, and clearing it would strand the account.
                "google_sub = CASE WHEN auth_provider = 'google' "
                "THEN google_sub ELSE NULL END, "
                "auth_provider = 'password' WHERE id = ?",
                (generate_password_hash(password), reset["user_id"]),
            )
            conn.execute(
                "DELETE FROM user_sessions WHERE user_id = ?", (reset["user_id"],)
            )
            conn.execute(
                "UPDATE password_reset_tokens SET used_at = datetime('now') "
                "WHERE id = ?",
                (reset["id"],),
            )
            conn.commit()
            flash("Your password has been changed. You can sign in now.", "success")
            return redirect(url_for("login"))

    return render_template("reset_password.html")


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    # Signing out stays a POST so a stray <img src="/logout"> cannot do it, but
    # GET has to lead somewhere: it is the only escape a user has if the page
    # carrying the sign-out button will not render.
    if request.method == "GET":
        return render_template("logout.html")
    record_security_event("logout", session.get("user_id"))
    revoke_authenticated_session()
    flash("Signed out.", "success")
    response = redirect(url_for("index"))
    # Also evict authenticated documents from the browser's HTTP cache. The
    # no-store headers protect back/forward navigation; this covers older
    # caches that retained a page before those headers were deployed.
    response.headers["Clear-Site-Data"] = '"cache"'
    return response


@auth_bp.route("/account")
@login_required
def account_settings():
    owned_teams = db.get_db().execute(
        "SELECT program,number,name FROM teams WHERE owner_id=? ORDER BY program,number",
        (current_user()["id"],),
    ).fetchall()
    return render_template("account.html", owned_teams=owned_teams)


@auth_bp.route("/account/email", methods=["POST"])
@login_required
@ratelimit.limit("change-email", 5, 3600)
def change_email():
    user = current_user()
    new_email = (request.form.get("email") or "").strip().lower()[:254]
    password = request.form.get("password") or ""

    if not check_password_hash(user["password_hash"], password):
        flash("Your current password was incorrect. Your email was not changed.", "error")
        return redirect(url_for("account_settings"))
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", new_email):
        flash("Enter a valid email address.", "error")
        return redirect(url_for("account_settings"))
    if new_email == user["email"].lower():
        flash("That is already your account email.", "error")
        return redirect(url_for("account_settings"))

    conn = db.get_db()
    duplicate = conn.execute(
        "SELECT id FROM users WHERE lower(email)=? AND id<>? AND deleted_at IS NULL",
        (new_email, user["id"]),
    ).fetchone()
    if duplicate:
        flash("That email address is already registered.", "error")
        return redirect(url_for("account_settings"))

    conn.execute(
        "UPDATE users SET email=?,email_verified_at=NULL WHERE id=?",
        (new_email, user["id"]),
    )
    conn.execute(
        "UPDATE email_verification_tokens SET used_at=datetime('now') WHERE user_id=? AND used_at IS NULL",
        (user["id"],),
    )
    conn.commit()
    sent = send_verification_email(user["id"], new_email, user["username"])
    if sent:
        flash("Email changed. Check your new inbox to verify the address.", "success")
    else:
        flash("Email changed, but the verification message could not be sent. Please resend it from the verification page.", "error")
    return redirect(url_for("account_settings"))


@auth_bp.route("/account/delete", methods=["POST"])
@login_required
def delete_account():
    """Permanently remove private account data and content, retaining useful comments anonymously."""
    user = current_user()
    password = request.form.get("password") or ""
    confirmation = (request.form.get("confirmation") or "").strip()
    if confirmation != "DELETE":
        flash("Type DELETE exactly to confirm account deletion.", "error")
        return redirect(url_for("account_settings"))
    if not check_password_hash(user["password_hash"], password):
        flash("Your password was incorrect. The account was not deleted.", "error")
        return redirect(url_for("account_settings"))

    conn = db.get_db()
    owned = conn.execute("SELECT number FROM teams WHERE owner_id=?", (user["id"],)).fetchall()
    if owned:
        numbers = ", ".join(str(row["number"]) for row in owned)
        flash(f"Transfer or delete the teams you own before deleting your account: {numbers}.", "error")
        return redirect(url_for("account_settings"))

    designs = conn.execute("SELECT * FROM designs WHERE user_id=?", (user["id"],)).fetchall()
    assets = []
    for design in designs:
        images = conn.execute(
            "SELECT filename FROM design_images WHERE design_id=?", (design["id"],)
        ).fetchall()
        assets.append((design["model_filename"], {row["filename"] for row in images} | {design["image_filename"]}))
    conn.execute("DELETE FROM ai_feedback WHERE requester_id=?", (user["id"],))
    conn.execute("DELETE FROM designs WHERE user_id=?", (user["id"],))
    conn.execute("DELETE FROM memberships WHERE user_id=?", (user["id"],))
    conn.execute("DELETE FROM password_reset_tokens WHERE user_id=?", (user["id"],))
    conn.execute("DELETE FROM email_verification_tokens WHERE user_id=?", (user["id"],))
    conn.execute("DELETE FROM user_sessions WHERE user_id=?", (user["id"],))
    deleted_username = f"deleted_user_{user['id']}"
    # google_sub has to be cleared with the rest: it is uniquely indexed, so
    # leaving it behind on a tombstone row would silently bar that Google
    # account from ever signing up again.
    conn.execute(
        """UPDATE users SET username=?,email=?,password_hash='',bio='',location='',contact_email='',
                  website_url=NULL,social_links='{}',profile_image=NULL,tagline='',specialties='',cad_tools='',
                  ftc_role=NULL,registration_ip=NULL,email_verified_at=NULL,suspended_at=datetime('now'),suspended_until=NULL,
                  banned_at=NULL,deleted_at=datetime('now'),storage_used_bytes=0,is_admin=0,
                  google_sub=NULL,auth_provider='password'
             WHERE id=?""",
        (deleted_username, f"deleted-{user['id']}@invalid.botfolio", user["id"]),
    )
    conn.commit()
    for model_filename, image_filenames in assets:
        for filename in image_filenames:
            delete_asset(UPLOAD_DIR, filename)
        delete_asset(MODEL_DIR, model_filename)
    delete_asset(UPLOAD_DIR, user["profile_image"])
    session.clear()
    flash("Your account and designs were deleted. Retained comments now appear as Deleted User.", "success")
    return redirect(url_for("index"))
