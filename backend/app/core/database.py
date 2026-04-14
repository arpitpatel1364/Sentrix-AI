import os
import bcrypt
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
import redis.asyncio as redis

from .config import DATABASE_URL, REDIS_URL

# --- Database Setup ---
# Using asyncpg for PostgreSQL async support
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# --- Redis Setup ---
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

async def init_db():
    """Initialize database tables using raw SQL (transitioning to SQLAlchemy)."""
    # 0. Clients table (MUST BE FIRST because of Foreign Keys)
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS clients (
                id UUID PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                permissions JSONB NOT NULL DEFAULT '{}',
                qdrant_collection TEXT
            )
        """))

    # 1. User table
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                client_id UUID REFERENCES clients(id) ON DELETE SET NULL
            )
        """))
    
    # Manual fixes in separate transactions to avoid aborting the whole process
    async with engine.connect() as conn:
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS client_id UUID REFERENCES clients(id) ON DELETE SET NULL"))
            await conn.commit()
        except Exception: await conn.rollback()

    # 2. Worker Keys table
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS worker_keys (
                id UUID PRIMARY KEY,
                client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                api_key_hash TEXT NOT NULL,
                label TEXT NOT NULL,
                last_seen TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

    # 3. Workers table
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS workers (
                id UUID PRIMARY KEY,
                client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                worker_key_id UUID NOT NULL REFERENCES worker_keys(id),
                label TEXT NOT NULL,
                ip_address TEXT,
                media_base_url TEXT,
                last_seen TIMESTAMP,
                status TEXT DEFAULT 'offline',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

    # 4. Sightings table
    async with engine.begin() as conn:
        await conn.execute(text("""
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
                embedding BYTEA,
                client_id UUID REFERENCES clients(id) ON DELETE CASCADE,
                worker_id UUID REFERENCES workers(id) ON DELETE SET NULL
            )
        """))
    
    async with engine.connect() as conn:
        try:
            await conn.execute(text("ALTER TABLE sightings ADD COLUMN IF NOT EXISTS client_id UUID REFERENCES clients(id) ON DELETE CASCADE"))
            await conn.execute(text("ALTER TABLE sightings ADD COLUMN IF NOT EXISTS worker_id UUID REFERENCES workers(id) ON DELETE SET NULL"))
            await conn.commit()
        except Exception: await conn.rollback()

    # 5. Watchlist table (formerly wanted)
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                added_by TEXT,
                added_at TEXT,
                client_id UUID REFERENCES clients(id) ON DELETE CASCADE,
                qdrant_vector_id TEXT
            )
        """))
    
    async with engine.connect() as conn:
        try:
            await conn.execute(text("ALTER TABLE IF EXISTS wanted RENAME TO watchlist"))
            await conn.commit()
        except Exception: await conn.rollback()
        
        try:
            await conn.execute(text("ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS client_id UUID REFERENCES clients(id) ON DELETE CASCADE"))
            await conn.execute(text("ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS qdrant_vector_id TEXT"))
            await conn.commit()
        except Exception: await conn.rollback()

    # 6. Person photos table
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS person_photos (
                id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL REFERENCES watchlist(id) ON DELETE CASCADE,
                embedding BYTEA NOT NULL,
                snapshot_path TEXT,
                added_at TEXT
            )
        """))

    # 7. Object detections table
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS object_detections (
                id TEXT PRIMARY KEY,
                camera_id TEXT,
                location TEXT,
                timestamp TEXT,
                object_label TEXT,
                confidence REAL,
                snapshot_path TEXT
            )
        """))

    # 8. ROI table (formerly camera_configs)
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS roi (
                id TEXT PRIMARY KEY,
                roi TEXT,
                location TEXT,
                client_id UUID REFERENCES clients(id) ON DELETE CASCADE
            )
        """))
    
    async with engine.connect() as conn:
        try:
            await conn.execute(text("ALTER TABLE IF EXISTS camera_configs RENAME TO roi"))
            await conn.commit()
        except Exception: await conn.rollback()
        
        try:
            await conn.execute(text("ALTER TABLE roi ADD COLUMN IF NOT EXISTS client_id UUID REFERENCES clients(id) ON DELETE CASCADE"))
            await conn.commit()
        except Exception: await conn.rollback()

    # 9. Cameras table
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS cameras (
                id           TEXT PRIMARY KEY,
                camera_id    TEXT UNIQUE NOT NULL,
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
                client_id UUID REFERENCES clients(id) ON DELETE CASCADE,
                worker_id UUID REFERENCES workers(id) ON DELETE SET NULL
            )
        """))
    
    async with engine.connect() as conn:
        try:
            await conn.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS client_id UUID REFERENCES clients(id) ON DELETE CASCADE"))
            await conn.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS worker_id UUID REFERENCES workers(id) ON DELETE SET NULL"))
            await conn.commit()
        except Exception: await conn.rollback()

    # 10. Alert rules table (Update created_at type if needed)
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS alert_rules (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                rule_type  TEXT NOT NULL,
                camera_id  TEXT DEFAULT '',
                conditions TEXT DEFAULT '{}',
                actions    TEXT DEFAULT '{}',
                enabled    INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

    # 11. Notification config table
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notification_config (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """))

    # 12. Notification log table
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notification_log (
                id        TEXT PRIMARY KEY,
                channel   TEXT,
                recipient TEXT,
                subject   TEXT,
                status    TEXT,
                error     TEXT,
                sent_at   TEXT
            )
        """))

    # 13. Audit log table
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id         TEXT PRIMARY KEY,
                timestamp  TEXT NOT NULL,
                username   TEXT NOT NULL,
                role       TEXT NOT NULL,
                action     TEXT NOT NULL,
                target     TEXT DEFAULT '',
                detail     TEXT DEFAULT '',
                ip_address TEXT DEFAULT ''
            )
        """))

    # 14. Camera stop requests table
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS camera_stop_requests (
                id           TEXT PRIMARY KEY,
                camera_id    TEXT NOT NULL,
                worker_user  TEXT NOT NULL,
                reason       TEXT DEFAULT '',
                status       TEXT DEFAULT 'pending',
                requested_at TEXT NOT NULL,
                reviewed_by  TEXT DEFAULT NULL,
                reviewed_at  TEXT DEFAULT NULL
            )
        """))

    # Indexes for fast queries
    async with engine.begin() as conn:
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sightings_person_id   ON sightings(person_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sightings_camera      ON sightings(camera_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sightings_ts          ON sightings(timestamp)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_objects_camera        ON object_detections(camera_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_objects_ts            ON object_detections(timestamp)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_user            ON audit_log(username)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_ts              ON audit_log(timestamp)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_stop_status           ON camera_stop_requests(status)"))


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends — provides a DB session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_db_conn():
    """Manual context manager — use this in background tasks or scripts."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except:
            await session.rollback()
            raise
        finally:
            await session.close()


async def _add_user(username: str, password: str, role: str):
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    async with get_db_conn() as db:
        # Check if user exists
        res = await db.execute(
            text("SELECT 1 FROM users WHERE username = :username"),
            {"username": username}
        )
        if not res.fetchone():
            await db.execute(
                text("INSERT INTO users (username, password_hash, role) VALUES (:username, :password_hash, :role)"),
                {"username": username, "password_hash": hashed, "role": role},
            )


async def seed_default_users():
    """Create default admin if none exists."""
    async with get_db_conn() as db:
        res = await db.execute(text("SELECT COUNT(*) FROM users WHERE role = 'admin'"))
        count = res.scalar()
        if count == 0:
            await _add_user("admin", "admin123", "admin")
            print("[DB] Default admin created: admin / admin123")


async def log_audit(db: AsyncSession, username: str, role: str, action: str,
              target: str = "", detail: str = "", ip: str = ""):
    """
    Write one audit log entry into the audit_log table.
    """
    import uuid
    await db.execute(
        text("""INSERT INTO audit_log
               (id, timestamp, username, role, action, target, detail, ip_address)
           VALUES (:id, :timestamp, :username, :role, :action, :target, :detail, :ip)"""),
        {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "username": username,
            "role": role,
            "action": action,
            "target": target,
            "detail": detail,
            "ip": ip,
        },
    )
    await db.commit()
