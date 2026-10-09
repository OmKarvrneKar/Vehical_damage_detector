"""Analytics routes for Admin (global) and User (user-specific reports)."""
from flask import Blueprint, Response, jsonify, session
from routes.auth import admin_required, login_required, user_required
from services import charts, db

bp = Blueprint("analytics", __name__)


# ---------------- ADMIN GLOBAL ANALYTICS ----------------

@bp.get("/api/admin/analytics/summary")
@admin_required
def admin_analytics_summary():
    df = db.reports_df()
    return jsonify(charts.summary(df))


@bp.get("/api/admin/analytics/chart/<name>.png")
@admin_required
def admin_chart(name: str):
    if name not in ("types", "severity", "trend"):
        return jsonify(error="Chart not found."), 404
    df = db.reports_df()
    return Response(charts.make_chart(name, df), mimetype="image/png")


# ---------------- USER PERSONAL ANALYTICS ----------------

@bp.get("/api/user/analytics/summary")
@login_required
def user_analytics_summary():
    uid = session["user_id"]
    df = db.reports_df(user_id=uid)
    return jsonify(charts.summary(df))


@bp.get("/api/user/analytics/chart/<name>.png")
@login_required
def user_chart(name: str):
    if name not in ("types", "severity", "trend"):
        return jsonify(error="Chart not found."), 404
    uid = session["user_id"]
    df = db.reports_df(user_id=uid)
    return Response(charts.make_chart(name, df), mimetype="image/png")


# ---------------- COMPATIBILITY ANALYTICS ENDPOINTS ----------------

@bp.get("/api/analytics/summary")
@login_required
def summary_compat():
    if session.get("role") == "admin":
        df = db.reports_df()
    else:
        df = db.reports_df(user_id=session["user_id"])
    return jsonify(charts.summary(df))


@bp.get("/api/analytics/chart/<name>.png")
@login_required
def chart_compat(name: str):
    if name not in ("types", "severity", "trend"):
        return jsonify(error="Unknown chart."), 404
    if session.get("role") == "admin":
        df = db.reports_df()
    else:
        df = db.reports_df(user_id=session["user_id"])
    return Response(charts.make_chart(name, df), mimetype="image/png")
