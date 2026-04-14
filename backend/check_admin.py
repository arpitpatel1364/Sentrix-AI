import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.core.database import get_db_conn
from app.core.models import User
from sqlalchemy import select

async def check_admin():
    async with get_db_conn() as db:
        result = await db.execute(select(User).where(User.username == 'admin'))
        user = result.scalar_one_or_none()
        if user:
            print(f"Admin found! Role: {user.role}")
            print(f"Hash: {user.password_hash}")
        else:
            print("Admin NOT found!")

if __name__ == "__main__":
    asyncio.run(check_admin())
