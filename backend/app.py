"""AI-Based Vehicle Damage Detection System - Application Entry Point."""
import os
import secrets
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
import config
from routes import admin, analytics, auth, detect, user
from routes.auth import admin_required, login_required, user_required
from services import db

# Initialize upload directories and database
config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
config.TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
db.init_db()

app = Flask(
    __name__,
    template_folder=str(config.FRONTEND_DIR / "templates"),
    static_folder=str(config.FRONTEND_DIR / "static")
)

app.secret_key = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = config.SESSION_COOKIE_HTTPONLY
app.config["SESSION_COOKIE_SAMESITE"] = config.SESSION_COOKIE_SAMESITE
app.config["SESSION_COOKIE_SECURE"] = config.SESSION_COOKIE_SECURE


# ---------------- CSRF PROTECTION ----------------

def get_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": get_csrf_token}


@app.after_request
def set_csrf_cookie(response):
    if "_csrf_token" in session:
        response.set_cookie(
            "csrf_token",
            session["_csrf_token"],
            samesite="Lax",
            httponly=False,
            secure=app.config.get("SESSION_COOKIE_SECURE", False)
        )
    return response


@app.before_request
def csrf_protection():
    # Ensure every session has a CSRF token initialized
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)

    # Only enforce for state-changing HTTP methods
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        # Allow bypassing in test client unless explicitly testing CSRF
        if app.config.get("TESTING") and not app.config.get("ENFORCE_CSRF_IN_TESTS"):
            return None

        # Check token from headers, form data, or JSON body
        sent_token = (
            request.headers.get("X-CSRF-Token")
            or request.headers.get("X-CSRFToken")
            or request.form.get("csrf_token")
            or (request.is_json and (request.get_json(silent=True) or {}).get("csrf_token"))
        )
        expected_token = session.get("_csrf_token")

        if not expected_token or not sent_token or not secrets.compare_digest(str(sent_token), str(expected_token)):
            if request.path.startswith("/api/"):
                return jsonify(error="CSRF validation failed. Invalid or missing CSRF token."), 403
            return render_template("user_login.html", error="Session validation expired. Please refresh and try again."), 403



# ---------------- ERROR HANDLERS ----------------

@app.errorhandler(400)
def bad_request(e):
    if request.path.startswith("/api/"):
        return jsonify(error="Bad request."), 400
    return "Bad Request", 400


@app.errorhandler(403)
def forbidden(e):
    if request.path.startswith("/api/"):
        return jsonify(error="Access denied. Forbidden."), 403
    return "Forbidden - Access Denied", 403


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify(error="Resource not found."), 404
    return "Page Not Found", 404


@app.errorhandler(500)
def internal_error(e):
    if request.path.startswith("/api/"):
        return jsonify(error="An internal server error occurred."), 500
    return "Internal Server Error", 500


# Register all route blueprints
for bp_module in (auth, detect, analytics, admin, user):
    app.register_blueprint(bp_module.bp)


# ---------------- PUBLIC LANDING & AUTH PAGES ----------------

@app.route("/")
def home_page():
    if "user_id" in session:
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard_page"))
        return redirect(url_for("user_dashboard_page"))
    return render_template("index.html")


@app.route("/admin/login")
def admin_login_page():
    if "user_id" in session:
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard_page"))
        return redirect(url_for("user_dashboard_page"))
    return render_template("admin_login.html")


@app.route("/user/login")
def user_login_page():
    if "user_id" in session:
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard_page"))
        return redirect(url_for("user_dashboard_page"))
    return render_template("user_login.html")


@app.route("/user/register")
def user_register_page():
    if "user_id" in session:
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard_page"))
        return redirect(url_for("user_dashboard_page"))
    return render_template("user_register.html")


# ---------------- ADMIN PORTAL PAGES ----------------

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard_page():
    return render_template("admin_dashboard.html", user=session.get("full_name") or session.get("username"), role="admin")


@app.route("/admin/analyze")
@admin_required
def admin_analyze_page():
    return render_template("admin_analyze.html", user=session.get("full_name") or session.get("username"), role="admin")


@app.route("/admin/users")
@admin_required
def admin_users_page():
    return render_template("admin_users.html", user=session.get("full_name") or session.get("username"), role="admin")


@app.route("/admin/login-activity")
@admin_required
def admin_login_activity_page():
    return render_template("admin_login_activity.html", user=session.get("full_name") or session.get("username"), role="admin")


@app.route("/admin/reports")
@admin_required
def admin_reports_page():
    return render_template("admin_reports.html", user=session.get("full_name") or session.get("username"), role="admin")


@app.route("/admin/reports/<report_id>")
@admin_required
def admin_report_detail_page(report_id):
    report = db.get_report(report_id)
    if not report:
        abort(404)
    return render_template("admin_report_detail.html", report=report, user=session.get("full_name") or session.get("username"), role="admin")


@app.route("/admin/analytics")
@admin_required
def admin_analytics_page():
    return render_template("admin_analytics.html", user=session.get("full_name") or session.get("username"), role="admin")


@app.route("/admin/download-excel")
@admin_required
def admin_download_excel_page():
    return render_template("admin_download_excel.html", user=session.get("full_name") or session.get("username"), role="admin")


@app.route("/admin/profile")
@admin_required
def admin_profile_page():
    return render_template("admin_profile.html", user=session.get("full_name") or session.get("username"), role="admin")


# ---------------- USER PORTAL PAGES ----------------

@app.route("/user/dashboard")
@user_required
def user_dashboard_page():
    return render_template("user_dashboard.html", user=session.get("full_name") or session.get("username"), role="user")


@app.route("/user/reports")
@user_required
def user_reports_page():
    return render_template("user_reports.html", user=session.get("full_name") or session.get("username"), role="user")


@app.route("/user/reports/<report_id>")
@user_required
def user_report_detail_page(report_id):
    report = db.get_report(report_id)
    if not report:
        abort(404)
    if report.get("user_id") != session.get("user_id"):
        abort(403)
    return render_template("user_report_detail.html", report=report, user=session.get("full_name") or session.get("username"), role="user")


@app.route("/user/analyze")
@user_required
def user_analyze_page():
    return render_template("user_analyze.html", user=session.get("full_name") or session.get("username"), role="user")


@app.route("/user/profile")
@user_required
def user_profile_page():
    return render_template("user_profile.html", user=session.get("full_name") or session.get("username"), role="user")


# ---------------- BACKWARD COMPATIBLE REDIRECTS ----------------

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("home_page"))
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard_page"))
    return redirect(url_for("user_dashboard_page"))


@app.route("/analytics")
def analytics_page():
    if "user_id" not in session:
        return redirect(url_for("home_page"))
    if session.get("role") == "admin":
        return redirect(url_for("admin_analytics_page"))
    return redirect(url_for("user_dashboard_page"))


@app.route("/profile")
def profile_page():
    if "user_id" not in session:
        return redirect(url_for("home_page"))
    if session.get("role") == "admin":
        return redirect(url_for("admin_profile_page"))
    return redirect(url_for("user_profile_page"))


if __name__ == "__main__":
    debug_mode = (not config.IS_PRODUCTION) and os.environ.get("FLASK_DEBUG", "false").lower() in ("true", "1")
    app.run(debug=debug_mode)
