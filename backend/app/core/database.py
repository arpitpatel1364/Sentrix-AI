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
        
        # Optimization: Index for person-based history lookup
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sightings_person_id ON sightings(person_id)")
        
        conn.commit()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
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
