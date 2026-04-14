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
    """
    Initialize database. 
    Table creation is now handled by Alembic Migrations.
    This function remains for any non-Alembic initialization logic if needed.
    """
    pass



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
