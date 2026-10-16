"""Design publishing, direct uploads, and author editing."""

from pathlib import Path
import json
import math
import re
import secrets
import uuid
from urllib.parse import urlparse

import app as core

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from services.discord_service import notify_design_published

from app import (
    CAD_DOWNLOAD_ONLY, CAD_SOFTWARE, CONTRIBUTOR_ROLES, LINKED_CAD_SOFTWARE,
    MAX_MODEL_BYTES, MODEL_DIR, MODEL_EXTENSIONS, MODEL_FORMATS_PHRASE,
    MODEL_UPLOAD_PART_BYTES, TEAM_PROGRAMS, UPLOAD_CERTIFICATION_VERSION,
    UPLOAD_DIR, UPLOAD_LIMIT_10_MINUTES, UPLOAD_LIMIT_DAILY,
    _safe_upload_size, app, attach_tag, clean_camera_json, credit_team_name,
    current_user, db, delete_asset, dimension_error, hashlib, infra_storage,
    login_required, model_is_viewable, moderate_public_content,
    qualify_founding_contributor, qualify_founding_team, ratelimit,
    save_design_contributors, save_image_upload, save_model_upload,
    save_preview_data_url, settings, slugify, valid_model_content,
    verified_required, DESIGN_TYPES, DESIGN_FUNCTIONS,
)


designs_bp = Blueprint("designs", __name__)


def _team_program(raw, default="ftc"):
    program = (raw or default).strip().lower()
    return program if program in TEAM_PROGRAMS else None


def _clean_orientation(raw):
    """Pull a unit quaternion out of a stored or submitted viewer state.

    This is the correction that says which way a model is actually facing,
    written by the orientation sequence in static/viewer-orientation.js. Like
    the camera it is rebuilt rather than trusted: it comes from a form field,
    and it is echoed back into a <script> block on the design page.

    A quaternion of no length names no rotation and would make the viewer's
    matrices degenerate, so it is rejected; everything else is scaled to length
    one, which is the only form the viewer can use.
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    value = data.get("orientation") if isinstance(data, dict) else None
    if (not isinstance(value, list) or len(value) != 4
            or not all(isinstance(n, (int, float)) and not isinstance(n, bool)
                       and math.isfinite(n) for n in value)):
        return None

    length = math.sqrt(sum(float(n) * float(n) for n in value))
    if not 1e-6 < length < 1e6:
        return None
    return [float(n) / length for n in value]


def clean_viewer_state(raw, existing=None):
    """Reduce everything the viewer stores about a design to one JSON string.

    The column behind this began as the camera alone and grew an orientation,
    because both answer the same question — how this design should look when
    somebody opens it — and because the two have to be written together: the
    saved angle is measured against the corrected model, so storing one without
    the other points the camera at a different face.

    `existing` is the row's current value, and its orientation is kept when the
    submission has none. Every path that writes here also predates the
    orientation, so a page served from a stale cache, or any client that only
    knows about the camera, would otherwise quietly undo a correction while
    saving something unrelated.
    """
    camera = clean_camera_json(raw)
    state = json.loads(camera) if camera else {}

    orientation = _clean_orientation(raw)
    if orientation is None:
        orientation = _clean_orientation(existing)
    if orientation is not None:
        state["orientation"] = orientation

    return json.dumps(state) if state else None


@designs_bp.route("/api/model-uploads/authorize", methods=["POST"])
@ratelimit.limit(
    "model-upload-authorize", 10, 3600,
    exempt=lambda: bool(current_user() and current_user()["is_admin"]),
)
@login_required
@verified_required
def authorize_model_upload():
    if not settings.uses_direct_model_uploads:
        return jsonify(error="Direct model uploads are not configured."), 503
    payload = request.get_json(silent=True) or {}
    original = secure_filename(str(payload.get("filename") or ""))
    extension = Path(original).suffix.lower()
    try:
        declared_size = int(payload.get("size") or 0)
    except (TypeError, ValueError):
        declared_size = 0
    if extension not in MODEL_EXTENSIONS:
        return jsonify(error=f"Only {MODEL_FORMATS_PHRASE} models are supported."), 400
    if not 0 < declared_size <= MAX_MODEL_BYTES:
        return jsonify(error="The model must be between 1 byte and 2.5 GB."), 400
    user = current_user()

    raw_token = secrets.token_urlsafe(32)
    object_filename = f"{uuid.uuid4().hex}{extension}"
    try:
        multipart_upload_id = infra_storage.initiate_multipart_upload(
            "quarantine", object_filename, "application/octet-stream"
        )
    except Exception:
        app.logger.exception("Could not initiate direct model upload")
        return jsonify(error="Storage could not start the upload."), 503

    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO pending_model_uploads(user_id,token_hash,original_filename,"
            "object_filename,declared_size_bytes,multipart_upload_id,expires_at) "
            "VALUES (?,?,?,?,?,?,datetime('now','+6 hours'))",
            (user["id"], hashlib.sha256(raw_token.encode()).hexdigest(), original,
             object_filename, declared_size, multipart_upload_id),
        )
        conn.commit()

        part_count = math.ceil(declared_size / MODEL_UPLOAD_PART_BYTES)
        part_urls = [
            {
                "part_number": number,
                "upload_url": infra_storage.presign_upload_part(
                    "quarantine", object_filename, multipart_upload_id, number
                ),
            }
            for number in range(1, part_count + 1)
        ]
    except Exception:
        infra_storage.abort_multipart_upload(
            "quarantine", object_filename, multipart_upload_id
        )
        app.logger.exception("Could not authorize multipart model upload")
        return jsonify(error="Storage could not authorize the upload."), 503
    return jsonify(
        upload_token=raw_token,
        content_type="application/octet-stream",
        expires_in=6 * 60 * 60,
        part_size=MODEL_UPLOAD_PART_BYTES,
        parts=part_urls,
    )


@designs_bp.route("/api/model-uploads/complete", methods=["POST"])
@ratelimit.limit(
    "model-upload-complete", 20, 3600,
    exempt=lambda: bool(current_user() and current_user()["is_admin"]),
)
@login_required
@verified_required
def complete_model_upload():
    """Complete a browser-to-storage multipart upload before form submission."""
    payload = request.get_json(silent=True) or {}
    raw_token = str(payload.get("upload_token") or "")
    supplied_parts = payload.get("parts")
    if not raw_token or not isinstance(supplied_parts, list):
        return jsonify(error="The multipart upload response was incomplete."), 400

    user = current_user()
    conn = db.get_db()
    pending = conn.execute(
        "SELECT * FROM pending_model_uploads WHERE token_hash=? AND user_id=?",
        (hashlib.sha256(raw_token.encode()).hexdigest(), user["id"]),
    ).fetchone()
    if pending is None or pending["status"] != "pending":
        return jsonify(error="That upload is missing, expired, or already used."), 409
    if pending["upload_completed_at"]:
        return jsonify(ok=True)
    if not pending["multipart_upload_id"]:
        return jsonify(error="That upload does not have a multipart session."), 409

    expired = conn.execute(
        "SELECT ? <= datetime('now') expired", (pending["expires_at"],)
    ).fetchone()["expired"]
    if expired:
        infra_storage.abort_multipart_upload(
            "quarantine", pending["object_filename"], pending["multipart_upload_id"]
        )
        conn.execute("UPDATE pending_model_uploads SET status='rejected' WHERE id=?",
                     (pending["id"],))
        conn.commit()
        return jsonify(error="That upload session expired. Start the upload again."), 409

    expected_count = math.ceil(
        pending["declared_size_bytes"] / MODEL_UPLOAD_PART_BYTES
    )
    normalized_parts = []
    for index, part in enumerate(supplied_parts, start=1):
        if not isinstance(part, dict):
            return jsonify(error="The uploaded part list was invalid."), 400
        try:
            number = int(part.get("part_number"))
        except (TypeError, ValueError):
            return jsonify(error="The uploaded part list was invalid."), 400
        etag = str(part.get("etag") or "").strip()
        if number != index or len(etag) > 128 or not re.fullmatch(
            r'"?[0-9a-fA-F]{32}"?', etag
        ):
            return jsonify(error="The uploaded part list was invalid."), 400
        normalized_parts.append({"PartNumber": number, "ETag": etag})
    if len(normalized_parts) != expected_count:
        return jsonify(error="Not every model part finished uploading."), 400

    assembled_bucket = "quarantine"
    try:
        infra_storage.complete_multipart_upload(
            "quarantine", pending["object_filename"],
            pending["multipart_upload_id"], normalized_parts,
        )
        actual_size = infra_storage.size("quarantine", pending["object_filename"])
    except Exception:
        # The provider may have assembled the object even if its response was
        # lost. A retry then reports that the upload id no longer exists. The
        # uniquely named final object is authoritative in that case.
        try:
            actual_size = infra_storage.size("quarantine", pending["object_filename"])
        except Exception:
            # A previous request can also finish the promotion and lose its
            # database response. Recover from the already-prepared model.
            try:
                assembled_bucket = "models"
                actual_size = infra_storage.size("models", pending["object_filename"])
            except Exception:
                app.logger.exception("Could not complete multipart model upload")
                return jsonify(error="Storage could not finish assembling the model."), 503
            if actual_size == pending["declared_size_bytes"]:
                conn.execute(
                    "UPDATE pending_model_uploads SET upload_completed_at=datetime('now'),"
                    "promoted_at=datetime('now') WHERE id=?",
                    (pending["id"],),
                )
                conn.commit()
                return jsonify(ok=True)

    if actual_size != pending["declared_size_bytes"] or actual_size > MAX_MODEL_BYTES:
        infra_storage.delete(assembled_bucket, pending["object_filename"])
        conn.execute("UPDATE pending_model_uploads SET status='rejected' WHERE id=?",
                     (pending["id"],))
        conn.commit()
        return jsonify(error="The completed model size did not match the upload."), 409

    extension = Path(pending["object_filename"]).suffix.lower()
    try:
        prefix = infra_storage.read_prefix("quarantine", pending["object_filename"])
        if not valid_model_content(extension, prefix, actual_size):
            infra_storage.delete("quarantine", pending["object_filename"])
            conn.execute(
                "UPDATE pending_model_uploads SET status='rejected' WHERE id=?",
                (pending["id"],),
            )
            conn.commit()
            return jsonify(
                error=f"The uploaded file was not a valid {MODEL_FORMATS_PHRASE} model."
            ), 400
        infra_storage.promote(
            "quarantine", "models", pending["object_filename"]
        )
    except Exception:
        app.logger.exception("Could not validate and promote uploaded model")
        return jsonify(error="Storage could not prepare the model for publishing."), 503

    conn.execute(
        "UPDATE pending_model_uploads SET upload_completed_at=datetime('now'),"
        "promoted_at=datetime('now') WHERE id=?",
        (pending["id"],),
    )
    conn.commit()
    return jsonify(ok=True)


def finalize_model_upload(raw_token, user):
    """Verify and promote one browser-uploaded quarantine object."""
    conn = db.get_db()
    pending = conn.execute(
        "SELECT * FROM pending_model_uploads WHERE token_hash=? AND user_id=?",
        (hashlib.sha256(raw_token.encode()).hexdigest(), user["id"]),
    ).fetchone()
    if pending is None or pending["status"] != "pending":
        raise ValueError("That model upload is missing, expired, or already used.")
    expired = conn.execute(
        "SELECT ? <= datetime('now') expired", (pending["expires_at"],)
    ).fetchone()["expired"]
    if expired:
        infra_storage.abort_multipart_upload(
            "quarantine", pending["object_filename"], pending["multipart_upload_id"]
        )
        conn.execute("UPDATE pending_model_uploads SET status='rejected' WHERE id=?",
                     (pending["id"],))
        conn.commit()
        raise ValueError("That model upload authorization expired. Upload it again.")
    if pending["multipart_upload_id"] and not pending["upload_completed_at"]:
        raise ValueError("That model upload has not finished yet.")
    storage_bucket = "models" if pending["promoted_at"] else "quarantine"
    try:
        actual_size = infra_storage.size(storage_bucket, pending["object_filename"])
    except Exception as exc:
        raise ValueError("The model did not finish uploading to storage.") from exc
    if actual_size <= 0 or actual_size > MAX_MODEL_BYTES:
        infra_storage.delete(storage_bucket, pending["object_filename"])
        conn.execute("UPDATE pending_model_uploads SET status='rejected' WHERE id=?",
                     (pending["id"],))
        conn.commit()
        raise ValueError("The uploaded model is empty or larger than 2.5 GB.")
    if actual_size != pending["declared_size_bytes"]:
        infra_storage.delete(storage_bucket, pending["object_filename"])
        raise ValueError("The uploaded model size did not match its authorization.")
    if not pending["promoted_at"]:
        prefix = infra_storage.read_prefix("quarantine", pending["object_filename"])
        extension = Path(pending["object_filename"]).suffix.lower()
        if not valid_model_content(extension, prefix, actual_size):
            infra_storage.delete("quarantine", pending["object_filename"])
            conn.execute("UPDATE pending_model_uploads SET status='rejected' WHERE id=?",
                         (pending["id"],))
            conn.commit()
            raise ValueError(
                f"The uploaded file was not a valid {MODEL_FORMATS_PHRASE} model."
            )
        infra_storage.promote("quarantine", "models", pending["object_filename"])
    conn.execute(
        "UPDATE pending_model_uploads SET status='consumed',consumed_at=datetime('now') WHERE id=?",
        (pending["id"],),
    )
    return pending["object_filename"], actual_size, None

def _resolve_archetype(conn, season_id, archetype_id, new_name, user_id):
    """Use the chosen archetype, or coin a new one scoped to this season."""
    new_name = (new_name or "").strip()
    if new_name:
        slug = slugify(new_name)
        existing = conn.execute(
            "SELECT id FROM archetypes WHERE slug = ? AND "
            "(season_id IS ? OR season_id = ?)",
            (slug, season_id, season_id),
        ).fetchone()
        if existing:
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO archetypes (season_id, name, slug, created_by) "
            "VALUES (?, ?, ?, ?)",
            (season_id, new_name, slug, user_id),
        )
        return cur.lastrowid
    return archetype_id or None


def _design_taxonomy_error(conn, program, season_id, archetype_id):
    """Keep a design's season and model type inside its robotics program."""
    if season_id and conn.execute(
        "SELECT 1 FROM seasons WHERE id=? AND program=?", (season_id, program)
    ).fetchone() is None:
        return "Choose a season from the selected robotics program."
    if archetype_id:
        # PostgreSQL cannot infer a type for a bare NULL parameter in
        # ``? IS NULL``. Keep the no-season case explicit instead of relying on
        # SQLite's more permissive parameter handling.
        if season_id is None:
            archetype = conn.execute(
                """SELECT 1 FROM archetypes a LEFT JOIN seasons s ON s.id=a.season_id
                    WHERE a.id=? AND (a.season_id IS NULL OR s.program=?)""",
                (archetype_id, program),
            ).fetchone()
        else:
            archetype = conn.execute(
                """SELECT 1 FROM archetypes a LEFT JOIN seasons s ON s.id=a.season_id
                    WHERE a.id=? AND (a.season_id IS NULL OR
                          (s.program=? AND a.season_id=?))""",
                (archetype_id, program, season_id),
            ).fetchone()
        if archetype is None:
            return "Choose a model type from the selected season."
    return None


@designs_bp.route("/submit", methods=["GET", "POST"])
# Sits in front of the per-user database limits in config.py rather than
# replacing them. This one is about bandwidth: MAX_CONTENT_LENGTH is 400 MB, so
# without a cap here a single client can post 400 MB in a loop.
@ratelimit.limit(
    "submit", 20, 600,
    exempt=lambda: bool(current_user() and current_user()["is_admin"]),
)
@login_required
@verified_required
def submit():
    conn = db.get_db()
    user = current_user()

    if request.method == "POST":
        if not user["is_admin"]:
            short = conn.execute("SELECT COUNT(*) n FROM upload_attempts WHERE user_id=? AND created_at >= datetime('now','-10 minutes')", (user["id"],)).fetchone()["n"]
            daily = conn.execute("SELECT COUNT(*) n FROM upload_attempts WHERE user_id=? AND created_at >= datetime('now','-1 day')", (user["id"],)).fetchone()["n"]
            if short >= UPLOAD_LIMIT_10_MINUTES or daily >= UPLOAD_LIMIT_DAILY:
                wait = "10 minutes" if short >= UPLOAD_LIMIT_10_MINUTES else "24 hours"
                flash(f"Upload limit reached. Please try again after the oldest submission leaves the {wait} window.", "error")
                return redirect(url_for("submit"))
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        program = _team_program(request.form.get("program")) or "ftc"
        # The browser requires an explicit choice. Treat older API/form clients
        # that predate this field as "Other CAD" so existing integrations keep
        # publishing instead of failing after the additive migration.
        cad_software = (request.form.get("cad_software") or "other").strip().lower()
        cad_link = (request.form.get("cad_link") or "").strip()
        season_id = request.form.get("season_id", type=int)
        design_type = (request.form.get("design_type") or "other").strip()
        if design_type not in DESIGN_TYPES:
            design_type = "other"
        function_keys = [key for key in request.form.getlist("functions") if key in DESIGN_FUNCTIONS]
        archetype_id = request.form.get("archetype_id", type=int)
        new_archetype = request.form.get("new_archetype") or ""
        if cad_software == CAD_DOWNLOAD_ONLY:
            cad_link = ""
        team_choice = (request.form.get("team_id") or "").strip()
        admin_team_number = None
        admin_team_name = ""
        if user["is_admin"]:
            team_choice = (request.form.get("admin_attribution") or team_choice).strip()
            if team_choice == "team":
                admin_team_number = request.form.get("admin_team_number", type=int)
                admin_team_name = (request.form.get("admin_team_name") or "").strip()
        team_id = None
        prototype_version = request.form.get("prototype_version", type=int)
        competition_tested_raw = request.form.get("competition_tested")
        dimension_unit = (request.form.get("dimension_unit") or "in").strip().lower()
        length_in = request.form.get("length_in", type=float)
        width_in = request.form.get("width_in", type=float)
        height_in = request.form.get("height_in", type=float)
        dimension_raws = [(request.form.get(name) or "").strip()
                          for name in ("length_in", "width_in", "height_in")]
        if dimension_unit == "mm":
            length_in, width_in, height_in = (
                round(value / 25.4, 6) if value is not None else None
                for value in (length_in, width_in, height_in)
            )
        dimension_message = dimension_error(
            dimension_raws, (length_in, width_in, height_in))
        motor_count_raw = (request.form.get("motor_count") or "").strip()
        servo_count_raw = (request.form.get("servo_count") or "").strip()
        motor_count = request.form.get("motor_count", type=int)
        servo_count = request.form.get("servo_count", type=int)
        camera_json = (request.form.get("camera_json") or "").strip()
        preview_data_url = request.form.get("preview_data_url") or ""
        upload_certification_accepted = request.form.get("upload_certification") == "accepted"
        contributor_usernames = request.form.getlist("contributor_username")
        contributor_roles = request.form.getlist("contributor_role")

        if user["is_admin"] and team_choice == "team" and admin_team_number:
            existing_team = conn.execute(
                "SELECT id FROM teams WHERE program=? AND number=?",
                (program, admin_team_number),
            ).fetchone()
            team_id = existing_team["id"] if existing_team else None
        elif team_choice and team_choice != "individual":
            try:
                team_id = int(team_choice)
            except ValueError:
                team_id = None

        if team_id:
            selected_team = conn.execute(
                "SELECT program FROM teams WHERE id=?", (team_id,)
            ).fetchone()
            if selected_team:
                program = selected_team["program"]

        if archetype_id and conn.execute(
            "SELECT 1 FROM archetypes WHERE id=?", (archetype_id,)
        ).fetchone() is None:
            archetype_id = None
        taxonomy_message = _design_taxonomy_error(
            conn, program, season_id, archetype_id
        )

        image_files = [f for f in request.files.getlist("image_files") if f.filename][:8]
        model_file = request.files.get("model_file")
        model_upload_token = (request.form.get("model_upload_token") or "").strip()

        error = None
        image_filename = None
        image_filenames = []
        model_filename = None
        model_size_bytes = 0
        model_sha256 = None

        if not team_choice:
            error = "Choose whether this design is uploaded for you individually or for a team."
        elif user["is_admin"] and team_choice == "team" and (
            admin_team_number is None or not 1 <= admin_team_number <= 999999
        ):
            error = "Enter a valid team number."
        elif not user["is_admin"] and team_choice != "individual" and (
            team_id is None or conn.execute(
                "SELECT 1 FROM memberships WHERE user_id=? AND team_id=?",
                (user["id"], team_id),
            ).fetchone() is None
        ):
            error = "Choose yourself or a team you belong to."
        elif not upload_certification_accepted:
            error = "You must accept the Upload Certification before publishing."
        elif not title:
            error = "Please give your design a title."
        elif taxonomy_message:
            error = taxonomy_message
        elif prototype_version is None or not 1 <= prototype_version <= 99:
            error = "Enter a prototype version between V1 and V99."
        elif competition_tested_raw not in {"0", "1"}:
            error = "Choose whether this design has been competition tested."
        elif dimension_unit not in {"in", "mm"}:
            error = "Choose inches or millimeters for the dimensions."
        elif dimension_message:
            error = dimension_message
        elif motor_count_raw and (motor_count is None or not 0 <= motor_count <= 99):
            error = "Motor count must be between 0 and 99."
        elif servo_count_raw and (servo_count is None or not 0 <= servo_count <= 99):
            error = "Servo count must be between 0 and 99."
        if cad_software not in CAD_SOFTWARE:
            error = "Choose the CAD software used for this design."
        elif cad_link:
            parsed_cad_link = urlparse(cad_link)
            if parsed_cad_link.scheme not in {"http", "https"} or not parsed_cad_link.netloc:
                error = "Please enter a valid CAD design link."

        if error is None:
            try:
                moderate_public_content(
                    texts=[title, description, new_archetype, admin_team_name,
                           request.form.get("tags") or ""],
                    use_api=not app.testing,
                )
                # Preferred path: a render the author framed in the 3D viewer.
                if preview_data_url.startswith("data:image/"):
                    image_filename = core.save_preview_data_url(preview_data_url)
                    image_filenames.append(image_filename)
                    image_files = image_files[:7]
                # Fallback path: a plain photo. Works with JavaScript disabled.
                elif image_files:
                    image_filename = core.save_image_upload(image_files.pop(0))
                    image_filenames.append(image_filename)
                else:
                    error = ("Add a preview: either upload a 3D model and set an "
                             "angle, or upload a picture.")

                if error is None and model_file and model_file.filename:
                    model_filename, model_size_bytes, model_sha256 = core.save_model_upload(model_file)
                elif error is None and model_upload_token:
                    model_filename, model_size_bytes, model_sha256 = finalize_model_upload(
                        model_upload_token, user
                    )
                if error is None:
                    for image_file in image_files:
                        image_filenames.append(core.save_image_upload(image_file))
            except ValueError as exc:
                error = str(exc)

        storage_bytes = 0
        if error is None:
            storage_bytes = model_size_bytes + sum(
                infra_storage.size("uploads", filename) for filename in image_filenames
            )

        if error is not None:
            for filename in image_filenames:
                delete_asset(UPLOAD_DIR, filename)
            if model_filename:
                delete_asset(MODEL_DIR, model_filename)
            flash(error, "error")
        else:
            camera_json = clean_camera_json(camera_json)

            if user["is_admin"] and team_choice == "team":
                admin_team_name = credit_team_name(
                    conn, admin_team_number, admin_team_name, program=program
                )
                if team_id is None:
                    team_id = conn.execute(
                        "INSERT INTO teams(program,number,name,invite_code,profile_status) VALUES (?,?,?,?,'reference')",
                        (program, admin_team_number, admin_team_name, secrets.token_urlsafe(18)),
                    ).lastrowid
                elif conn.execute(
                    "SELECT profile_status FROM teams WHERE id=?", (team_id,)
                ).fetchone()["profile_status"] == "reference":
                    conn.execute("UPDATE teams SET name=? WHERE id=?",
                                 (admin_team_name, team_id))

            archetype_id = _resolve_archetype(
                conn, season_id, archetype_id, new_archetype, user["id"]
            )

            cur = conn.execute(
                """
                INSERT INTO designs (
                    user_id,
                    team_id,
                    program,
                    title,
                    description,
                    onshape_link,
                    cad_software,
                    cad_link,
                    season_id,
                    archetype_id,
                    design_type,
                    prototype_version,
                    competition_tested,
                    length_in,
                    width_in,
                    height_in,
                    dimension_unit,
                    motor_count,
                    servo_count,
                    image_filename,
                    model_filename,
                    camera_json,
                    upload_certification_version,
                    upload_certification_accepted,
                    model_size_bytes,
                    model_sha256,
                    storage_bytes,
                    upload_status,
                    uploaded_by_admin
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 'approved', ?)
                """,
                (
                    user["id"],
                    team_id or None,
                    program,
                    title,
                    description,
                    cad_link if cad_software == "onshape" else None,
                    cad_software,
                    cad_link or None,
                    season_id or None,
                    archetype_id,
                    design_type,
                    prototype_version,
                    int(competition_tested_raw),
                    length_in,
                    width_in,
                    height_in,
                    dimension_unit,
                    motor_count,
                    servo_count,
                    image_filename,
                    model_filename,
                    camera_json,
                    UPLOAD_CERTIFICATION_VERSION,
                    model_size_bytes,
                    model_sha256,
                    storage_bytes,
                    int(bool(user["is_admin"])),
                ),
            )
            design_id = cur.lastrowid
            for function_key in dict.fromkeys(function_keys):
                conn.execute("INSERT INTO design_functions(design_id,function_key) VALUES(?,?)", (design_id, function_key))
            if user["is_admin"] and team_id:
                conn.execute(
                    "UPDATE designs SET team_attribution_accepted=0 WHERE id=?",
                    (design_id,),
                )
            for position, filename in enumerate(image_filenames):
                conn.execute(
                    "INSERT INTO design_images(design_id,filename,position) VALUES (?,?,?)",
                    (design_id, filename, position),
                )

            if not user["is_admin"]:
                conn.execute("INSERT INTO upload_attempts (user_id) VALUES (?)", (user["id"],))
            conn.execute(
                "UPDATE users SET storage_used_bytes=storage_used_bytes+? WHERE id=?",
                (storage_bytes, user["id"]),
            )

            try:
                for raw in (request.form.get("tags") or "").split(","):
                    if raw.strip():
                        attach_tag(design_id, raw, user["id"])
                save_design_contributors(conn, design_id, contributor_usernames, contributor_roles)
                qualify_founding_contributor(conn, user["id"])
                qualify_founding_team(conn, team_id)
            except ValueError as exc:
                conn.rollback()
                for filename in image_filenames:
                    delete_asset(UPLOAD_DIR, filename)
                delete_asset(MODEL_DIR, model_filename)
                flash(str(exc), "error")
                return redirect(url_for("submit"))

            conn.commit()
            notify_design_published(
                settings.discord_showcase_webhook_url,
                design_url=url_for("design_detail", design_id=design_id, _external=True),
                title=title,
                author=user["username"],
                description=description,
                image_url=infra_storage.url("uploads", image_filename, external=True),
            )
            flash("Design published.", "success")
            return redirect(url_for("design_detail", design_id=design_id))

    seasons = conn.execute("SELECT * FROM seasons ORDER BY program,sort_order DESC").fetchall()
    selected_season = (
        request.form.get("season_id", type=int)
        if request.method == "POST"
        else request.args.get("season", type=int)
    )
    selected_program = _team_program(request.values.get("program")) or "ftc"
    # Every archetype is sent to the page and narrowed to the chosen season in
    # the browser. Filtering here instead would mean a reload that throws away
    # whatever the user had already typed into the form.
    archetypes = conn.execute("SELECT * FROM archetypes ORDER BY name").fetchall()
    teams = conn.execute(
        "SELECT t.* FROM teams t JOIN memberships m ON m.team_id = t.id "
        "WHERE m.user_id = ? ORDER BY t.number",
        (user["id"],),
    ).fetchall()

    return render_template(
        "submit.html", seasons=seasons, archetypes=archetypes, teams=teams,
        selected_season=selected_season,
        selected_program=selected_program, programs=TEAM_PROGRAMS,
        direct_model_uploads=settings.uses_direct_model_uploads,
        contributor_roles=CONTRIBUTOR_ROLES, cad_software_choices=CAD_SOFTWARE,
        design_types=DESIGN_TYPES, design_functions=DESIGN_FUNCTIONS,
    )


@designs_bp.route("/submit/link", methods=["GET", "POST"])
# Shares the /submit bandwidth bucket: this is another publish path, so a client
# can't sidestep the cap by alternating between the two forms.
@ratelimit.limit(
    "submit", 20, 600,
    exempt=lambda: bool(current_user() and current_user()["is_admin"]),
)
@login_required
@verified_required
def submit_link():
    """Lightweight publish path: link out to a model hosted elsewhere, add basic
    info and at least one image. No hosted 3D file, so none of the model-upload
    plumbing — just the fields someone needs to share a design quickly."""
    conn = db.get_db()
    user = current_user()

    if request.method == "POST":
        if not user["is_admin"]:
            short = conn.execute("SELECT COUNT(*) n FROM upload_attempts WHERE user_id=? AND created_at >= datetime('now','-10 minutes')", (user["id"],)).fetchone()["n"]
            daily = conn.execute("SELECT COUNT(*) n FROM upload_attempts WHERE user_id=? AND created_at >= datetime('now','-1 day')", (user["id"],)).fetchone()["n"]
            if short >= UPLOAD_LIMIT_10_MINUTES or daily >= UPLOAD_LIMIT_DAILY:
                wait = "10 minutes" if short >= UPLOAD_LIMIT_10_MINUTES else "24 hours"
                flash(f"Upload limit reached. Please try again after the oldest submission leaves the {wait} window.", "error")
                return redirect(url_for("submit_link"))

        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        program = _team_program(request.form.get("program")) or "ftc"
        cad_software = (request.form.get("cad_software") or "other").strip().lower()
        cad_link = (request.form.get("cad_link") or "").strip()
        season_id = request.form.get("season_id", type=int)
        archetype_id = request.form.get("archetype_id", type=int)
        competition_tested_raw = request.form.get("competition_tested")
        team_choice = (request.form.get("team_id") or "").strip()
        # Admins credit a design to any team by number and name (an "unregistered
        # creator"), exactly as the full form does; their attribution select
        # stands in for the ordinary team picker.
        admin_team_number = None
        admin_team_name = ""
        if user["is_admin"]:
            team_choice = (request.form.get("admin_attribution") or team_choice).strip()
            if team_choice == "team":
                admin_team_number = request.form.get("admin_team_number", type=int)
                admin_team_name = (request.form.get("admin_team_name") or "").strip()
        upload_certification_accepted = request.form.get("upload_certification") == "accepted"
        team_id = None
        if user["is_admin"] and team_choice == "team" and admin_team_number:
            existing_team = conn.execute(
                "SELECT id FROM teams WHERE program=? AND number=?",
                (program, admin_team_number),
            ).fetchone()
            team_id = existing_team["id"] if existing_team else None
        elif team_choice and team_choice != "individual":
            try:
                team_id = int(team_choice)
            except ValueError:
                team_id = None

        if team_id:
            selected_team = conn.execute(
                "SELECT program FROM teams WHERE id=?", (team_id,)
            ).fetchone()
            if selected_team:
                program = selected_team["program"]

        # Old clients may post a stale catalog id; keep the long-standing
        # behavior of treating that as no model type instead of rejecting the
        # entire share.
        if archetype_id and conn.execute(
            "SELECT 1 FROM archetypes WHERE id=?", (archetype_id,)
        ).fetchone() is None:
            archetype_id = None
        taxonomy_message = _design_taxonomy_error(
            conn, program, season_id, archetype_id
        )

        image_files = [f for f in request.files.getlist("image_files") if f.filename][:8]

        error = None
        image_filename = None
        image_filenames = []

        if not team_choice:
            error = "Choose whether this design is shared for you individually or for a team."
        elif user["is_admin"] and team_choice == "team" and (
            admin_team_number is None or not 1 <= admin_team_number <= 999999
        ):
            error = "Enter a valid team number."
        elif not user["is_admin"] and team_choice != "individual" and (
            team_id is None or conn.execute(
                "SELECT 1 FROM memberships WHERE user_id=? AND team_id=?",
                (user["id"], team_id),
            ).fetchone() is None
        ):
            error = "Choose yourself or a team you belong to."
        elif not title:
            error = "Please give your design a title."
        elif taxonomy_message:
            error = taxonomy_message
        elif cad_software not in LINKED_CAD_SOFTWARE:
            error = "Choose the CAD software used for this design."
        elif not cad_link:
            error = "Add a link to your model so people can open it."
        elif urlparse(cad_link).scheme not in {"http", "https"} or not urlparse(cad_link).netloc:
            error = "Please enter a valid model link (starting with http:// or https://)."
        elif competition_tested_raw not in {"0", "1"}:
            error = "Choose whether this design has been competition tested."
        elif not image_files:
            error = "Add at least one image of your design."
        elif not upload_certification_accepted:
            error = "You must accept the Upload Certification before publishing."

        if error is None:
            try:
                moderate_public_content(
                    texts=[title, description, admin_team_name,
                           request.form.get("tags") or ""],
                    use_api=not app.testing,
                )
                image_filename = core.save_image_upload(image_files.pop(0))
                image_filenames.append(image_filename)
                for image_file in image_files:
                    image_filenames.append(core.save_image_upload(image_file))
            except ValueError as exc:
                error = str(exc)

        storage_bytes = 0
        if error is None:
            storage_bytes = sum(
                infra_storage.size("uploads", filename) for filename in image_filenames
            )

        if error is not None:
            for filename in image_filenames:
                delete_asset(UPLOAD_DIR, filename)
            flash(error, "error")
        else:
            # Attribution to a team not yet on Botfolio creates a lightweight
            # reference profile a real representative can later claim; an
            # existing reference profile gets its name refreshed.
            if user["is_admin"] and team_choice == "team":
                admin_team_name = credit_team_name(
                    conn, admin_team_number, admin_team_name, program=program
                )
                if team_id is None:
                    team_id = conn.execute(
                        "INSERT INTO teams(program,number,name,invite_code,profile_status) VALUES (?,?,?,?,'reference')",
                        (program, admin_team_number, admin_team_name, secrets.token_urlsafe(18)),
                    ).lastrowid
                elif conn.execute(
                    "SELECT profile_status FROM teams WHERE id=?", (team_id,)
                ).fetchone()["profile_status"] == "reference":
                    conn.execute("UPDATE teams SET name=? WHERE id=?",
                                 (admin_team_name, team_id))
            cur = conn.execute(
                """
                INSERT INTO designs (
                    user_id, team_id, program, title, description, onshape_link,
                    cad_software, cad_link, season_id, archetype_id,
                    competition_tested, image_filename,
                    upload_certification_version,
                    upload_certification_accepted, storage_bytes, upload_status,
                    uploaded_by_admin
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'approved', ?)
                """,
                (
                    user["id"],
                    team_id or None,
                    program,
                    title,
                    description,
                    cad_link if cad_software == "onshape" else None,
                    cad_software,
                    cad_link,
                    season_id or None,
                    archetype_id or None,
                    int(competition_tested_raw),
                    image_filename,
                    UPLOAD_CERTIFICATION_VERSION,
                    storage_bytes,
                    int(bool(user["is_admin"])),
                ),
            )
            design_id = cur.lastrowid
            if user["is_admin"] and team_id:
                conn.execute(
                    "UPDATE designs SET team_attribution_accepted=0 WHERE id=?",
                    (design_id,),
                )
            for position, filename in enumerate(image_filenames):
                conn.execute(
                    "INSERT INTO design_images(design_id,filename,position) VALUES (?,?,?)",
                    (design_id, filename, position),
                )
            if not user["is_admin"]:
                conn.execute("INSERT INTO upload_attempts (user_id) VALUES (?)", (user["id"],))
            conn.execute(
                "UPDATE users SET storage_used_bytes=storage_used_bytes+? WHERE id=?",
                (storage_bytes, user["id"]),
            )

            # A rejected tag (too long, too many, coined too fast) undoes the
            # whole publish rather than leaving a design with a half-applied
            # tag list, exactly as the full form does.
            try:
                for raw in (request.form.get("tags") or "").split(","):
                    if raw.strip():
                        attach_tag(design_id, raw, user["id"])
                qualify_founding_contributor(conn, user["id"])
                qualify_founding_team(conn, team_id)
            except ValueError as exc:
                conn.rollback()
                for filename in image_filenames:
                    delete_asset(UPLOAD_DIR, filename)
                flash(str(exc), "error")
                return redirect(url_for("submit_link"))

            conn.commit()
            notify_design_published(
                settings.discord_showcase_webhook_url,
                design_url=url_for("design_detail", design_id=design_id, _external=True),
                title=title,
                author=user["username"],
                description=description,
                image_url=infra_storage.url("uploads", image_filename, external=True),
            )
            flash("Design published.", "success")
            return redirect(url_for("design_detail", design_id=design_id))

    seasons = conn.execute("SELECT * FROM seasons ORDER BY program,sort_order DESC").fetchall()
    teams = conn.execute(
        "SELECT t.* FROM teams t JOIN memberships m ON m.team_id = t.id "
        "WHERE m.user_id = ? ORDER BY t.number",
        (user["id"],),
    ).fetchall()
    # Every model type is sent to the page and narrowed to the chosen season in
    # the browser, the same way the full form does it.
    archetypes = conn.execute("SELECT * FROM archetypes ORDER BY name").fetchall()
    return render_template(
        "submit_link.html", seasons=seasons, teams=teams, archetypes=archetypes,
        cad_software_choices=LINKED_CAD_SOFTWARE, programs=TEAM_PROGRAMS,
        selected_program=_team_program(request.values.get("program")) or "ftc",
    )


def _owned_design_or_404(design_id):
    design = db.get_db().execute(
        "SELECT * FROM designs WHERE id = ?", (design_id,)
    ).fetchone()
    if design is None:
        abort(404)
    user = current_user()
    if user is None or (design["user_id"] != user["id"] and not user["is_admin"]):
        abort(403)
    return design


@designs_bp.route("/designs/<int:design_id>/orientation", methods=["POST"])
# The same ceiling as editing the design, which is what this is: a small,
# deliberate edit made a couple of times at most, from a wizard that takes two
# camera moves to complete.
@ratelimit.limit(
    "design-edit", 20, 600,
    exempt=lambda: bool(current_user() and current_user()["is_admin"]),
)
@login_required
def set_design_orientation(design_id):
    """Store which way a model faces, from the viewer's orientation sequence.

    The design page has no form to hang this on — the viewer opens in a dialog
    over a page that is otherwise read-only — so the sequence posts here
    directly and the reply is read by JavaScript rather than a browser.

    Owner or admin only, the same gate as editing: this is not a per-visitor
    preference but a property of the design that decides what its Front button
    means for everybody afterwards.
    """
    design = _owned_design_or_404(design_id)
    if not model_is_viewable(design["model_filename"]):
        return jsonify(error="This design has no model to orient."), 400

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="The viewer sent nothing to save."), 400

    # The sequence sends the whole viewer state, camera included, because
    # re-orienting turns the saved angle along with the model. `existing` is
    # not passed: an empty orientation here is the sequence's undo, and has to
    # be able to clear what is stored rather than inherit it back.
    state = clean_viewer_state(json.dumps(payload))
    conn = db.get_db()
    conn.execute("UPDATE designs SET camera_json=? WHERE id=?", (state, design_id))
    conn.commit()
    return jsonify(ok=True, camera_json=state)


@designs_bp.route("/designs/<int:design_id>/edit", methods=["GET", "POST"])
# The form accepts replacement pictures and a replacement 3D model, so it
# needs the same bandwidth ceiling as publishing: MAX_CONTENT_LENGTH is
# 400 MB, and without a cap one client can post that in a loop. Only the
# POST half counts, so reopening the form to fix a typo stays free.
@ratelimit.limit(
    "design-edit", 20, 600,
    exempt=lambda: bool(current_user() and current_user()["is_admin"]),
)
@login_required
def edit_design(design_id):
    design = _owned_design_or_404(design_id)
    conn = db.get_db()
    selected_program = design["program"]
    selected_season = design["season_id"]
    selected_archetype = design["archetype_id"]
    # Admins can re-credit an admin-uploaded design to a named creator team that
    # may not be a registered Botfolio team (the "unregistered creator" case).
    user = current_user()
    admin_can_edit_team = bool(user["is_admin"] and design["uploaded_by_admin"])
    # A quick (link-only) design has no prototype version and no stored model
    # file. Editing one shows just the quick fields until the owner opts into the
    # full form (?full=1 on GET, a hidden full_mode flag carried through POST).
    is_quick = design["prototype_version"] is None and not design["model_filename"]
    requested_full = ((request.form.get("full_mode") == "1") if request.method == "POST"
                      else (request.args.get("full") == "1"))
    full_mode = (not is_quick) or requested_full
    cad_choices = LINKED_CAD_SOFTWARE if is_quick else CAD_SOFTWARE
    # Anyone who can edit the design can also replace its attached files.
    can_add_model = full_mode

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        # Older clients do not send this new field, so omission keeps the
        # design where it already lives; an explicit unknown value is rejected.
        program = _team_program(
            request.form.get("program"), default=design["program"]
        )
        cad_software = (request.form.get("cad_software") or "").strip().lower()
        cad_link = (request.form.get("cad_link") or "").strip()
        season_id = request.form.get("season_id", type=int)
        archetype_id = request.form.get("archetype_id", type=int)
        selected_program = program or design["program"]
        selected_season = season_id
        selected_archetype = archetype_id
        prototype_version = request.form.get("prototype_version", type=int)
        if cad_software == CAD_DOWNLOAD_ONLY:
            cad_link = ""
        competition_tested_raw = request.form.get("competition_tested")
        dimension_unit = (request.form.get("dimension_unit") or design["dimension_unit"] or "in").strip().lower()
        length_in = request.form.get("length_in", type=float)
        width_in = request.form.get("width_in", type=float)
        height_in = request.form.get("height_in", type=float)
        dimension_raws = [(request.form.get(name) or "").strip()
                          for name in ("length_in", "width_in", "height_in")]
        if dimension_unit == "mm":
            length_in, width_in, height_in = (
                round(value / 25.4, 6) if value is not None else None
                for value in (length_in, width_in, height_in)
            )
        dimension_message = dimension_error(
            dimension_raws, (length_in, width_in, height_in))
        motor_count_raw = (request.form.get("motor_count") or "").strip()
        servo_count_raw = (request.form.get("servo_count") or "").strip()
        motor_count = request.form.get("motor_count", type=int)
        servo_count = request.form.get("servo_count", type=int)
        contributor_usernames = request.form.getlist("contributor_username")
        contributor_roles = request.form.getlist("contributor_role")
        if archetype_id and conn.execute(
            "SELECT 1 FROM archetypes WHERE id=?", (archetype_id,)
        ).fetchone() is None:
            archetype_id = None
        taxonomy_message = (
            _design_taxonomy_error(conn, program, season_id, archetype_id)
            if program else None
        )

        admin_attribution = (request.form.get("admin_attribution") or "").strip()
        admin_team_number = request.form.get("admin_team_number", type=int)
        admin_team_name = (request.form.get("admin_team_name") or "").strip()

        # A recaptured 3D preview replaces the gallery cover. It applies only to a
        # design that already carries a browser-viewable mesh — the owner
        # re-oriented it in the edit page's viewer and captured a new angle. A
        # stray data URL on any other design is ignored.
        preview_data_url = request.form.get("preview_data_url") or ""
        can_recapture_preview = (
            preview_data_url.startswith("data:image/")
            and model_is_viewable(design["model_filename"], design["model_size_bytes"])
        )

        if not title:
            flash("Please give your design a title.", "error")
        elif not program:
            flash("Choose the robotics program this design belongs to.", "error")
        elif admin_can_edit_team and admin_attribution not in {"individual", "team"}:
            flash("Choose whether this design is credited to an individual or a team.", "error")
        elif admin_can_edit_team and admin_attribution == "team" and (admin_team_number is None or not 1 <= admin_team_number <= 999999):
            flash("Enter a valid team number.", "error")
        elif cad_software not in cad_choices:
            flash("Choose the CAD software used for this design.", "error")
        elif cad_link and (urlparse(cad_link).scheme not in {"http", "https"} or not urlparse(cad_link).netloc):
            flash("Please enter a valid CAD design link.", "error")
        elif taxonomy_message:
            flash(taxonomy_message, "error")
        elif full_mode and (prototype_version is None or not 1 <= prototype_version <= 99):
            flash("Enter a prototype version between V1 and V99.", "error")
        elif competition_tested_raw not in {"0", "1"}:
            flash("Choose whether this design has been competition tested.", "error")
        elif full_mode and dimension_unit not in {"in", "mm"}:
            flash("Choose inches or millimeters for the dimensions.", "error")
        elif full_mode and dimension_message:
            flash(dimension_message, "error")
        elif motor_count_raw and (motor_count is None or not 0 <= motor_count <= 99):
            flash("Motor count must be between 0 and 99.", "error")
        elif servo_count_raw and (servo_count is None or not 0 <= servo_count <= 99):
            flash("Servo count must be between 0 and 99.", "error")
        else:
            new_model = None
            new_model_size = 0
            new_model_sha = None
            new_preview_image = None
            new_preview_size = 0
            old_preview_image = None
            new_images = []
            replaced_images = False
            replaced_model = False
            try:
                moderate_public_content(
                    texts=[title, description] + ([admin_team_name] if admin_can_edit_team else []),
                    use_api=not app.testing,
                )
                image_files = [
                    upload for upload in request.files.getlist("image_files")
                    if upload.filename
                ][:8]
                if full_mode and image_files:
                    new_images = [core.save_image_upload(upload) for upload in image_files]
                    replaced_images = True

                # Large models land in object storage first and arrive here as a
                # token, matching the publish flow.
                if can_add_model:
                    model_file = request.files.get("model_file")
                    model_upload_token = (request.form.get("model_upload_token") or "").strip()
                    if model_file and model_file.filename:
                        new_model, new_model_size, new_model_sha = core.save_model_upload(model_file)
                        replaced_model = True
                    elif model_upload_token:
                        new_model, new_model_size, new_model_sha = finalize_model_upload(
                            model_upload_token, user
                        )
                # Sanitize, moderate, and store the recaptured cover before any
                # database write, so a rejected image aborts the whole save.
                if can_recapture_preview and not replaced_images:
                    new_preview_image = core.save_preview_data_url(preview_data_url)
                    new_preview_size = _safe_upload_size(new_preview_image)
                if new_model:
                    replaced_model = True
                # A team credit cannot cross programs. Ordinary authors keep the
                # credit when the program still matches; switching programs
                # removes it. Admin uploads can immediately choose a replacement.
                new_team_id = design["team_id"]
                team_credit_removed = False
                if new_team_id:
                    credited_team = conn.execute(
                        "SELECT program FROM teams WHERE id=?", (new_team_id,)
                    ).fetchone()
                    if credited_team and credited_team["program"] != program:
                        new_team_id = None
                        team_credit_removed = True
                if admin_can_edit_team:
                    if admin_attribution == "individual":
                        new_team_id = None
                    else:
                        admin_team_name = credit_team_name(
                            conn, admin_team_number, admin_team_name,
                            program=program,
                        )
                        existing_team = conn.execute(
                            "SELECT id FROM teams WHERE program=? AND number=?",
                            (program, admin_team_number),
                        ).fetchone()
                        if existing_team:
                            new_team_id = existing_team["id"]
                            status = conn.execute(
                                "SELECT profile_status FROM teams WHERE id=?",
                                (existing_team["id"],),
                            ).fetchone()["profile_status"]
                            if status == "reference":
                                conn.execute("UPDATE teams SET name=? WHERE id=?",
                                             (admin_team_name, existing_team["id"]))
                        else:
                            new_team_id = conn.execute(
                                "INSERT INTO teams(program,number,name,invite_code,profile_status) VALUES (?,?,?,?,'reference')",
                                (program, admin_team_number, admin_team_name,
                                 secrets.token_urlsafe(18)),
                            ).lastrowid
                if full_mode:
                    conn.execute(
                        "UPDATE designs SET program = ?, title = ?, description = ?, cad_software = ?, cad_link = ?, onshape_link = ?, season_id = ?, "
                        "archetype_id = ?, prototype_version = ?, competition_tested = ?, "
                        "length_in = ?, width_in = ?, height_in = ?, dimension_unit = ?, motor_count = ?, servo_count = ?, team_id = ?, "
                        "updated_at = datetime('now') WHERE id = ?",
                        (program, title, description, cad_software, cad_link or None,
                         cad_link if cad_software == "onshape" else None,
                         season_id or None, archetype_id or None,
                         prototype_version, int(competition_tested_raw), length_in, width_in,
                         height_in, dimension_unit, motor_count, servo_count, new_team_id, design_id),
                    )
                else:
                    # Quick edit: touch only the fields the quick form exposes so
                    # the full-only columns (specs, prototype, contributors) keep
                    # their existing values instead of being cleared to NULL.
                    conn.execute(
                        "UPDATE designs SET program = ?, title = ?, description = ?, cad_software = ?, "
                        "cad_link = ?, onshape_link = ?, season_id = ?, archetype_id = ?, "
                        "competition_tested = ?, team_id = ?, "
                        "updated_at = datetime('now') WHERE id = ?",
                        (program, title, description, cad_software, cad_link or None,
                         cad_link if cad_software == "onshape" else None,
                         season_id or None, archetype_id or None,
                         int(competition_tested_raw), new_team_id, design_id),
                    )
                old_images = [row["filename"] for row in conn.execute(
                    "SELECT filename FROM design_images WHERE design_id=? ORDER BY position,id",
                    (design_id,),
                ).fetchall()]
                old_image_bytes = max(0, design["storage_bytes"] - design["model_size_bytes"])
                new_image_bytes = sum(
                    infra_storage.size("uploads", filename) for filename in new_images
                ) if replaced_images else old_image_bytes
                final_model_bytes = new_model_size if replaced_model else design["model_size_bytes"]
                storage_delta = (new_image_bytes + final_model_bytes) - design["storage_bytes"]

                if replaced_images:
                    conn.execute("DELETE FROM design_images WHERE design_id=?", (design_id,))
                    for position, filename in enumerate(new_images):
                        conn.execute(
                            "INSERT INTO design_images(design_id,filename,position) VALUES (?,?,?)",
                            (design_id, filename, position),
                        )
                    # New photos mean the old preview angle belongs to a cover
                    # that is gone, so the camera goes with it — but an
                    # orientation is a fact about the mesh, which nobody
                    # touched here, so it is carried across.
                    conn.execute(
                        "UPDATE designs SET image_filename=?, camera_json=? WHERE id=?",
                        (new_images[0],
                         clean_viewer_state(None, existing=design["camera_json"]),
                         design_id),
                    )
                if replaced_model:
                    conn.execute(
                        "UPDATE designs SET model_filename=?, model_size_bytes=?, "
                        "model_sha256=? WHERE id=?",
                        (new_model, new_model_size, new_model_sha, design_id),
                    )
                if replaced_images or replaced_model:
                    conn.execute(
                        "UPDATE designs SET storage_bytes=? WHERE id=?",
                        (new_image_bytes + final_model_bytes, design_id),
                    )
                    conn.execute(
                        "UPDATE users SET storage_used_bytes=CASE WHEN storage_used_bytes+? >= 0 "
                        "THEN storage_used_bytes+? ELSE 0 END WHERE id=?",
                        (storage_delta, storage_delta, design["user_id"]),
                    )
                if new_preview_image:
                    old_preview_image = design["image_filename"]
                    old_preview_size = _safe_upload_size(old_preview_image)
                    new_camera = clean_viewer_state(
                        request.form.get("camera_json") or "",
                        existing=design["camera_json"],
                    )
                    conn.execute(
                        "UPDATE designs SET image_filename=?, camera_json=?, "
                        "storage_bytes=storage_bytes-?+? WHERE id=?",
                        (new_preview_image, new_camera, old_preview_size,
                         new_preview_size, design_id),
                    )
                    # Keep the gallery cover (the design_images row that mirrors
                    # designs.image_filename) pointing at the same file, so cards
                    # and the detail gallery show the new angle too.
                    if old_preview_image:
                        conn.execute(
                            "UPDATE design_images SET filename=? "
                            "WHERE design_id=? AND filename=?",
                            (new_preview_image, design_id, old_preview_image),
                        )
                    conn.execute(
                        "UPDATE users SET storage_used_bytes="
                        "storage_used_bytes-?+? WHERE id=?",
                        (old_preview_size, new_preview_size, design["user_id"]),
                    )
                # A replaced mesh invalidates the saved camera: those angles
                # were measured against the old geometry and the viewer
                # applies them verbatim, so keeping them would open the new
                # model off-screen. Cleared after the recapture block so an
                # angle captured from the old mesh in this same save cannot
                # put them back.
                #
                # This clears the orientation too, unlike the replaced-photos
                # branch above. A correction names two faces of one particular
                # mesh; carried onto a different file it would confidently
                # point at the wrong ones, which is worse than the file's own
                # axes, since nothing on the page would suggest it is wrong.
                if replaced_model:
                    conn.execute(
                        "UPDATE designs SET camera_json=NULL WHERE id=?", (design_id,)
                    )
                if admin_can_edit_team and admin_attribution == "team" and new_team_id != design["team_id"]:
                    conn.execute(
                        "UPDATE designs SET team_attribution_accepted=0 WHERE id=?",
                        (design_id,),
                    )
                if full_mode:
                    save_design_contributors(conn, design_id, contributor_usernames, contributor_roles)
                conn.commit()
                # The replaced cover is unreferenced now that the row is committed.
                if old_preview_image:
                    delete_asset(UPLOAD_DIR, old_preview_image)
                if replaced_images:
                    for filename in set(old_images + [design["image_filename"]]):
                        delete_asset(UPLOAD_DIR, filename)
                if replaced_model:
                    delete_asset(MODEL_DIR, design["model_filename"])
                if team_credit_removed and not new_team_id:
                    flash(
                        "Design updated. Its previous team credit was removed because that team belongs to a different program.",
                        "success",
                    )
                else:
                    flash("Design updated.", "success")
                return redirect(url_for("design_detail", design_id=design_id))
            except ValueError as exc:
                if new_model:
                    delete_asset(MODEL_DIR, new_model)
                if new_preview_image:
                    delete_asset(UPLOAD_DIR, new_preview_image)
                for filename in new_images:
                    delete_asset(UPLOAD_DIR, filename)
                flash(str(exc), "error")

    # Send both programs so the browser can swap the dependent choices without
    # throwing away the rest of the edit form in a reload.
    seasons = conn.execute(
        "SELECT * FROM seasons ORDER BY program,sort_order DESC"
    ).fetchall()
    archetypes = conn.execute(
        """SELECT DISTINCT a.*,s.program season_program FROM archetypes a
             LEFT JOIN seasons s ON s.id=a.season_id
            ORDER BY a.name""",
    ).fetchall()
    contributors = conn.execute("SELECT u.username,dc.role FROM design_contributors dc JOIN users u ON u.id=dc.user_id WHERE dc.design_id=? ORDER BY dc.credited_at,u.username", (design_id,)).fetchall()
    design_images = conn.execute(
        "SELECT filename FROM design_images WHERE design_id=? ORDER BY position,id",
        (design_id,),
    ).fetchall()
    current_team = conn.execute(
        "SELECT program,number,name FROM teams WHERE id=?", (design["team_id"],)
    ).fetchone() if design["team_id"] else None
    return render_template(
        "edit_design.html", design=design, seasons=seasons, archetypes=archetypes,
        contributors=contributors, contributor_roles=CONTRIBUTOR_ROLES,
        design_images=design_images,
        cad_software_choices=cad_choices,
        programs=TEAM_PROGRAMS, selected_program=selected_program,
        selected_season=selected_season, selected_archetype=selected_archetype,
        admin_can_edit_team=admin_can_edit_team, current_team=current_team,
        can_add_model=can_add_model,
        model_viewable=model_is_viewable(
            design["model_filename"], design["model_size_bytes"]
        ),
        direct_model_uploads=settings.uses_direct_model_uploads,
        full_mode=full_mode, is_quick=is_quick,
    )
