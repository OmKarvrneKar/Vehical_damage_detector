"""Authentication routes and role-based access control decorators."""
import re
from functools import wraps
from flask import Blueprint, jsonify, redirect, request, session, url_for
from services import db

bp = Blueprint("auth", __name__)

EMAIL_REGEX = re.compile(r"^[\w\.\+\-]+@[a-zA-Z0-9\.\-]+\.[a-zA-Z]{2,}$")


def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/") or request.path.startswith("/uploads/"):
                return jsonify(error="Please sign in to continue."), 401
            return redirect(url_for("user_login_page"))
        return f(*args, **kwargs)
    return wrap


def admin_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify(error="Authentication required. Please sign in as administrator."), 401
            return redirect(url_for("admin_login_page"))
        if session.get("role") != "admin":
            if request.path.startswith("/api/"):
                return jsonify(error="Access denied. Administrator privileges required."), 403
            return redirect(url_for("user_dashboard_page"))
        return f(*args, **kwargs)
    return wrap


def user_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify(error="Please sign in to continue."), 401
            return redirect(url_for("user_login_page"))
        if session.get("role") != "user":
            if request.path.startswith("/api/"):
                return jsonify(error="Access denied. Regular user account required."), 403
            return redirect(url_for("admin_dashboard_page"))
        return f(*args, **kwargs)
    return wrap


def _start_session(user: dict):
    session.clear()
    session["user_id"] = user["user_id"]
    session["username"] = user["username"]
    session["email"] = user["email"]
    session["full_name"] = user.get("full_name") or user["username"]
    session["role"] = user["role"]


@bp.post("/api/admin/login")
def admin_login():
    data = request.get_json(silent=True) or {}
    email_or_user = str(data.get("email") or data.get("username") or "").strip()
    password = str(data.get("password") or "")
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "127.0.0.1")
    ua = request.headers.get("User-Agent", "Browser")

    if not email_or_user or not password:
        return jsonify(error="Please provide both email and password."), 400

    user = db.verify_user(email_or_user, password, expected_role="admin")
    if not user:
        # Check if account exists with non-admin role
        existing = db.get_user_by_email(email_or_user) or db.get_user_by_username(email_or_user)
        role = existing["role"] if existing else "unknown"
        user_id = existing["user_id"] if existing else None

        db.log_login_event(user_id=user_id, username_or_email=email_or_user, role="admin",
                           event_type="failed_login", outcome="failed",
                           ip_address=ip, user_agent=ua)
        return jsonify(error="Invalid administrator email or password."), 401

    _start_session(user)
    db.log_login_event(user_id=user["user_id"], username_or_email=user["email"], role="admin",
                       event_type="login", outcome="success",
                       ip_address=ip, user_agent=ua)

    return jsonify(ok=True, role="admin", redirect=url_for("admin_dashboard_page"))


@bp.post("/api/login")
def user_login():
    data = request.get_json(silent=True) or {}
    email_or_user = str(data.get("email") or data.get("username") or "").strip()
    password = str(data.get("password") or "")
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "127.0.0.1")
    ua = request.headers.get("User-Agent", "Browser")

    if not email_or_user or not password:
        return jsonify(error="Please provide both email and password."), 400

    # Look up user
    user = db.verify_user(email_or_user, password)
    if not user:
        existing = db.get_user_by_email(email_or_user) or db.get_user_by_username(email_or_user)
        user_id = existing["user_id"] if existing else None
        db.log_login_event(user_id=user_id, username_or_email=email_or_user, role="user",
                           event_type="failed_login", outcome="failed",
                           ip_address=ip, user_agent=ua)
        return jsonify(error="Invalid email or password."), 401

    if user["role"] == "admin":
        db.log_login_event(user_id=user["user_id"], username_or_email=email_or_user, role="admin",
                           event_type="failed_login", outcome="failed",
                           ip_address=ip, user_agent=ua)
        return jsonify(error="This is an administrator account. Please use the Admin Login portal."), 403

    _start_session(user)
    db.log_login_event(user_id=user["user_id"], username_or_email=user["email"], role="user",
                       event_type="login", outcome="success",
                       ip_address=ip, user_agent=ua)

    return jsonify(ok=True, role="user", redirect=url_for("user_dashboard_page"))


@bp.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    full_name = str(data.get("full_name") or "").strip()
    username = str(data.get("username") or "").strip()
    email = str(data.get("email") or "").strip()
    password = str(data.get("password") or "")
    confirm_password = str(data.get("confirm_password") or "")

    # Validation
    if not full_name:
        return jsonify(error="Full name is required."), 400
    if len(username) < 3:
        return jsonify(error="Username must be at least 3 characters."), 400
    if not re.match(r"^[a-zA-Z0-9_.\-]+$", username):
        return jsonify(error="Username can only contain letters, numbers, underscores, and hyphens."), 400
    if not email or not EMAIL_REGEX.match(email):
        return jsonify(error="Please enter a valid email address."), 400
    if len(password) < 6:
        return jsonify(error="Password must be at least 6 characters."), 400
    if password != confirm_password:
        return jsonify(error="Passwords do not match."), 400

    # User registration strictly assigns regular 'user' role
    user, err = db.create_user(username=username, email=email, password=password,
                               full_name=full_name, role="user")
    if err:
        return jsonify(error=err), 409

    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "127.0.0.1")
    ua = request.headers.get("User-Agent", "Browser")
    db.log_login_event(user_id=user["user_id"], username_or_email=user["email"], role="user",
                       event_type="register", outcome="success",
                       ip_address=ip, user_agent=ua)

    _start_session(user)
    return jsonify(ok=True, redirect=url_for("user_dashboard_page"))


@bp.route("/logout", methods=["GET", "POST"])
@bp.post("/api/logout")
def logout():
    uid = session.get("user_id")
    email = session.get("email") or session.get("username")
    role = session.get("role", "user")
    if uid:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "127.0.0.1")
        ua = request.headers.get("User-Agent", "Browser")
        db.log_login_event(user_id=uid, username_or_email=email or "Unknown", role=role,
                           event_type="logout", outcome="success",
                           ip_address=ip, user_agent=ua)
    session.clear()
    if request.path.startswith("/api/"):
        return jsonify(ok=True, redirect=url_for("home_page"))
    return redirect(url_for("home_page"))


@bp.get("/api/profile")
@login_required
def profile():
    uid = session["user_id"]
    user = db.get_user_by_id(uid)
    if not user:
        return jsonify(error="User not found."), 404
    logins = db.get_user_login_history(uid, limit=20)
    reports = db.get_user_reports(uid)
    return jsonify(user=user, logins=logins, reports=len(reports))
