"""User portal dedicated API routes with strict report ownership enforcement."""
from flask import Blueprint, jsonify, session
from routes.auth import login_required, user_required
from services import db

bp = Blueprint("user", __name__)


@bp.get("/api/user/dashboard-stats")
@login_required
def user_dashboard_stats():
    uid = session["user_id"]
    stats = db.get_user_dashboard_stats(uid)
    return jsonify(stats)


@bp.get("/api/user/reports")
@login_required
def user_reports_list():
    uid = session["user_id"]
    reports = db.get_user_reports(uid)
    return jsonify(reports=reports)


@bp.get("/api/user/reports/<report_id>")
@login_required
def user_report_detail(report_id: str):
    report = db.get_report(report_id)
    if not report:
        return jsonify(error="Report not found."), 404

    # Enforce strict ownership: a regular user can never view another user's report!
    if session.get("role") != "admin" and report.get("user_id") != session.get("user_id"):
        return jsonify(error="Access denied. You do not have permission to view this report."), 403

    return jsonify(report=report)


@bp.get("/api/user/profile")
@login_required
def user_profile():
    uid = session["user_id"]
    user = db.get_user_by_id(uid)
    if not user:
        return jsonify(error="User not found."), 404

    logins = db.get_user_login_history(uid, limit=20)
    reports = db.get_user_reports(uid)
    return jsonify(user=user, logins=logins, total_reports=len(reports))
