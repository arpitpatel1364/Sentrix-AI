import uuid
import secrets
import bcrypt
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from ...core.security import _create_token, _verify_password
from ...core.database import get_db
from ...core.dependencies import get_current_user, require_admin, get_worker_client_id
from ...core.models import User, Client, WorkerKey
from ...core.face_engine import QDRANT_CLIENT, QDRANT_AVAILABLE
from ..audit_log.router import write_log
from ...core.sse_manager import SSE_CONNECTIONS

router = APIRouter(prefix="/auth")

@router.post("/login")
async def login(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
        
    if not user or not _verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    permissions = {}
    if user.role == "client" and user.client_id:
        c_res = await db.execute(select(Client).where(Client.id == user.client_id))
        client = c_res.scalar_one_or_none()
        if client:
            permissions = client.permissions
            
    token = _create_token(
        user.username, 
        user.role, 
        str(user.client_id) if user.client_id else None,
        permissions
    )
    
    await write_log(db, username=user.username, role=user.role, action="login", ip=request.client.host)
    return {"token": token, "username": user.username, "role": user.role}

@router.post("/logout")
async def logout(request: Request, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    SSE_CONNECTIONS.pop(user.username, None)
    await write_log(db, username=user.username, role=user.role, action="logout", ip=request.client.host)
    return {"ok": True}

@router.get("/users")
async def get_users(_admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User))
    users = result.scalars().all()
    return [{"username": u.username, "role": u.role} for u in users]

@router.post("/users")
async def create_user(request: Request, _admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    role = body.get("role", "worker")
    
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")
    
    result = await db.execute(select(User).where(User.username == username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User already exists")
    
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    new_user = User(username=username, password_hash=hashed, role=role)
    db.add(new_user)
    await db.commit()
    
    await write_log(db, username=_admin.username, role=_admin.role, action="add_user", target=username, detail=f"Created user {username} as {role}", ip=request.client.host)
    return {"ok": True, "username": username, "role": role}

@router.delete("/users/{username}")
async def delete_user(username: str, request: Request, _admin=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    if username == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete main admin")
    
    await db.execute(delete(User).where(User.username == username))
    await db.commit()
    
    await write_log(db, username=_admin.username, role=_admin.role, action="delete_user", target=username, detail=f"Deleted user {username}", ip=request.client.host)
    return {"ok": True}

@router.post("/issue-credentials")
async def issue_credentials(
    request: Request,
    body: dict,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    client_name = body.get("client_name")
    if not client_name:
        raise HTTPException(status_code=400, detail="client_name required")
        
    # 1. Create Client with default permissions (all False)
    client_id = uuid.uuid4()
    qdrant_collection = f"client_{str(client_id)}_faces"
    new_client = Client(
        id=client_id,
        name=client_name,
        permissions={
            "can_view_sightings": False,
            "can_manage_cameras": False,
            "can_manage_watchlist": False,
            "can_view_analytics": False
        },
        qdrant_collection=qdrant_collection
    )
    db.add(new_client)
    
    # 2. Create User row with role="client", linked to client
    email = f"{client_name.lower().replace(' ', '_')}@sentrix.ai"
    password = secrets.token_urlsafe(12)
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    
    new_user = User(
        username=email,
        password_hash=password_hash,
        role="client",
        client_id=client_id
    )
    db.add(new_user)
    
    # 3. Generate random 48-char CLIENT_API_KEY and store bcrypt hash
    api_key = secrets.token_urlsafe(36) # approx 48 chars
    api_key_hash = bcrypt.hashpw(api_key.encode(), bcrypt.gensalt()).decode()
    
    new_worker_key = WorkerKey(
        client_id=client_id,
        api_key_hash=api_key_hash,
        label="Default Worker"
    )
    db.add(new_worker_key)
    
    # 4. Create Qdrant collection
    if QDRANT_AVAILABLE and QDRANT_CLIENT:
        from qdrant_client.models import Distance, VectorParams
        try:
            QDRANT_CLIENT.create_collection(
                collection_name=qdrant_collection,
                vectors_config=VectorParams(size=512, distance=Distance.COSINE)
            )
        except Exception:
            # Silence error if collection exists or other issue
            pass
            
    await db.commit()
    await write_log(db, username=_admin.username, role=_admin.role, action="issue_credentials", target=client_name, detail=f"Created client {client_name}", ip=request.client.host)
    
    return {
        "client_id": str(client_id),
        "email": email,
        "password": password,
        "client_api_key": api_key,
        "qdrant_collection": qdrant_collection
    }

@router.post("/validate-worker-key")
async def validate_worker_key(
    client_id: uuid.UUID = Depends(get_worker_client_id),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
        
    return {
        "client_id": str(client_id),
        "qdrant_collection": client.qdrant_collection
    }

@router.get("/media-token")
async def get_media_token(
    current_user = Depends(get_current_user)
):
    """
    Generate a short-lived signed token for the client to access worker media.
    """
    from ...core.config import MEDIA_SECRET_KEY, ALGORITHM
    from jose import jwt
    from datetime import datetime, timedelta
    
    expires = datetime.utcnow() + timedelta(minutes=15)
    payload = {
        "sub": current_user.username,
        "client_id": str(current_user.client_id) if current_user.client_id else None,
        "role": current_user.role,
        "exp": expires
    }
    token = jwt.encode(payload, MEDIA_SECRET_KEY, algorithm=ALGORITHM)
    
    return {
        "media_token": token,
        "expires_in": 900
    }

