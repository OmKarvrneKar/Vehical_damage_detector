# AI-Based Vehicle Damage Detection System (Enterprise Upgrade)

Full-Stack AI/Computer Vision Platform featuring separate **Admin and User Portals**, Role-Based Access Control (RBAC), User-Specific Report Assignment, Detailed Login Activity Auditing, Isolated Temporary Analyses, and Admin-Exclusive Excel Exports.

---

## 1. Quick Start & Execution

### Prerequisites
- Python 3.10+ (tested on Python 3.12 / 3.14)
- Pip

### Installation
From the project root:
```bash
pip install -r requirements.txt
```

### Running the Application
```bash
python backend/app.py
```
Open your browser and navigate to:
**`http://127.0.0.1:5000`**

---

## 2. Default Credentials & Portal Access

### Option A: Admin Portal
- **URL**: `http://127.0.0.1:5000/admin/login`
- **Initial Email**: `admin@Samrat.com`
- **Initial Password**: `Samrat@2026`

> **Note on Changing Admin Password:**
> - You can update the password in the UI at **Admin Profile** (`/admin/profile`) -> **Update Admin Password**.
> - Or configure environment variables prior to start:
>   ```bash
>   set ADMIN_EMAIL=admin@Samrat.com
>   set ADMIN_PASSWORD=YourNewPassword2026
>   ```

### Option B: User Portal
- **Sign In URL**: `http://127.0.0.1:5000/user/login`
- **Registration URL**: `http://127.0.0.1:5000/user/register`
- Users register with Full Name, Username, Email, Password, and Confirm Password.
- Email address is the primary sign-in identifier.
- Registrations are strictly constrained to the regular `user` role (no public admin registration).

---

## 3. Architecture & Features

### Core Upgrades Implemented
1. **Separation of Portals**:
   - `/admin/*`: Administrator workspace with sidebar navigation, summary KPI metrics, vehicle scanning with mandatory user assignment, user management, login auditing, global analytics, and Excel exports.
   - `/user/*`: Vehicle owner portal scoped strictly to records owned by the authenticated user.
2. **Mandatory User Selection**:
   - Inspectors must select a registered customer before running an official analysis.
   - Analysis saves an official report linked to `user_id = selected_user.id` and `created_by_admin_id = admin.id`.
3. **Isolated Temporary User Analysis**:
   - Vehicle owners can run temporary diagnostic scans on their own photos.
   - Temporary results are returned only to the active browser session.
   - User scans are **never** inserted into the official `Reports` database or included in admin metrics/exports.
4. **Backend Security & Data Ownership**:
   - Server-side RBAC on all routes and APIs.
   - Regular users cannot access other users' reports or report images (enforced in `detect.py` and `user.py`).
   - Passwords hashed with Werkzeug `scrypt`.
   - File uploads sanitized and validated (size, format, OpenCV decodability).
5. **Dual Persistence & Admin-Only Excel Export**:
   - Multi-user ACID persistence backed by SQLite (`data/vehicle_damage.db`) with automatic migration from existing workbooks.
   - Export available exclusively to administrators at `/admin/download-excel` (`GET /api/admin/download-excel`), producing a multi-sheet Excel workbook (`Reports`, `Users`, `LoginHistory`) with frozen headers.

---

## 4. Environment Variables

| Variable | Default Value | Description |
|---|---|---|
| `SECRET_KEY` | `vehicle-damage-detection-secret-key-2026` | Flask session encryption key. |
| `ADMIN_EMAIL` | `admin@Samrat.com` | Default admin email. |
| `ADMIN_PASSWORD` | `Samrat@2026` | Default admin password. |
| `ADMIN_USERNAME` | `admin` | Default admin username. |
| `ADMIN_FULL_NAME` | `System Administrator` | Default admin display name. |
| `ALLOW_LOCAL_PATHS` | `false` | Disabled by default for security. Set to `true` only in trusted local development environments. |
| `YOLO_CONF` | `0.10` | Minimum confidence for YOLO detections. Lower it (e.g. `0.05`) if a weak model hides damage; raise it to reduce false positives. |

---

## 5. Enabling and Training the YOLO Model

By default, if `backend/models/damage_model.pt` is not present, the system automatically uses the **OpenCV edge-density heuristic baseline** with a clear UI status warning.

To train and activate the custom YOLO model:
1. Place your dataset in `data/dataset/` with YOLO directory structure (`images/train`, `images/val`, `labels/train`, `labels/val`) and inspect `data/dataset/damage.yaml`.
2. Install Ultralytics:
   ```bash
   pip install ultralytics
   ```
3. Run training:
   ```bash
   python backend/training/train_model.py --epochs 50
   ```
4. This trains fine-tuned weights, prints Precision/Recall/F1/mAP, and copies weights to `backend/models/damage_model.pt`.
5. Restart the server (`python backend/app.py`). The pipeline automatically switches from OpenCV fallback to the active YOLO model.

---

## 6. Running Tests

The test suite covers 38 acceptance scenarios across authentication, admin workflows, customer isolation, and regression verification:

```bash
pytest tests/test_app.py -v
```
