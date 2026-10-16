"""Retention enforcement and safe maintenance for Botfolio's database.

Run with no arguments at least daily. Legal/security holds are managed with:
  python maintenance.py hold <target_type> <target_id> <reason>
  python maintenance.py release <hold_id>
"""

import argparse
import os
import secrets

import db

# The maintenance process imports a few shared helpers from app.py, but it
# never serves requests or signs browser sessions. Give that import a private,
# short-lived key so a standalone cron service does not need the website's
# FLASK_SECRET_KEY copied into it.
os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_urlsafe(48))

from app import cleanup_low_score_tags, design_week_start, ensure_runtime_schema
from infra import storage


# Evaluate only design/tag assignments; shared vocabulary rows are retained.
def _active_hold_sql(alias, target_type):
    return (
        "NOT EXISTS (SELECT 1 FROM retention_holds h "
        f"WHERE h.target_type='{target_type}' AND h.target_id=CAST({alias}.id AS TEXT) "
        "AND h.released_at IS NULL "
        "AND (h.expires_at IS NULL OR h.expires_at>datetime('now')))"
    )


def run_retention():
    ensure_runtime_schema()
    conn = db.connect()
    removed = cleanup_low_score_tags(conn)
    current_week = design_week_start()
    reset_awards = conn.execute(
        "UPDATE design_of_week_awards SET is_current=0 "
        "WHERE is_current=1 AND (current_week IS NULL OR current_week<>?)",
        (current_week,),
    ).rowcount
    expired_ai_chats = conn.execute(
        "DELETE FROM ai_feedback WHERE saved_at IS NULL "
        "AND created_at<datetime('now','-3 days')"
    ).rowcount

    # Moderated content is soft-hidden immediately so it disappears from the
    # public site. The scheduled maintenance pass then permanently removes it,
    # including dependent rows via foreign-key cascades. Active legal holds
    # remain the sole exception.
    purged_comments = conn.execute(
        f"DELETE FROM comments WHERE status IN ('hidden','deleted') "
        f"AND {_active_hold_sql('comments', 'comment')}"
    ).rowcount
    hidden_designs = conn.execute(
        f"""SELECT d.id,d.user_id,d.storage_bytes,d.image_filename,d.model_filename
               FROM designs d WHERE d.is_hidden=1
                AND {_active_hold_sql('d', 'design')}"""
    ).fetchall()
    hidden_design_assets = {}
    for design in hidden_designs:
        hidden_design_assets[design["id"]] = {
            row["filename"] for row in conn.execute(
                "SELECT filename FROM design_images WHERE design_id=?", (design["id"],)
            ).fetchall()
        } | {design["image_filename"]}
        conn.execute(
            "UPDATE users SET storage_used_bytes=CASE WHEN storage_used_bytes>=? THEN storage_used_bytes-? ELSE 0 END WHERE id=?",
            (design["storage_bytes"], design["storage_bytes"], design["user_id"]),
        )
        conn.execute("DELETE FROM designs WHERE id=?", (design["id"],))
    stale_uploads = conn.execute(
        "SELECT id,object_filename,status,multipart_upload_id,upload_completed_at,promoted_at "
        "FROM pending_model_uploads "
        "WHERE expires_at<datetime('now','-1 day')"
    ).fetchall()
    for upload in stale_uploads:
        if upload["status"] != "consumed":
            if upload["multipart_upload_id"] and not upload["upload_completed_at"]:
                storage.abort_multipart_upload(
                    "quarantine", upload["object_filename"],
                    upload["multipart_upload_id"],
                )
            elif upload["promoted_at"]:
                storage.delete("models", upload["object_filename"])
            else:
                storage.delete("quarantine", upload["object_filename"])
        conn.execute("DELETE FROM pending_model_uploads WHERE id=?", (upload["id"],))
    # Account consent evidence survives anonymization for the documented
    # post-closure period, unless the account is under an active hold.
    user_not_held = _active_hold_sql("users", "user")
    age_consents = conn.execute(
        f"""UPDATE users SET age_13_confirmed=0,minor_permission_confirmed=0
              WHERE deleted_at IS NOT NULL
                AND deleted_at<datetime('now','-3 years') AND {user_not_held}"""
    ).rowcount
    policy_consents = conn.execute(
        f"""UPDATE users SET accepted_terms_version=NULL,accepted_terms_at=NULL,
                                 accepted_privacy_version=NULL,accepted_privacy_at=NULL,
                                 acknowledged_legal_version=NULL,acknowledged_legal_at=NULL
              WHERE deleted_at IS NOT NULL
                AND deleted_at<datetime('now','-5 years') AND {user_not_held}"""
    ).rowcount

    # Closed copyright and material safety/security reports are kept five
    # years; ordinary moderation reports are kept two years.
    report_not_held = _active_hold_sql("content_reports", "content_report")
    expired_reports = conn.execute(
        f"""SELECT id FROM content_reports
            WHERE workflow_status='closed' AND resolved_at IS NOT NULL AND (
              (reason IN ('copyright','threat','youth_safety','intimate','privacy_danger','malware')
                   AND resolved_at<datetime('now','-5 years')) OR
              (reason NOT IN ('copyright','threat','youth_safety','intimate','privacy_danger','malware')
                   AND resolved_at<datetime('now','-2 years'))
            ) AND {report_not_held}"""
    ).fetchall()
    for report in expired_reports:
        conn.execute("DELETE FROM content_reports WHERE id=?", (report["id"],))

    expired_comment_reports = conn.execute(
        f"""SELECT id FROM comment_reports
              WHERE status!='open' AND resolved_at IS NOT NULL
                AND resolved_at<datetime('now','-2 years')
                AND {_active_hold_sql('comment_reports', 'comment_report')}"""
    ).fetchall()
    for report in expired_comment_reports:
        conn.execute("DELETE FROM comment_reports WHERE id=?", (report["id"],))

    # Standalone moderation audit actions age out after two years. Actions
    # attached to five-year report classes follow the longer period.
    expired_actions = conn.execute(
        f"""SELECT ma.id FROM moderation_actions ma
              WHERE {_active_hold_sql('ma', 'moderation_action')} AND (
                (ma.target_type='content_report' AND EXISTS (
                    SELECT 1 FROM content_reports cr
                     WHERE CAST(cr.id AS TEXT)=ma.target_id
                       AND cr.reason IN ('copyright','threat','youth_safety','intimate','privacy_danger','malware')
                ) AND ma.created_at<datetime('now','-5 years'))
                OR
                (NOT (ma.target_type='content_report' AND EXISTS (
                    SELECT 1 FROM content_reports cr
                     WHERE CAST(cr.id AS TEXT)=ma.target_id
                       AND cr.reason IN ('copyright','threat','youth_safety','intimate','privacy_danger','malware')
                )) AND ma.created_at<datetime('now','-2 years'))
              )"""
    ).fetchall()
    for action in expired_actions:
        conn.execute("DELETE FROM moderation_actions WHERE id=?", (action["id"],))

    expired_security_events = conn.execute(
        f"""SELECT id FROM security_events
              WHERE occurred_at<datetime('now','-90 days')
                AND {_active_hold_sql('security_events', 'security_event')}"""
    ).fetchall()
    for event in expired_security_events:
        conn.execute("DELETE FROM security_events WHERE id=?", (event["id"],))

    expired_incidents = conn.execute(
        f"""SELECT id FROM security_incidents
              WHERE resolution_date IS NOT NULL
                AND resolution_date<datetime('now','-5 years')
                AND {_active_hold_sql('security_incidents', 'security_incident')}"""
    ).fetchall()
    for incident in expired_incidents:
        conn.execute("DELETE FROM security_incidents WHERE id=?", (incident["id"],))

    conn.execute("DELETE FROM password_reset_tokens WHERE created_at<datetime('now','-90 days')")
    conn.execute("DELETE FROM email_verification_tokens WHERE created_at<datetime('now','-90 days')")
    conn.commit()
    conn.close()
    for design in hidden_designs:
        for filename in hidden_design_assets[design["id"]]:
            if filename:
                storage.delete("uploads", filename)
        if design["model_filename"]:
            storage.delete("models", design["model_filename"])
    print(f"Removed {removed} expired or heavily downvoted tag assignment(s).")
    print(f"Reset {reset_awards} expired Design of the Week selection(s).")
    print(f"Removed {expired_ai_chats} unsaved AI chat(s) older than three days.")
    print(f"Permanently removed {purged_comments} hidden/deleted comment(s).")
    print(f"Permanently removed {len(hidden_designs)} hidden design(s) and their stored files.")
    print(f"Removed {len(stale_uploads)} stale upload authorization(s).")
    print(f"Removed {len(expired_reports)} content report(s) past their retention period.")
    print(f"Removed {len(expired_comment_reports)} closed comment report(s) past two years.")
    print(f"Removed {len(expired_actions)} moderation action(s) past retention.")
    print(f"Removed {len(expired_security_events)} security event(s) past 90 days.")
    print(f"Removed {len(expired_incidents)} resolved security incident record(s) past five years.")
    print(f"Expired age/permission evidence on {age_consents} closed account(s).")
    print(f"Expired policy-acceptance evidence on {policy_consents} closed account(s).")


def create_hold(target_type, target_id, reason, expires_at=None):
    ensure_runtime_schema()
    conn = db.connect()
    cursor = conn.execute(
        "INSERT INTO retention_holds(target_type,target_id,reason,expires_at) VALUES (?,?,?,?)",
        (target_type, str(target_id), reason, expires_at),
    )
    conn.commit()
    conn.close()
    print(f"Created retention hold #{cursor.lastrowid} for {target_type} {target_id}.")


def release_hold(hold_id):
    ensure_runtime_schema()
    conn = db.connect()
    conn.execute(
        "UPDATE retention_holds SET released_at=datetime('now') WHERE id=? AND released_at IS NULL",
        (hold_id,),
    )
    conn.commit()
    conn.close()
    print(f"Released retention hold #{hold_id}.")


def main():
    parser = argparse.ArgumentParser(description="Botfolio retention maintenance")
    subparsers = parser.add_subparsers(dest="command")
    hold = subparsers.add_parser("hold", help="prevent automatic deletion of a record")
    hold.add_argument("target_type")
    hold.add_argument("target_id")
    hold.add_argument("reason")
    hold.add_argument("--expires-at")
    release = subparsers.add_parser("release", help="release an existing hold")
    release.add_argument("hold_id", type=int)
    args = parser.parse_args()
    if args.command == "hold":
        create_hold(args.target_type, args.target_id, args.reason, args.expires_at)
    elif args.command == "release":
        release_hold(args.hold_id)
    else:
        run_retention()


if __name__ == "__main__":
    main()
