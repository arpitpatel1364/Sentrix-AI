import sqlite3
import bcrypt
from datetime import datetime
from .config import DB_PATH

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
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
                embedding BLOB
            )
        """)
        # Wanted List (People)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS wanted (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                added_by TEXT,
                added_at TEXT
            )
        """)
        
        # New: Multiple Photos per person
        cur.execute("""
            CREATE TABLE IF NOT EXISTS person_photos (
                id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL,
                embedding BLOB NOT NULL,
                snapshot_path TEXT,
                added_at TEXT,
                FOREIGN KEY(person_id) REFERENCES wanted(id) ON DELETE CASCADE
            )
        """)
        
        # New: Object Detection Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS object_detections (
                id TEXT PRIMARY KEY,
                camera_id TEXT,
                location TEXT,
                timestamp TEXT,
                object_label TEXT,
                confidence REAL,
                snapshot_path TEXT
            )
        """)
        
        # Camera Configurations (ROI)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS camera_configs (
                id TEXT PRIMARY KEY, -- user:camera_id
                roi TEXT,             -- JSON string [x1, y1, x2, y2]
                location TEXT
            )
        """)

        # Camera Registry — full camera management
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cameras (
                id          TEXT PRIMARY KEY,
                camera_id   TEXT UNIQUE NOT NULL,
                name        TEXT NOT NULL,
                location    TEXT DEFAULT '',
                description TEXT DEFAULT '',
                stream_url  TEXT DEFAULT '',
                floor_plan_x REAL DEFAULT 50.0,
                floor_plan_y REAL DEFAULT 50.0,
                added_by    TEXT,
                added_at    TEXT
            )
        """)

        # Alert Rules Engine
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alert_rules (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                rule_type  TEXT NOT NULL,
                camera_id  TEXT DEFAULT '',
                conditions TEXT DEFAULT '{}',
                actions    TEXT DEFAULT '{}',
                enabled    INTEGER DEFAULT 1,
                created_at TEXT
            )
        """)

        # Notification Config (key-value store)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_config (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Notification Dispatch Log
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_log (
                id        TEXT PRIMARY KEY,
                channel   TEXT,
                recipient TEXT,
                subject   TEXT,
                status    TEXT,
                error     TEXT,
                sent_at   TEXT
            )
        """)

        # Indexes for performance
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sightings_person_id ON sightings(person_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sightings_camera ON sightings(camera_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sightings_ts ON sightings(timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_objects_camera ON object_detections(camera_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_objects_ts ON object_detections(timestamp)")
        
        conn.commit()

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

from contextlib import contextmanager
@contextmanager
def get_db_conn():
    """Manual context manager for database operations outside of FastAPI Depends."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def _add_user(username: str, password: str, role: str):
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR REPLACE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                     (username, hashed, role))
        conn.commit()

def seed_default_users():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT username FROM users WHERE username = 'admin'")
        if not cur.fetchone():
            _add_user("admin", "admin123", "admin")
            print("✓ Seeded default admin: admin/admin123")
        
        cur.execute("SELECT username FROM users WHERE username = 'worker1'")
        if not cur.fetchone():
            _add_user("worker1", "worker123", "worker")
            print("✓ Seeded default worker: worker1/worker123")
