from fastapi import APIRouter, Depends, HTTPException, Request
from ...core.security import _create_token, _verify_password, get_current_user, require_admin
from ...core.database import get_db, _add_user
from ...core.sse_manager import SSE_CONNECTIONS
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
    return {"token": token, "username": username, "role": user["role"]}

@router.post("/logout")
async def logout(user=Depends(get_current_user)):
    SSE_CONNECTIONS.pop(user["username"], None)
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
    return {"ok": True, "username": username, "role": role}

@router.delete("/users/{username}")
async def delete_user(username: str, user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    if username == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete main admin")
    db.execute("DELETE FROM users WHERE username = ?", (username,))
    db.commit()
    return {"ok": True}
