"""Engineering resources, BOMs, and relationships attached to design posts."""

import csv
import io
from pathlib import Path

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

import app as core


engineering_bp = Blueprint("engineering", __name__)


def _owned(conn, design_id):
    design = conn.execute("SELECT id,user_id,is_hidden FROM designs WHERE id=?", (design_id,)).fetchone()
    user = core.current_user()
    if design is None or not user or (user["id"] != design["user_id"] and not user["is_admin"]):
        abort(404)
    return design


def _money(value):
    if not (value or "").strip():
        return None
    try:
        cents = round(float(value) * 100)
    except ValueError:
        raise ValueError("Costs must be valid positive numbers.")
    if cents < 0 or cents > 100_000_000:
        raise ValueError("Costs must be between 0 and 1,000,000.")
    return cents


@engineering_bp.post("/designs/<int:design_id>/engineering/cost")
@core.login_required
def update_cost(design_id):
    conn = core.db.get_db()
    _owned(conn, design_id)
    try:
        low, high = _money(request.form.get("cost_low")), _money(request.form.get("cost_high"))
        if low is not None and high is not None and low > high:
            raise ValueError("The low estimate cannot exceed the high estimate.")
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("design_detail", design_id=design_id) + "#engineering-resources")
    conn.execute("UPDATE designs SET replacement_cost_low_cents=?,replacement_cost_high_cents=?,replacement_cost_currency='USD',updated_at=datetime('now') WHERE id=?", (low, high, design_id))
    conn.commit()
    flash("Replacement-cost estimate updated.", "success")
    return redirect(url_for("design_detail", design_id=design_id) + "#engineering-resources")


@engineering_bp.post("/designs/<int:design_id>/engineering/resources")
@core.login_required
def add_resource(design_id):
    conn = core.db.get_db()
    _owned(conn, design_id)
    upload = request.files.get("resource_file")
    name = (request.form.get("name") or "").strip()[:120]
    if not name or not upload or not upload.filename:
        flash("Give the subsystem a name and choose a CAD file.", "error")
        return redirect(url_for("design_detail", design_id=design_id) + "#subsystems")
    try:
        filename, size, digest = core.save_model_upload(upload)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("design_detail", design_id=design_id) + "#subsystems")
    function_key = (request.form.get("function_key") or "").strip()
    if function_key not in core.DESIGN_FUNCTIONS:
        function_key = None
    conn.execute("INSERT INTO design_resources(design_id,kind,name,description,function_key,filename,original_filename,size_bytes,sha256) VALUES(?,?,?,?,?,?,?,?,?)", (design_id, "subsystem", name, (request.form.get("description") or "").strip()[:500], function_key, filename, secure_filename(upload.filename), size, digest))
    conn.commit()
    flash("Subsystem added.", "success")
    return redirect(url_for("design_detail", design_id=design_id) + "#subsystems")


@engineering_bp.get("/resources/<int:resource_id>/download")
@core.login_required
def download_resource(resource_id):
    conn = core.db.get_db()
    row = conn.execute("SELECT r.*,d.is_hidden,d.user_id FROM design_resources r JOIN designs d ON d.id=r.design_id WHERE r.id=?", (resource_id,)).fetchone()
    user = core.current_user()
    if row is None or not row["filename"] or (row["is_hidden"] and user["id"] != row["user_id"] and not user["is_admin"]):
        abort(404)
    response = core.infra_storage.send("models", row["filename"], as_attachment=True)
    if response.status_code in core.DOWNLOAD_COUNTED_STATUSES:
        key = core.visitor_key()
        recent = conn.execute("SELECT 1 FROM resource_downloads WHERE resource_id=? AND visitor_key=? AND downloaded_at>=datetime('now',?)", (resource_id, key, f"-{core.DOWNLOAD_COOLDOWN_MINUTES} minutes")).fetchone()
        if not recent:
            conn.execute("INSERT INTO resource_downloads(resource_id,user_id,visitor_key) VALUES(?,?,?)", (resource_id, user["id"], key))
            conn.commit()
    return response


@engineering_bp.get("/resources/<int:resource_id>/preview")
@core.login_required
def preview_resource(resource_id):
    conn = core.db.get_db()
    row = conn.execute("SELECT r.*,d.title design_title,d.is_hidden,d.user_id FROM design_resources r JOIN designs d ON d.id=r.design_id WHERE r.id=?", (resource_id,)).fetchone()
    user = core.current_user()
    if row is None or not core.model_is_viewable(row["filename"], row["size_bytes"]) or (row["is_hidden"] and user["id"] != row["user_id"] and not user["is_admin"]):
        abort(404)
    return render_template("resource_preview.html", resource=row)


@engineering_bp.get("/resources/<int:resource_id>/model")
@core.login_required
def resource_model(resource_id):
    conn = core.db.get_db()
    row = conn.execute("SELECT r.filename,r.size_bytes,d.is_hidden,d.user_id FROM design_resources r JOIN designs d ON d.id=r.design_id WHERE r.id=?", (resource_id,)).fetchone()
    user = core.current_user()
    if row is None or not core.model_is_viewable(row["filename"], row["size_bytes"]) or (row["is_hidden"] and user["id"] != row["user_id"] and not user["is_admin"]):
        abort(404)
    return core.infra_storage.send("models", row["filename"])


@engineering_bp.post("/designs/<int:design_id>/engineering/relationships")
@core.login_required
def add_relationship(design_id):
    conn = core.db.get_db()
    _owned(conn, design_id)
    target_id = request.form.get("target_design_id", type=int)
    if not target_id or target_id == design_id or not conn.execute("SELECT 1 FROM designs WHERE id=? AND is_hidden=0", (target_id,)).fetchone():
        flash("Choose a different, published Botfolio design.", "error")
    else:
        conn.execute("INSERT OR IGNORE INTO design_relationships(source_design_id,target_design_id,relationship_type,label,created_by) VALUES(?,?,'has_subsystem',?,?)", (design_id, target_id, (request.form.get("label") or "").strip()[:120], core.current_user()["id"]))
        conn.commit()
        flash("Linked subsystem added.", "success")
    return redirect(url_for("design_detail", design_id=design_id) + "#subsystems")


@engineering_bp.post("/designs/<int:design_id>/engineering/bom")
@core.login_required
def add_bom_item(design_id):
    conn = core.db.get_db()
    _owned(conn, design_id)
    name = (request.form.get("part_name") or "").strip()[:160]
    try:
        quantity = float(request.form.get("quantity") or 1)
        cost = _money(request.form.get("unit_cost"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("design_detail", design_id=design_id) + "#bom")
    if not name or quantity <= 0 or quantity > 100000:
        flash("Enter a part name and a positive quantity.", "error")
    else:
        conn.execute("INSERT INTO bom_items(design_id,part_name,part_number,manufacturer,quantity,unit,unit_cost_cents,product_url,notes) VALUES(?,?,?,?,?,?,?,?,?)", (design_id, name, (request.form.get("part_number") or "").strip()[:120], (request.form.get("manufacturer") or "").strip()[:120], quantity, (request.form.get("unit") or "ea").strip()[:20], cost, (request.form.get("product_url") or "").strip()[:1000] or None, (request.form.get("notes") or "").strip()[:500]))
        conn.commit()
        flash("BOM item added.", "success")
    return redirect(url_for("design_detail", design_id=design_id) + "#bom")


@engineering_bp.post("/designs/<int:design_id>/engineering/bom/import")
@core.login_required
def import_bom(design_id):
    conn = core.db.get_db()
    _owned(conn, design_id)
    upload = request.files.get("bom_csv")
    if not upload or not upload.filename:
        flash("Choose a CSV file to import.", "error")
        return redirect(url_for("design_detail", design_id=design_id) + "#bom")
    try:
        text = upload.read(2_000_001).decode("utf-8-sig")
        if len(text) > 2_000_000:
            raise ValueError("CSV files must be 2 MB or smaller.")
        rows, added = csv.DictReader(io.StringIO(text)), 0
        for row in rows:
            name = (row.get("part_name") or row.get("name") or "").strip()[:160]
            if not name:
                continue
            quantity = float(row.get("quantity") or 1)
            cost = _money(row.get("unit_cost") or "")
            conn.execute("INSERT INTO bom_items(design_id,part_name,part_number,manufacturer,quantity,unit,unit_cost_cents,product_url,notes) VALUES(?,?,?,?,?,?,?,?,?)", (design_id, name, (row.get("part_number") or "")[:120], (row.get("manufacturer") or "")[:120], quantity, (row.get("unit") or "ea")[:20], cost, (row.get("product_url") or "")[:1000] or None, (row.get("notes") or "")[:500]))
            added += 1
        conn.commit()
        flash(f"Imported {added} BOM item{'s' if added != 1 else ''}.", "success")
    except (UnicodeDecodeError, ValueError, csv.Error):
        conn.rollback()
        flash("That CSV could not be imported. Use UTF-8 with part_name and quantity columns.", "error")
    return redirect(url_for("design_detail", design_id=design_id) + "#bom")


@engineering_bp.get("/designs/<int:design_id>/engineering/bom.csv")
def export_bom(design_id):
    conn = core.db.get_db()
    if not conn.execute("SELECT 1 FROM designs WHERE id=? AND is_hidden=0", (design_id,)).fetchone():
        abort(404)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["part_name", "part_number", "manufacturer", "quantity", "unit", "unit_cost", "product_url", "notes"])
    for row in conn.execute("SELECT * FROM bom_items WHERE design_id=? ORDER BY position,id", (design_id,)).fetchall():
        writer.writerow([row["part_name"], row["part_number"], row["manufacturer"], row["quantity"], row["unit"], "" if row["unit_cost_cents"] is None else f'{row["unit_cost_cents"] / 100:.2f}', row["product_url"] or "", row["notes"]])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="botfolio-{design_id}-bom.csv"'})
