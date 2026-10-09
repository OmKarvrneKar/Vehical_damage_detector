"""Excel logger interface compatible with original codebase, delegating to SQLite db persistence."""
from typing import Any, Dict, List, Optional
import io
import pandas as pd
from services import db

REPORT_COLS = [
    "Report ID", "User ID", "Timestamp", "Image Location", "Image Name", "Vehicle",
    "Damage Detected", "Damage Type", "Severity Level", "Confidence (%)",
    "Estimated Repair Cost Range", "Cost Min (INR)", "Cost Max (INR)",
    "Parts Needed", "Repair Recommendation", "Status"
]
USER_COLS = ["User ID", "Username", "Full Name", "Email", "Password Hash", "Created"]
LOGIN_COLS = ["User ID", "Username", "Login Time", "IP Address"]


def now() -> str:
    return db.now_str()


def init_db():
    db.init_db()


def verify_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    return db.verify_user(username, password)


def create_user(username: str, password: str, full_name: str = "", email: str = ""):
    return db.create_user(username=username, email=email or f"{username}@local.test",
                          password=password, full_name=full_name)


def log_login(user: Dict[str, Any], ip: Optional[str] = None, user_agent: Optional[str] = None):
    db.log_login_event(
        user_id=user.get("user_id"),
        username_or_email=user.get("email") or user.get("username", "Unknown"),
        role=user.get("role", "user"),
        event_type="login",
        outcome="success",
        ip_address=ip or "127.0.0.1",
        user_agent=user_agent or "Browser"
    )


def profile(user_id: int):
    u = db.get_user_by_id(user_id)
    logins = db.get_user_login_history(user_id, 20)
    # Format logins for legacy profile view
    formatted_logins = [
        {"Login Time": l["timestamp"], "IP Address": l["ip_address"]}
        for l in logins
    ]
    return u, formatted_logins


def next_report_id() -> str:
    return db.next_report_id()


def log_report(r: Dict[str, Any], user_id: int, admin_id: Optional[int] = None):
    return db.create_report(r, user_id, admin_id=admin_id)


def log_failure(rid: str, user_id: int, location: str, name: str, reason: str, admin_id: Optional[int] = None):
    db.log_failure(rid, user_id, location, name, reason, admin_id=admin_id)


def history(user_id: int, limit: int = 50):
    reports = db.get_user_reports(user_id, limit)
    # Map to legacy column names for compatibility
    rows = []
    for r in reports:
        rows.append({
            "Report ID": r["report_id"],
            "User ID": r["user_id"],
            "Timestamp": r["timestamp"],
            "Image Location": r["location"],
            "Image Name": r["image_name"],
            "Vehicle": r["vehicle_type"],
            "Damage Detected": r["damage_detected"],
            "Damage Type": r["damage_types"],
            "Severity Level": r["severity"],
            "Confidence (%)": r["confidence"],
            "Estimated Repair Cost Range": r["cost_range"],
            "Cost Min (INR)": r["cost_min"],
            "Cost Max (INR)": r["cost_max"],
            "Parts Needed": r["parts_needed"],
            "Repair Recommendation": r["repair_recommendation"],
            "Status": r["status"]
        })
    return rows


def reports_df(user_id: Optional[int] = None) -> pd.DataFrame:
    return db.reports_df(user_id)


def export_admin_excel() -> io.BytesIO:
    return db.export_admin_excel()


def export_user_excel(user_id: int) -> io.BytesIO:
    df = db.reports_df(user_id)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Reports")
        for col in w.sheets["Reports"].columns:
            w.sheets["Reports"].column_dimensions[col[0].column_letter].width = 20
    buf.seek(0)
    return buf
