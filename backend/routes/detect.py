"""Damage detection routes for Admin (official reports) and User (temporary analysis)."""
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from flask import Blueprint, jsonify, request, send_file, send_from_directory, session
from werkzeug.utils import secure_filename

import config
from routes.auth import admin_required, login_required, user_required
from services import db
from services.damage_detector import analyze

bp = Blueprint("detect", __name__)


def _is_safe_path(base_dir: Path, target_path: Path) -> bool:
    try:
        resolved = target_path.resolve()
        return base_dir.resolve() in resolved.parents or resolved == base_dir.resolve()
    except Exception:
        return False


def _extract_report_id(filename: str) -> str:
    # Match patterns like R-101, R-102_annotated.jpg, R-101_s1.jpg
    m = re.match(r"^(R-\d+)", Path(filename).name)
    return m.group(1) if m else ""


# ---------------- ADMIN OFFICIAL VEHICLE ANALYSIS ----------------

@bp.post("/api/admin/detect-damage")
@admin_required
def admin_detect_damage():
    admin_id = session["user_id"]
    rid = db.next_report_id()

    # 1. Mandatory User Selection
    target_user_id_raw = request.form.get("user_id") or request.form.get("target_user_id")
    if not target_user_id_raw:
        return jsonify(error="Please select a registered user before performing an official analysis."), 400

    try:
        target_user_id = int(target_user_id_raw)
    except (ValueError, TypeError):
        return jsonify(error="Invalid user selected. Please select a valid registered user."), 400

    target_user = db.get_user_by_id(target_user_id)
    if not target_user:
        return jsonify(error="Selected user was not found. Please choose an existing user."), 400

    if target_user.get("role") != "user":
        return jsonify(error="Official damage reports can only be assigned to accounts with the 'user' role."), 400

    # 2. File handling
    f = request.files.get("image")
    folder = request.form.get("folder", "").strip()
    name = request.form.get("name", "").strip()
    location, shown_name = "(browser upload)", name or "-"

    try:
        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        if f and f.filename:
            ext = Path(f.filename).suffix.lower()
            shown_name = secure_filename(f.filename) or f"{rid}.jpg"
            if ext not in config.ALLOWED_EXT:
                raise ValueError("Only JPG, JPEG or PNG images are supported.")
            saved_path = config.UPLOAD_DIR / f"{rid}{ext}"
            f.save(saved_path)
        elif folder and name:
            if not config.ALLOW_LOCAL_PATHS:
                raise ValueError("Local-path analysis is disabled outside trusted development environments. Please upload or capture an image file.")
            location = folder
            folder_path = Path(folder)
            if not folder_path.is_dir():
                raise ValueError("The specified image folder path does not exist on this computer.")
            src = folder_path / name
            if not _is_safe_path(folder_path, src) or not src.is_file():
                raise ValueError("The specified image name was not found inside that folder.")
            ext = src.suffix.lower()
            if ext not in config.ALLOWED_EXT:
                raise ValueError("Only JPG, JPEG or PNG images are supported.")
            saved_path = config.UPLOAD_DIR / f"{rid}{ext}"
            shutil.copy(src, saved_path)
        else:
            raise ValueError("Please select or drop an image file, or enter a valid local folder and filename.")

        # 3. Perform analysis
        res = analyze(saved_path, config.UPLOAD_DIR, rid)
    except ValueError as e:
        db.log_failure(rid, target_user_id, location, shown_name, str(e), admin_id=admin_id)
        return jsonify(error=str(e)), 400
    except Exception as e:
        db.log_failure(rid, target_user_id, location, shown_name, f"Processing error: {str(e)}", admin_id=admin_id)
        return jsonify(error=f"Vehicle analysis failed: {str(e)}"), 500

    # 4. Save official report associated with selected user
    res.update(
        date=db.now_str(),
        location=location,
        image_name=shown_name,
        target_user=target_user
    )
    db.create_report(res, target_user_id, admin_id=admin_id)

    return jsonify(res)


# ---------------- USER TEMPORARY VEHICLE ANALYSIS ----------------

@bp.post("/api/user/analyze-temporary")
@login_required
def user_analyze_temporary():
    """Runs isolated, short-lived vehicle analysis without writing to the official reports database."""
    # Clean old temporary files first
    db.clean_temp_uploads()

    config.TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    temp_id = f"TEMP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    f = request.files.get("image")
    folder = request.form.get("folder", "").strip()
    name = request.form.get("name", "").strip()
    location, shown_name = "(browser upload)", name or "-"

    try:
        if f and f.filename:
            ext = Path(f.filename).suffix.lower()
            shown_name = secure_filename(f.filename) or f"{temp_id}.jpg"
            if ext not in config.ALLOWED_EXT:
                raise ValueError("Only JPG, JPEG or PNG images are supported.")
            saved_path = config.TEMP_UPLOAD_DIR / f"{temp_id}{ext}"
            f.save(saved_path)
        elif folder and name:
            if not config.ALLOW_LOCAL_PATHS:
                raise ValueError("Local-path analysis is disabled outside trusted development environments. Please upload or capture an image file.")
            location = folder
            folder_path = Path(folder)
            if not folder_path.is_dir():
                raise ValueError("The specified image folder path does not exist on this computer.")
            src = folder_path / name
            if not _is_safe_path(folder_path, src) or not src.is_file():
                raise ValueError("The specified image was not found in the folder.")
            ext = src.suffix.lower()
            if ext not in config.ALLOWED_EXT:
                raise ValueError("Only JPG, JPEG or PNG images are supported.")
            saved_path = config.TEMP_UPLOAD_DIR / f"{temp_id}{ext}"
            shutil.copy(src, saved_path)
        else:
            raise ValueError("Please upload or drop an image, or use the camera.")

        res = analyze(saved_path, config.TEMP_UPLOAD_DIR, temp_id)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error=f"Temporary analysis failed: {str(e)}"), 500

    # Adjust paths so images point to /uploads/temp/...
    res["annotated"] = f"temp/{res['annotated']}"
    for step in res.get("steps", []):
        step["file"] = f"temp/{step['file']}"

    res.update(
        date=db.now_str(),
        location=location,
        image_name=shown_name,
        is_temporary=True,
        notice="This is a temporary evaluation. It is not recorded as an official vehicle inspection report."
    )

    # CRITICAL: Do NOT call db.create_report(). Returns directly to user session only.
    return jsonify(res)


# ---------------- BACKWARD COMPATIBLE / ROUTED ENDPOINTS ----------------

@bp.post("/api/detect-damage")
@login_required
def detect_damage_compat():
    """Compatibility route: delegates to admin analysis if admin, or temporary analysis if user."""
    if session.get("role") == "admin":
        return admin_detect_damage()
    return user_analyze_temporary()


@bp.get("/api/history")
@login_required
def history():
    uid = session["user_id"]
    if session.get("role") == "admin":
        return jsonify(db.get_all_reports(limit=50))
    return jsonify(db.get_user_reports(uid, limit=50))


@bp.get("/api/download-excel")
@admin_required
def download_excel_compat():
    """Admin-only export compatibility route."""
    return send_file(
        db.export_admin_excel(),
        as_attachment=True,
        download_name="vehicle_damage_reports.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ---------------- SECURE IMAGE SERVING ----------------

@bp.get("/uploads/<path:name>")
@login_required
def uploads(name: str):
    """Securely serves images while enforcing ownership and preventing directory traversal."""
    name = name.replace("\\", "/")

    # Check for directory traversal
    if ".." in name or name.startswith("/"):
        return jsonify(error="Invalid file path."), 400

    # Check if this is a temporary file
    if name.startswith("temp/"):
        temp_filename = name.split("/", 1)[1]
        target = config.TEMP_UPLOAD_DIR / temp_filename
        if not _is_safe_path(config.TEMP_UPLOAD_DIR, target):
            return jsonify(error="Invalid file path."), 400
        if not target.is_file():
            return jsonify(error="Image not found or expired."), 404
        return send_from_directory(config.TEMP_UPLOAD_DIR, temp_filename)

    # Official report file
    target = config.UPLOAD_DIR / name
    if not _is_safe_path(config.UPLOAD_DIR, target):
        return jsonify(error="Invalid file path."), 400
    if not target.is_file():
        return jsonify(error="Image file not found."), 404

    # Enforce role-based and ownership-based access control
    if session.get("role") == "admin":
        # Admin can view all official report images
        return send_from_directory(config.UPLOAD_DIR, name)

    # Regular user can only view their own report images
    report_id = _extract_report_id(name)
    if not report_id:
        return jsonify(error="Access denied."), 403

    report = db.get_report(report_id)
    if not report or report.get("user_id") != session.get("user_id"):
        return jsonify(error="Access denied. You do not have permission to view this vehicle image."), 403

    return send_from_directory(config.UPLOAD_DIR, name)
