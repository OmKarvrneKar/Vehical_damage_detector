import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
UPLOAD_DIR = ROOT / "uploads"
TEMP_UPLOAD_DIR = UPLOAD_DIR / "temp"
FRONTEND_DIR = ROOT / "frontend"
EXCEL_PATH = DATA_DIR / "vehicle_damage_reports.xlsx"
DB_PATH = DATA_DIR / "vehicle_damage.db"
MODEL_PATH = Path(__file__).parent / "models" / "damage_model.pt"

# Environment detection
IS_PRODUCTION = (
    os.environ.get("FLASK_ENV") == "production"
    or os.environ.get("ENV") == "production"
    or os.environ.get("PRODUCTION", "").lower() in ("true", "1", "yes")
)

# Secret Key validation
DEFAULT_DEV_SECRET = "vehicle-damage-detection-secret-key-2026"
_env_secret = os.environ.get("SECRET_KEY")

if IS_PRODUCTION:
    if not _env_secret or _env_secret == DEFAULT_DEV_SECRET or len(_env_secret) < 16:
        raise RuntimeError(
            "CRITICAL SECURITY CONFIGURATION ERROR: A secure, unique SECRET_KEY environment "
            "variable must be configured when running in production mode."
        )
    SECRET_KEY = _env_secret
else:
    SECRET_KEY = _env_secret or DEFAULT_DEV_SECRET

# Session & Cookie Security
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = (
    os.environ.get("SESSION_COOKIE_SECURE", "false").lower() in ("true", "1", "yes")
    or IS_PRODUCTION
)

# Development / Initial Admin Credentials
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@Samrat.com").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Samrat@2026")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin").strip()
ADMIN_FULL_NAME = os.environ.get("ADMIN_FULL_NAME", "System Administrator").strip()

MAX_UPLOAD_MB = 10
ALLOWED_EXT = {".jpg", ".jpeg", ".png"}

# SECURITY REQUIREMENT: ALLOW_LOCAL_PATHS must be False by default.
# Only enabled if explicitly set to true in trusted development environments.
ALLOW_LOCAL_PATHS = os.environ.get("ALLOW_LOCAL_PATHS", "false").lower() in ("true", "1", "yes")

# Retention duration for temporary user uploads (in seconds)
TEMP_RETENTION_SECONDS = 3600
