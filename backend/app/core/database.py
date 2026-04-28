import sqlite3
import bcrypt
from datetime import datetime
from contextlib import contextmanager
from .config import DB_PATH


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                admin_id INTEGER DEFAULT 1,
                created_by TEXT DEFAULT 'system'
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS sightings (
                id TEXT PRIMARY KEY,
                camera_id TEXT,
                location TEXT,
                timestamp TEXT,
                uploaded_by TEXT,
                snapshot_path TEXT,
                matched BOOLEAN,
                person_id TEXT,
                person_name TEXT,
                confidence REAL,
                embedding BLOB,
                admin_id INTEGER DEFAULT 1
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS wanted (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                added_by TEXT,
                added_at TEXT,
                admin_id INTEGER DEFAULT 1
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS person_photos (
                id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL,
                embedding BLOB NOT NULL,
                snapshot_path TEXT,
                added_at TEXT,
                admin_id INTEGER DEFAULT 1,
                FOREIGN KEY(person_id) REFERENCES wanted(id) ON DELETE CASCADE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS object_detections (
                id TEXT PRIMARY KEY,
                camera_id TEXT,
                location TEXT,
                timestamp TEXT,
                object_label TEXT,
                confidence REAL,
                snapshot_path TEXT,
                admin_id INTEGER DEFAULT 1
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS camera_configs (
                id TEXT PRIMARY KEY,
                roi TEXT,
                location TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS cameras (
                id           TEXT PRIMARY KEY,
                camera_id    TEXT NOT NULL,
                name         TEXT NOT NULL,
                location     TEXT DEFAULT '',
                description  TEXT DEFAULT '',
                stream_url   TEXT DEFAULT '',
                floor_plan_x REAL DEFAULT 50.0,
                floor_plan_y REAL DEFAULT 50.0,
                roi          TEXT DEFAULT NULL,
                added_by     TEXT,
                added_at     TEXT,
                status       TEXT DEFAULT 'active',
                face_enabled INTEGER DEFAULT 1,
                obj_enabled  INTEGER DEFAULT 1,
                stream_enabled INTEGER DEFAULT 1,
                admin_id     INTEGER DEFAULT 1
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS alert_rules (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                rule_type  TEXT NOT NULL,
                camera_id  TEXT DEFAULT '',
                conditions TEXT DEFAULT '{}',
                actions    TEXT DEFAULT '{}',
                enabled    INTEGER DEFAULT 1,
                created_at TEXT,
                admin_id   INTEGER DEFAULT 1
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_config (
                key   TEXT PRIMARY KEY,
                value TEXT,
                admin_id INTEGER DEFAULT 1
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_log (
                id        TEXT PRIMARY KEY,
                channel   TEXT,
                recipient TEXT,
                subject   TEXT,
                status    TEXT,
                error     TEXT,
                sent_at   TEXT,
                admin_id INTEGER DEFAULT 1
            )
        """)

        # --- NEW: Audit Log ---
        # Records every important user action for admin review.
        # The Audit Log page in the dashboard reads from this table.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id         TEXT PRIMARY KEY,
                timestamp  TEXT NOT NULL,
                username   TEXT NOT NULL,
                role       TEXT NOT NULL,
                action     TEXT NOT NULL,
                target     TEXT DEFAULT '',
                detail     TEXT DEFAULT '',
                ip_address TEXT DEFAULT '',
                admin_id   INTEGER DEFAULT 1
            )
        """)

        # --- NEW: Camera Stop Requests ---
        # When a worker wants to stop/remove their camera, they submit a request here.
        # Admin approves or denies it from the dashboard.
        # The worker polls GET /api/camera-requests/my-status to check the decision.
        # Status values: pending | approved | denied
        cur.execute("""
            CREATE TABLE IF NOT EXISTS camera_stop_requests (
                id           TEXT PRIMARY KEY,
                camera_id    TEXT NOT NULL,
                worker_user  TEXT NOT NULL,
                reason       TEXT DEFAULT '',
                status       TEXT DEFAULT 'pending',
                requested_at TEXT NOT NULL,
                reviewed_by  TEXT DEFAULT NULL,
                reviewed_at  TEXT DEFAULT NULL,
                admin_id     INTEGER DEFAULT 1
            )
        """)

        # Migrations: safely add columns to existing databases
        migrations = [
            ("ALTER TABLE cameras ADD COLUMN roi    TEXT DEFAULT NULL",    "roi on cameras"),
            ("ALTER TABLE cameras ADD COLUMN status TEXT DEFAULT 'active'", "status on cameras"),
            ("ALTER TABLE cameras ADD COLUMN face_enabled INTEGER DEFAULT 1", "face_enabled on cameras"),
            ("ALTER TABLE cameras ADD COLUMN obj_enabled INTEGER DEFAULT 1", "obj_enabled on cameras"),
            ("ALTER TABLE cameras ADD COLUMN stream_enabled INTEGER DEFAULT 1", "stream_enabled on cameras"),
            ("ALTER TABLE users ADD COLUMN created_by TEXT DEFAULT 'system'", "created_by on users"),
            ("ALTER TABLE users ADD COLUMN admin_id INTEGER DEFAULT 1", "admin_id on users"),
            ("ALTER TABLE sightings ADD COLUMN admin_id INTEGER DEFAULT 1", "admin_id on sightings"),
            ("ALTER TABLE wanted ADD COLUMN admin_id INTEGER DEFAULT 1", "admin_id on wanted"),
            ("ALTER TABLE person_photos ADD COLUMN admin_id INTEGER DEFAULT 1", "admin_id on person_photos"),
            ("ALTER TABLE object_detections ADD COLUMN admin_id INTEGER DEFAULT 1", "admin_id on object_detections"),
            ("ALTER TABLE alert_rules ADD COLUMN admin_id INTEGER DEFAULT 1", "admin_id on alert_rules"),
            ("ALTER TABLE notification_log ADD COLUMN admin_id INTEGER DEFAULT 1", "admin_id on notification_log"),
            
            # --- Tiered Multi-Tenancy Migrations ---
            ("ALTER TABLE audit_log ADD COLUMN admin_id INTEGER DEFAULT 1", "admin_id on audit_log"),
            ("ALTER TABLE camera_stop_requests ADD COLUMN admin_id INTEGER DEFAULT 1", "admin_id on camera_stop_requests"),
            ("ALTER TABLE camera_configs ADD COLUMN admin_id INTEGER DEFAULT 1", "admin_id on camera_configs"),
            ("ALTER TABLE notification_config ADD COLUMN admin_id INTEGER DEFAULT 1", "admin_id on notification_config"),

            # Fix master_admin ID if it was set to 1 incorrectly
            ("UPDATE users SET admin_id = 0 WHERE username = 'master_admin' AND role = 'super_admin'", "fix master_admin admin_id"),
        ]
        for sql, label in migrations:
            try:
                cur.execute(sql)
                print(f"[DB] Migrated: added {label}")
            except sqlite3.OperationalError:
                pass  # column already exists, skip

        # Indexes for fast queries
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sightings_person_id   ON sightings(person_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sightings_camera      ON sightings(camera_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sightings_ts          ON sightings(timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_objects_camera        ON object_detections(camera_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_objects_ts            ON object_detections(timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_user            ON audit_log(username)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts              ON audit_log(timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_stop_status           ON camera_stop_requests(status)")

        conn.commit()


def get_db():
    """FastAPI Depends — provides a DB connection per request."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_db_conn():
    """Manual context manager — use this in background tasks or scripts."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _add_user(username: str, password: str, role: str, admin_id: int = 1, created_by: str = 'system'):
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with get_db_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role, admin_id, created_by) VALUES (?, ?, ?, ?, ?)",
            (username, hashed, role, admin_id, created_by),
        )


def seed_default_users():
    """Create default admin and super_admin if none exists."""
    with get_db_conn() as conn:
        cur = conn.cursor()
        
        # Admin
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        if cur.fetchone()[0] == 0:
            _add_user("admin", "admin123", "admin", 1, "system")
            print("[DB] Default admin created: admin / admin123 (Key: 1)")
            
        # Super Admin
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'super_admin'")
        if cur.fetchone()[0] == 0:
            _add_user("master_admin", "master123", "super_admin", 0, "system")
            print("[DB] Default super_admin created: master_admin / master123 (Key: 0)")


def log_audit(db, username: str, role: str, action: str,
              target: str = "", detail: str = "", ip: str = "", admin_id: int = None):
    if admin_id is None:
        # Fallback to system default if absolutely necessary, but log it
        admin_id = 1
    """
    Write one audit log entry into the audit_log table.
    Call this from any router after any important action.

    Usage example:
        from ...core.database import log_audit
        log_audit(db, user["username"], user["role"],
                  "DELETE_CAMERA", target=camera_id)
    """
    import uuid
    db.execute(
        """INSERT INTO audit_log
               (id, timestamp, username, role, action, target, detail, ip_address, admin_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4()),
            datetime.utcnow().isoformat(),
            username,
            role,
            action,
            target,
            detail,
            ip,
            admin_id
        ),
    )
    db.commit()
