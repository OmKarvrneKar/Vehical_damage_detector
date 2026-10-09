"""Admin portal dedicated API routes."""
from flask import Blueprint, jsonify, request, send_file, session
from routes.auth import admin_required
from services import db

bp = Blueprint("admin", __name__)


@bp.get("/api/admin/dashboard-stats")
@admin_required
def admin_dashboard_stats():
    return jsonify(db.get_admin_dashboard_stats())


@bp.get("/api/admin/users")
@admin_required
def admin_users_list():
    search = request.args.get("search")
    role = request.args.get("role")
    users = db.get_all_users(search=search, role=role)
    return jsonify(users=users)


@bp.get("/api/admin/users/selectable")
@admin_required
def admin_selectable_users():
    """Returns active regular users for the Admin Analysis 'Select User' dropdown."""
    users = db.get_regular_users()
    return jsonify(users=users)


@bp.get("/api/admin/users/<int:user_id>")
@admin_required
def admin_user_detail(user_id: int):
    user = db.get_user_by_id(user_id)
    if not user:
        return jsonify(error="User not found."), 404

    reports = db.get_user_reports(user_id, limit=50)
    logins = db.get_user_login_history(user_id, limit=20)
    return jsonify(user=user, reports=reports, logins=logins)


@bp.get("/api/admin/reports")
@admin_required
def admin_reports_list():
    search = request.args.get("search")
    severity = request.args.get("severity")
    reports = db.get_all_reports(limit=200, search=search, severity=severity)
    return jsonify(reports=reports)


@bp.get("/api/admin/reports/<report_id>")
@admin_required
def admin_report_detail(report_id: str):
    report = db.get_report(report_id)
    if not report:
        return jsonify(error="Report not found."), 404
    return jsonify(report=report)


@bp.get("/api/admin/login-history")
@admin_required
def admin_login_history():
    role = request.args.get("role")
    event_type = request.args.get("event_type")
    outcome = request.args.get("outcome")
    search = request.args.get("search")
    history = db.get_login_history(limit=100, role=role, event_type=event_type,
                                   outcome=outcome, search=search)
    return jsonify(history=history)


@bp.get("/api/admin/download-excel")
@admin_required
def admin_download_excel():
    excel_buf = db.export_admin_excel()
    return send_file(
        excel_buf,
        as_attachment=True,
        download_name="vehicle_damage_reports.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@bp.post("/api/admin/change-password")
@admin_required
def admin_change_password():
    data = request.get_json(silent=True) or {}
    old_password = str(data.get("old_password") or "")
    new_password = str(data.get("new_password") or "")
    confirm_password = str(data.get("confirm_password") or "")

    if not old_password or not new_password:
        return jsonify(error="Please provide both current and new passwords."), 400

    if len(new_password) < 6:
        return jsonify(error="New password must be at least 6 characters."), 400

    if new_password != confirm_password:
        return jsonify(error="New password confirmation does not match."), 400

    admin = db.verify_user(session["email"], old_password, expected_role="admin")
    if not admin:
        return jsonify(error="Incorrect current password."), 401

    db.update_admin_password(session["user_id"], new_password)
    return jsonify(ok=True, message="Administrator password updated successfully.")
