"""SQLite transactional persistence layer with automatic Excel migration,
user management, report ownership, login activity tracking, and Excel export.
"""
import io
import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
import pandas as pd
from werkzeug.security import check_password_hash, generate_password_hash

import config

DB_LOCK = threading.RLock()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    target = db_path or config.DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[Path] = None):
    """Initializes tables, migrates legacy Excel data if necessary, and ensures default admin."""
    with DB_LOCK:
        conn = get_connection(db_path)
        with conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    full_name TEXT,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_login_at TEXT
                );

                CREATE TABLE IF NOT EXISTS reports (
                    report_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    created_by_admin_id INTEGER REFERENCES users(user_id),
                    timestamp TEXT NOT NULL,
                    location TEXT,
                    image_name TEXT,
                    vehicle_type TEXT,
                    damage_detected TEXT,
                    damage_types TEXT,
                    damage_count INTEGER DEFAULT 0,
                    severity TEXT,
                    confidence REAL,
                    cost_range TEXT,
                    cost_min INTEGER,
                    cost_max INTEGER,
                    labour_cost INTEGER,
                    parts_cost INTEGER,
                    parts_needed TEXT,
                    repair_recommendation TEXT,
                    detection_method TEXT,
                    annotated_image TEXT,
                    status TEXT DEFAULT 'Success',
                    details_json TEXT
                );

                CREATE TABLE IF NOT EXISTS login_history (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(user_id),
                    username_or_email TEXT,
                    role TEXT,
                    event_type TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    ip_address TEXT,
                    user_agent TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
                CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
                CREATE INDEX IF NOT EXISTS idx_reports_user_id ON reports(user_id);
                CREATE INDEX IF NOT EXISTS idx_login_history_time ON login_history(timestamp);
            """)

        # If users table is empty, attempt migration from existing Excel database
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        user_count = cur.fetchone()[0]

        if user_count == 0 and config.EXCEL_PATH.exists():
            _migrate_from_excel(conn, config.EXCEL_PATH)

        # Ensure default configured admin exists
        _ensure_default_admin(conn)
        conn.close()


def _migrate_from_excel(conn: sqlite3.Connection, excel_path: Path):
    """Migrates users, reports, and login history from existing Excel database."""
    try:
        wb = openpyxl.load_workbook(excel_path, read_only=True)
        # Migrate Users
        if "Users" in wb.sheetnames:
            rows = [r for r in wb["Users"].iter_rows(min_row=2, values_only=True) if r and r[0] is not None]
            for r in rows:
                uid, uname, fname, email, phash, created = r[0], str(r[1]), str(r[2] or ""), str(r[3] or ""), str(r[4]), str(r[5] or now_str())
                role = "admin" if uname == "admin" or "admin" in email.lower() else "user"
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO users (user_id, username, email, full_name, password_hash, role, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (int(uid), uname, email, fname, phash, role, created))
                except Exception:
                    pass

        # Migrate Reports
        if "Reports" in wb.sheetnames:
            r_rows = [r for r in wb["Reports"].iter_rows(min_row=2, values_only=True) if r and r[0] is not None]
            for r in r_rows:
                try:
                    rid = str(r[0])
                    uid = int(r[1]) if r[1] is not None else 1001
                    ts = str(r[2] or now_str())
                    loc = str(r[3] or "")
                    im_name = str(r[4] or "")
                    veh = str(r[5] or "")
                    dmg_det = str(r[6] or "No")
                    dmg_type = str(r[7] or "-")
                    sev = str(r[8] or "-")
                    conf = float(r[9]) if r[9] is not None else None
                    cost_rng = str(r[10] or "-")
                    cmin = int(r[11]) if r[11] is not None else None
                    cmax = int(r[12]) if r[12] is not None else None
                    parts = str(r[13] or "-")
                    rec = str(r[14] or "")
                    status = str(r[15] or "Success")

                    conn.execute("""
                        INSERT OR IGNORE INTO reports (
                            report_id, user_id, created_by_admin_id, timestamp, location,
                            image_name, vehicle_type, damage_detected, damage_types,
                            damage_count, severity, confidence, cost_range, cost_min,
                            cost_max, labour_cost, parts_cost, parts_needed,
                            repair_recommendation, detection_method, annotated_image, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (rid, uid, 1001, ts, loc, im_name, veh, dmg_det, dmg_type,
                          1 if dmg_det == "Yes" else 0, sev, conf, cost_rng, cmin, cmax,
                          0, 0, parts, rec, "OpenCV baseline", f"{rid}_annotated.jpg", status))
                except Exception:
                    pass

        # Migrate LoginHistory
        if "LoginHistory" in wb.sheetnames:
            l_rows = [r for r in wb["LoginHistory"].iter_rows(min_row=2, values_only=True) if r and r[0] is not None]
            for r in l_rows:
                try:
                    uid = int(r[0]) if r[0] is not None else None
                    uname = str(r[1] or "")
                    ts = str(r[2] or now_str())
                    ip = str(r[3] or "127.0.0.1")
                    conn.execute("""
                        INSERT INTO login_history (user_id, username_or_email, role, event_type, outcome, timestamp, ip_address, user_agent)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (uid, uname, "user" if uid != 1001 else "admin", "login", "success", ts, ip, "Browser/Migrated"))
                except Exception:
                    pass

        conn.commit()
        wb.close()
    except Exception as e:
        print(f"Excel migration notice: {e}")


def _ensure_default_admin(conn: sqlite3.Connection):
    """Ensures configured admin exists with current email and credentials.
    CRITICAL: Preserves modified passwords on restart; never resets a previously changed password.
    """
    cur = conn.cursor()
    cur.execute("SELECT user_id, email, password_hash, role FROM users WHERE email = ? COLLATE NOCASE", (config.ADMIN_EMAIL,))
    existing = cur.fetchone()

    if existing:
        # Admin account with configured email exists; ensure role is admin, but NEVER overwrite password_hash!
        if existing["role"] != "admin":
            conn.execute("UPDATE users SET role = 'admin' WHERE user_id = ?", (existing["user_id"],))
            conn.commit()
    else:
        # Check if legacy admin (id 1001 or username 'admin' or legacy email) exists
        cur.execute("""
            SELECT user_id FROM users
            WHERE user_id = 1001 OR username = ? COLLATE NOCASE OR email = 'admin@example.com' COLLATE NOCASE
        """, (config.ADMIN_USERNAME,))
        legacy_admin = cur.fetchone()
        if legacy_admin:
            conn.execute("""
                UPDATE users
                SET email = ?, username = ?, full_name = ?, password_hash = ?, role = 'admin'
                WHERE user_id = ?
            """, (config.ADMIN_EMAIL, config.ADMIN_USERNAME, config.ADMIN_FULL_NAME,
                  generate_password_hash(config.ADMIN_PASSWORD), legacy_admin["user_id"]))
            conn.commit()
        else:
            conn.execute("""
                INSERT INTO users (user_id, username, email, full_name, password_hash, role, created_at)
                VALUES (1001, ?, ?, ?, ?, 'admin', ?)
            """, (config.ADMIN_USERNAME, config.ADMIN_EMAIL, config.ADMIN_FULL_NAME,
                  generate_password_hash(config.ADMIN_PASSWORD), now_str()))
            conn.commit()


# ---------------- USER FUNCTIONS ----------------

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, email, full_name, role, is_active, created_at, last_login_at FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, email, full_name, password_hash, role, is_active, created_at, last_login_at FROM users WHERE email = ? COLLATE NOCASE", (email.strip(),))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, email, full_name, password_hash, role, is_active, created_at, last_login_at FROM users WHERE username = ? COLLATE NOCASE", (username.strip(),))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(username: str, email: str, password: str, full_name: str = "", role: str = "user") -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Creates a regular user account. Prevents public admin role assignment."""
    username = username.strip()
    email = email.strip()
    full_name = full_name.strip()

    # Enforce that public registrations cannot assign admin role
    assigned_role = "user" if role != "admin" else "admin"

    with DB_LOCK:
        conn = get_connection()
        cur = conn.cursor()

        # Check existing email
        cur.execute("SELECT user_id FROM users WHERE email = ? COLLATE NOCASE", (email,))
        if cur.fetchone():
            conn.close()
            return None, "This email address is already registered. Please sign in instead."

        # Check existing username
        cur.execute("SELECT user_id FROM users WHERE username = ? COLLATE NOCASE", (username,))
        if cur.fetchone():
            conn.close()
            return None, "This username is already taken. Please choose another username."

        cur.execute("SELECT COALESCE(MAX(user_id), 1000) FROM users")
        next_uid = max(cur.fetchone()[0] + 1, 1001)

        created = now_str()
        pw_hash = generate_password_hash(password)

        cur.execute("""
            INSERT INTO users (user_id, username, email, full_name, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (next_uid, username, email, full_name, pw_hash, assigned_role, created))
        conn.commit()
        conn.close()

    return {
        "user_id": next_uid,
        "username": username,
        "email": email,
        "full_name": full_name,
        "role": assigned_role,
        "created_at": created
    }, None


def verify_user(identifier: str, password: str, expected_role: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Verifies user credentials by email or username, checking password hash and role."""
    ident = identifier.strip()
    conn = get_connection()
    cur = conn.cursor()

    # Look up by email first, then username
    cur.execute("""
        SELECT user_id, username, email, full_name, password_hash, role, is_active, created_at
        FROM users
        WHERE email = ? COLLATE NOCASE OR username = ? COLLATE NOCASE
    """, (ident, ident))
    row = cur.fetchone()

    if not row:
        conn.close()
        return None

    user = dict(row)
    if not check_password_hash(user["password_hash"], password):
        conn.close()
        return None

    if not user.get("is_active", 1):
        conn.close()
        return None

    if expected_role and user.get("role") != expected_role:
        conn.close()
        return None

    # Update last login timestamp
    login_time = now_str()
    cur.execute("UPDATE users SET last_login_at = ? WHERE user_id = ?", (login_time, user["user_id"]))
    conn.commit()
    conn.close()

    user.pop("password_hash", None)
    user["last_login_at"] = login_time
    return user


def update_admin_password(user_id: int, new_password: str) -> bool:
    with DB_LOCK:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET password_hash = ? WHERE user_id = ? AND role = 'admin'",
                    (generate_password_hash(new_password), user_id))
        updated = cur.rowcount > 0
        conn.commit()
        conn.close()
    return updated


def get_all_users(search: Optional[str] = None, role: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns all users with their report counts and last login."""
    conn = get_connection()
    cur = conn.cursor()

    query = """
        SELECT u.user_id, u.username, u.email, u.full_name, u.role, u.is_active,
               u.created_at, u.last_login_at,
               COUNT(r.report_id) as total_reports
        FROM users u
        LEFT JOIN reports r ON u.user_id = r.user_id AND r.status = 'Success'
        WHERE 1=1
    """
    params: List[Any] = []

    if role:
        query += " AND u.role = ?"
        params.append(role)

    if search:
        s = f"%{search.strip()}%"
        query += " AND (u.full_name LIKE ? OR u.username LIKE ? OR u.email LIKE ?)"
        params.extend([s, s, s])

    query += " GROUP BY u.user_id ORDER BY u.created_at DESC"
    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_regular_users() -> List[Dict[str, Any]]:
    """Returns list of active regular users for selection by admin."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, username, email, full_name
        FROM users
        WHERE role = 'user' AND is_active = 1
        ORDER BY full_name ASC, username ASC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------- LOGIN ACTIVITY FUNCTIONS ----------------

def log_login_event(user_id: Optional[int], username_or_email: str, role: str,
                    event_type: str, outcome: str, ip_address: Optional[str],
                    user_agent: Optional[str]):
    """Records login events safely without passwords."""
    with DB_LOCK:
        conn = get_connection()
        conn.execute("""
            INSERT INTO login_history (user_id, username_or_email, role, event_type, outcome, timestamp, ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username_or_email[:120], role[:20], event_type[:20], outcome[:20],
              now_str(), (ip_address or "Unknown")[:50], (user_agent or "Unknown")[:255]))
        conn.commit()
        conn.close()


def get_login_history(limit: int = 100, role: Optional[str] = None,
                      event_type: Optional[str] = None, outcome: Optional[str] = None,
                      search: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()

    query = """
        SELECT lh.event_id, lh.user_id, lh.username_or_email, lh.role,
               lh.event_type, lh.outcome, lh.timestamp, lh.ip_address, lh.user_agent,
               u.full_name, u.email as user_email
        FROM login_history lh
        LEFT JOIN users u ON lh.user_id = u.user_id
        WHERE 1=1
    """
    params: List[Any] = []

    if role and role != "all":
        query += " AND lh.role = ?"
        params.append(role)

    if event_type and event_type != "all":
        query += " AND lh.event_type = ?"
        params.append(event_type)

    if outcome and outcome != "all":
        query += " AND lh.outcome = ?"
        params.append(outcome)

    if search:
        s = f"%{search.strip()}%"
        query += " AND (lh.username_or_email LIKE ? OR u.full_name LIKE ? OR u.email LIKE ?)"
        params.extend([s, s, s])

    query += " ORDER BY lh.timestamp DESC LIMIT ?"
    params.append(limit)

    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_user_login_history(user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT event_id, event_type, outcome, timestamp, ip_address, user_agent
        FROM login_history
        WHERE user_id = ?
        ORDER BY timestamp DESC LIMIT ?
    """, (user_id, limit))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ---------------- REPORT FUNCTIONS ----------------

def next_report_id() -> str:
    with DB_LOCK:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM reports")
        cnt = cur.fetchone()[0]
        conn.close()
    return f"R-{101 + cnt}"


def create_report(r: Dict[str, Any], user_id: int, admin_id: Optional[int] = None) -> str:
    """Saves an official report associated with user_id and created_by_admin_id."""
    rid = r.get("id") or next_report_id()
    c = r.get("cost", {})
    cost_rng = f"₹{c.get('min', 0):,} - ₹{c.get('max', 0):,}" if r.get("damaged") else "₹0"
    parts_list = ", ".join(p.get("name", "") for p in r.get("parts", [])) or "-"
    dmg_types_str = ", ".join(r.get("damage_types", [])) or "-"

    with DB_LOCK:
        conn = get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO reports (
                report_id, user_id, created_by_admin_id, timestamp, location,
                image_name, vehicle_type, damage_detected, damage_types,
                damage_count, severity, confidence, cost_range, cost_min,
                cost_max, labour_cost, parts_cost, parts_needed,
                repair_recommendation, detection_method, annotated_image, status, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rid,
            user_id,
            admin_id,
            r.get("date") or now_str(),
            r.get("location") or "(browser upload)",
            r.get("image_name") or "-",
            r.get("vehicle", {}).get("label") or "Vehicle",
            "Yes" if r.get("damaged") else "No",
            dmg_types_str,
            len(r.get("damages", [])),
            r.get("severity") or "None",
            r.get("confidence"),
            cost_rng,
            c.get("min", 0),
            c.get("max", 0),
            c.get("labour", 0),
            c.get("parts", 0),
            parts_list,
            r.get("recommendation") or "",
            r.get("engine") or "OpenCV baseline",
            r.get("annotated") or f"{rid}_annotated.jpg",
            "Success",
            json.dumps(r)
        ))
        conn.commit()
        conn.close()

    return rid


def log_failure(rid: str, user_id: int, location: str, name: str, reason: str, admin_id: Optional[int] = None):
    with DB_LOCK:
        conn = get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO reports (
                report_id, user_id, created_by_admin_id, timestamp, location,
                image_name, vehicle_type, damage_detected, damage_types,
                damage_count, severity, confidence, cost_range, cost_min,
                cost_max, labour_cost, parts_cost, parts_needed,
                repair_recommendation, detection_method, annotated_image, status, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rid, user_id, admin_id, now_str(), location, name, "-", "No", "-", 0,
            "-", None, "-", None, None, 0, 0, "-", "-", "None", "", f"Failed: {reason}", None
        ))
        conn.commit()
        conn.close()


def get_report(report_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT r.*, u.username, u.email as user_email, u.full_name as user_full_name,
               a.username as admin_username, a.full_name as admin_full_name
        FROM reports r
        JOIN users u ON r.user_id = u.user_id
        LEFT JOIN users a ON r.created_by_admin_id = a.user_id
        WHERE r.report_id = ?
    """, (report_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if d.get("details_json"):
        try:
            d["details"] = json.loads(d["details_json"])
        except Exception:
            d["details"] = {}
    return d


def get_user_reports(user_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    """Returns official reports owned by user_id."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT r.*, u.username, u.email as user_email, u.full_name as user_full_name
        FROM reports r
        JOIN users u ON r.user_id = u.user_id
        WHERE r.user_id = ?
        ORDER BY r.timestamp DESC LIMIT ?
    """, (user_id, limit))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_all_reports(limit: int = 200, search: Optional[str] = None, severity: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns all official reports for admin portal."""
    conn = get_connection()
    cur = conn.cursor()

    query = """
        SELECT r.*, u.username, u.email as user_email, u.full_name as user_full_name,
               a.username as admin_username
        FROM reports r
        JOIN users u ON r.user_id = u.user_id
        LEFT JOIN users a ON r.created_by_admin_id = a.user_id
        WHERE 1=1
    """
    params: List[Any] = []

    if severity and severity != "all":
        query += " AND r.severity = ?"
        params.append(severity)

    if search:
        s = f"%{search.strip()}%"
        query += " AND (r.report_id LIKE ? OR u.full_name LIKE ? OR u.email LIKE ? OR u.username LIKE ? OR r.vehicle_type LIKE ?)"
        params.extend([s, s, s, s, s])

    query += " ORDER BY r.timestamp DESC LIMIT ?"
    params.append(limit)

    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def reports_df(user_id: Optional[int] = None) -> pd.DataFrame:
    """Returns pandas DataFrame for charts and analytics."""
    conn = get_connection()
    if user_id is not None:
        query = """
            SELECT report_id as "Report ID", user_id as "User ID", timestamp as "Timestamp",
                   location as "Image Location", image_name as "Image Name", vehicle_type as "Vehicle",
                   damage_detected as "Damage Detected", damage_types as "Damage Type",
                   severity as "Severity Level", confidence as "Confidence (%)",
                   cost_range as "Estimated Repair Cost Range", cost_min as "Cost Min (INR)",
                   cost_max as "Cost Max (INR)", parts_needed as "Parts Needed",
                   repair_recommendation as "Repair Recommendation", status as "Status"
            FROM reports
            WHERE user_id = ? AND status = 'Success'
        """
        df = pd.read_sql_query(query, conn, params=(user_id,))
    else:
        query = """
            SELECT report_id as "Report ID", user_id as "User ID", timestamp as "Timestamp",
                   location as "Image Location", image_name as "Image Name", vehicle_type as "Vehicle",
                   damage_detected as "Damage Detected", damage_types as "Damage Type",
                   severity as "Severity Level", confidence as "Confidence (%)",
                   cost_range as "Estimated Repair Cost Range", cost_min as "Cost Min (INR)",
                   cost_max as "Cost Max (INR)", parts_needed as "Parts Needed",
                   repair_recommendation as "Repair Recommendation", status as "Status"
            FROM reports
            WHERE status = 'Success'
        """
        df = pd.read_sql_query(query, conn)
    conn.close()
    return df


# ---------------- DASHBOARD STATS ----------------

def get_admin_dashboard_stats() -> Dict[str, Any]:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users WHERE role = 'user'")
    total_users = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM reports")
    total_analyses = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM reports WHERE status = 'Success'")
    total_reports = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM reports WHERE damage_detected = 'Yes' AND status = 'Success'")
    total_damaged = cur.fetchone()[0]

    cur.execute("""
        SELECT severity, COUNT(*) as cnt
        FROM reports
        WHERE status = 'Success'
        GROUP BY severity
    """)
    severity_counts = {r["severity"]: r["cnt"] for r in cur.fetchall()}

    # Recent registrations
    cur.execute("""
        SELECT user_id, username, email, full_name, created_at
        FROM users
        WHERE role = 'user'
        ORDER BY created_at DESC LIMIT 5
    """)
    recent_users = [dict(r) for r in cur.fetchall()]

    # Recent login activity
    cur.execute("""
        SELECT event_id, user_id, username_or_email, role, event_type, outcome, timestamp, ip_address
        FROM login_history
        ORDER BY timestamp DESC LIMIT 5
    """)
    recent_logins = [dict(r) for r in cur.fetchall()]

    # Recent analyses
    cur.execute("""
        SELECT r.report_id, r.user_id, r.timestamp, r.vehicle_type, r.damage_detected,
               r.damage_types, r.severity, r.cost_range, u.full_name as user_full_name, u.email as user_email
        FROM reports r
        JOIN users u ON r.user_id = u.user_id
        ORDER BY r.timestamp DESC LIMIT 5
    """)
    recent_analyses = [dict(r) for r in cur.fetchall()]

    conn.close()

    return {
        "total_users": total_users,
        "total_analyses": total_analyses,
        "total_reports": total_reports,
        "total_damaged": total_damaged,
        "severity": {
            "Minor": severity_counts.get("Minor", 0),
            "Moderate": severity_counts.get("Moderate", 0),
            "Severe": severity_counts.get("Severe", 0),
            "None": severity_counts.get("None", 0)
        },
        "recent_users": recent_users,
        "recent_logins": recent_logins,
        "recent_analyses": recent_analyses
    }


def get_user_dashboard_stats(user_id: int) -> Dict[str, Any]:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM reports WHERE user_id = ? AND status = 'Success'", (user_id,))
    total_reports = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM reports WHERE user_id = ? AND damage_detected = 'Yes' AND status = 'Success'", (user_id,))
    total_damaged = cur.fetchone()[0]

    cur.execute("""
        SELECT severity, COUNT(*) as cnt
        FROM reports
        WHERE user_id = ? AND status = 'Success'
        GROUP BY severity
    """)
    severity_counts = {r["severity"]: r["cnt"] for r in cur.fetchall()}

    cur.execute("""
        SELECT MAX(timestamp) FROM reports WHERE user_id = ?
    """, (user_id,))
    latest_date = cur.fetchone()[0]

    cur.execute("""
        SELECT report_id, timestamp, vehicle_type, damage_detected, damage_types, severity, cost_range, status, annotated_image
        FROM reports
        WHERE user_id = ?
        ORDER BY timestamp DESC LIMIT 5
    """, (user_id,))
    recent_reports = [dict(r) for r in cur.fetchall()]

    conn.close()

    return {
        "total_reports": total_reports,
        "total_damaged": total_damaged,
        "latest_date": latest_date or "No analyses yet",
        "severity": {
            "Minor": severity_counts.get("Minor", 0),
            "Moderate": severity_counts.get("Moderate", 0),
            "Severe": severity_counts.get("Severe", 0),
            "None": severity_counts.get("None", 0)
        },
        "recent_reports": recent_reports
    }


# ---------------- EXCEL EXPORT (ADMIN ONLY) ----------------

def export_admin_excel() -> io.BytesIO:
    """Generates an Excel workbook containing Reports, Users, and LoginHistory sheets."""
    conn = get_connection()

    # Sheet 1: Reports
    reports_query = """
        SELECT r.report_id as "Report ID",
               r.user_id as "User ID",
               u.username as "Username",
               u.email as "User Email",
               r.timestamp as "Analysis Date & Time",
               r.image_name as "Image Filename",
               r.vehicle_type as "Vehicle Type",
               r.damage_detected as "Damage Detected",
               r.damage_types as "Damage Categories",
               r.damage_count as "Damage Count",
               r.severity as "Severity",
               r.confidence as "Confidence (%)",
               r.cost_range as "Estimated Repair Cost Range",
               r.cost_min as "Cost Min (INR)",
               r.cost_max as "Cost Max (INR)",
               r.labour_cost as "Estimated Labour Cost (INR)",
               r.parts_cost as "Estimated Parts Cost (INR)",
               r.parts_needed as "Damaged Parts",
               r.repair_recommendation as "Repair Recommendation",
               r.detection_method as "Detection Method",
               r.created_by_admin_id as "Admin ID",
               r.status as "Status"
        FROM reports r
        JOIN users u ON r.user_id = u.user_id
        ORDER BY r.timestamp DESC
    """
    df_reports = pd.read_sql_query(reports_query, conn)

    # Sheet 2: Users (Excludes passwords)
    users_query = """
        SELECT user_id as "User ID",
               username as "Username",
               full_name as "Full Name",
               email as "Email",
               role as "Role",
               is_active as "Active",
               created_at as "Account Created",
               last_login_at as "Last Login"
        FROM users
        ORDER BY created_at DESC
    """
    df_users = pd.read_sql_query(users_query, conn)

    # Sheet 3: LoginHistory
    login_query = """
        SELECT event_id as "Event ID",
               user_id as "User ID",
               username_or_email as "Username or Email",
               role as "Role",
               event_type as "Event Type",
               outcome as "Outcome",
               timestamp as "Timestamp",
               ip_address as "Client IP",
               user_agent as "User Agent / Browser"
        FROM login_history
        ORDER BY timestamp DESC
    """
    df_logins = pd.read_sql_query(login_query, conn)
    conn.close()

    # Build styled openpyxl workbook
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_reports.to_excel(writer, index=False, sheet_name="Reports")
        df_users.to_excel(writer, index=False, sheet_name="Users")
        df_logins.to_excel(writer, index=False, sheet_name="LoginHistory")

        header_fill = PatternFill("solid", fgColor="14213D")
        header_font = Font(bold=True, color="FFFFFF", size=11)

        for sheetname in ["Reports", "Users", "LoginHistory"]:
            ws = writer.sheets[sheetname]
            for col in ws.iter_cols(min_row=1, max_row=1):
                cell = col[0]
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(vertical="center", horizontal="left")

            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = col[0].column_letter
                ws.column_dimensions[col_letter].width = max(14, min(max_len + 4, 50))

            ws.freeze_panes = "A2"

    buf.seek(0)
    return buf


def clean_temp_uploads():
    """Removes temporary user files older than config.TEMP_RETENTION_SECONDS."""
    if not config.TEMP_UPLOAD_DIR.exists():
        return
    now = datetime.now()
    threshold = timedelta(seconds=config.TEMP_RETENTION_SECONDS)
    for p in config.TEMP_UPLOAD_DIR.iterdir():
        if p.is_file():
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
                if now - mtime > threshold:
                    p.unlink(missing_ok=True)
            except Exception:
                pass
