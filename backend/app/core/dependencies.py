from uuid import UUID
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from jose import JWTError, jwt
import bcrypt
from datetime import datetime

from .database import get_db
from .models import User, Client, WorkerKey
from .config import SECRET_KEY, ALGORITHM

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    """
    Decodes JWT and returns the User model object.
    Payload includes 'sub' (username), 'role', 'client_id', 'permissions'.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

async def get_client_id(user: User = Depends(get_current_user)) -> UUID:
    """
    Ensures the user is a client and returns their client_id.
    Admins are forbidden from using client-specific endpoints.
    """
    if user.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins cannot access client-specific endpoints"
        )
    if not user.client_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with any client"
        )
    return user.client_id

async def require_admin(user: User = Depends(get_current_user)):
    """
    Raises 403 if the user is not an admin.
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return user

async def get_worker_client_id(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db)
) -> UUID:
    """
    Validates Worker API Key (from Authorization: Bearer <key> header).
    Hashes the provided key and looks up in worker_keys table.
    Updates last_seen on the key.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Use 'Bearer <api_key>'"
        )
    
    api_key = authorization.replace("Bearer ", "")
    
    # Fetch all keys to verify bcrypt hash. 
    # In a real system, we'd use a key ID or a deterministic hash for lookup.
    result = await db.execute(select(WorkerKey))
    worker_keys = result.scalars().all()
    
    matched_key = None
    for wk in worker_keys:
        try:
            # api_key_hash stores the bcrypt hash
            if bcrypt.checkpw(api_key.encode(), wk.api_key_hash.encode()):
                matched_key = wk
                break
        except Exception:
            continue
            
    if not matched_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired worker API key"
        )
    
    # Update last_seen
    wk_id = matched_key.id
    await db.execute(
        update(WorkerKey)
        .where(WorkerKey.id == wk_id)
        .values(last_seen=datetime.utcnow())
    )
    await db.commit()
    
    return matched_key.client_id

async def get_client_permissions(
    client_id: UUID = Depends(get_client_id),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Returns the permissions JSON for the current client.
    """
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client.permissions or {}
