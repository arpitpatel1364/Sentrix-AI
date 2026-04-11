from fastapi import APIRouter, Depends, HTTPException, Request
from ...core.security import _create_token, _verify_password, get_current_user, require_admin
from ...core.database import get_db, _add_user
from ...core.sse_manager import SSE_CONNECTIONS
from ..audit_log.router import write_log
import sqlite3

router = APIRouter(prefix="/api")

@router.post("/login")
async def login(request: Request, db: sqlite3.Connection = Depends(get_db)):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    
    cur = db.cursor()
    cur.execute("SELECT password_hash, role FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
        
    if not user or not _verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = _create_token(username, user["role"])
    write_log(db, username=username, role=user["role"], action="login", ip=request.client.host)
    return {"token": token, "username": username, "role": user["role"]}

@router.post("/logout")
async def logout(request: Request, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    SSE_CONNECTIONS.pop(user["username"], None)
    write_log(db, username=user["username"], role=user["role"], action="logout", ip=request.client.host)
    return {"ok": True}

@router.get("/users")
async def get_users(user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT username, role FROM users")
    return [dict(r) for r in cur.fetchall()]

@router.post("/users")
async def create_user(request: Request, user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    role = body.get("role", "worker")
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")
    
    cur = db.cursor()
    cur.execute("SELECT username FROM users WHERE username = ?", (username,))
    if cur.fetchone():
        raise HTTPException(status_code=409, detail="User already exists")
    
    if role not in ("admin", "worker"):
        raise HTTPException(status_code=400, detail="Role must be admin or worker")
    _add_user(username, password, role)
    write_log(db, username=user["username"], role=user["role"], action="add_user", target=username, detail=f"Created user {username} as {role}", ip=request.client.host)
    return {"ok": True, "username": username, "role": role}

@router.delete("/users/{username}")
async def delete_user(username: str, request: Request, user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    if username == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete main admin")
    db.execute("DELETE FROM users WHERE username = ?", (username,))
    db.commit()
    write_log(db, username=user["username"], role=user["role"], action="delete_user", target=username, detail=f"Deleted user {username}", ip=request.client.host)
    return {"ok": True}
