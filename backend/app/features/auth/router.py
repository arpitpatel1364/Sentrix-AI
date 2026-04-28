from fastapi import APIRouter, Depends, HTTPException, Request
from ...core.security import _create_token, _verify_password, get_current_user, require_admin, require_super_admin
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
    cur.execute("SELECT password_hash, role, admin_id FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
        
    if not user or not _verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = _create_token(username, user["role"], user["admin_id"])
    write_log(db, username=username, role=user["role"], action="login", ip=request.client.host, admin_id=user["admin_id"])
    return {"token": token, "username": username, "role": user["role"], "admin_id": user["admin_id"]}

@router.post("/impersonate/exit")
async def exit_impersonate(request: Request, user=Depends(require_super_admin), db: sqlite3.Connection = Depends(get_db)):
    print(f"[AUTH] Super Admin {user['username']} (ID: {user['admin_id']}) is reporting an impersonation exit.")
    write_log(db, username=user["username"], role=user["role"], action="exit_impersonate", target="system", detail="Super Admin exited preview mode", ip=request.client.host, admin_id=user["admin_id"])
    return {"ok": True}

@router.post("/impersonate/{username}")
async def impersonate(username: str, request: Request, user=Depends(require_super_admin), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT role, admin_id FROM users WHERE username = ?", (username,))
    target = cur.fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    
    token = _create_token(username, target["role"], target["admin_id"])
    write_log(db, username=user["username"], role=user["role"], action="impersonate", target=username, detail=f"Super Admin impersonated user {username}", ip=request.client.host, admin_id=user["admin_id"])
    return {"token": token, "username": username, "role": target["role"], "admin_id": target["admin_id"]}
@router.post("/logout")
async def logout(request: Request, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    SSE_CONNECTIONS.pop(user["username"], None)
    write_log(db, username=user["username"], role=user["role"], action="logout", ip=request.client.host, admin_id=user["admin_id"])
    return {"ok": True}

@router.get("/users")
async def get_users(user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    if user["admin_id"] == 0:
        cur.execute("SELECT username, role, admin_id FROM users")
    else:
        cur.execute("SELECT username, role, admin_id FROM users WHERE admin_id = ?", (user["admin_id"],))
    return [dict(r) for r in cur.fetchall()]

@router.post("/users")
async def create_user(request: Request, user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    role = body.get("role", "worker")
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")
    
    # Role Hierarchy Check
    if role in ("admin", "super_admin") and user["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="Only Super Admin can create admin accounts")
    
    cur = db.cursor()
    cur.execute("SELECT username FROM users WHERE username = ?", (username,))
    if cur.fetchone():
        raise HTTPException(status_code=409, detail="User already exists")
    
    if role not in ("admin", "worker", "super_admin"):
        raise HTTPException(status_code=400, detail="Invalid role")
        
    # Determine Admin ID for new user
    new_admin_id = user["admin_id"] # Default: inherit from creator
    if role == "admin" and user["role"] == "super_admin":
        #provision new unique admin_id
        cur.execute("SELECT MAX(admin_id) FROM users")
        max_id = cur.fetchone()[0] or 0
        new_admin_id = max(1, max_id + 1)
        
    _add_user(username, password, role, admin_id=new_admin_id, created_by=user["username"])
    write_log(db, username=user["username"], role=user["role"], action="add_user", target=username, detail=f"Created user {username} as {role} (Admin Key: {new_admin_id})", ip=request.client.host, admin_id=user["admin_id"])
    return {"ok": True, "username": username, "role": role, "admin_id": new_admin_id}

@router.get("/super/master-data")
async def get_master_data(user=Depends(require_super_admin), db: sqlite3.Connection = Depends(get_db)):
    # 1. Get all users with creator info
    cur = db.cursor()
    cur.execute("SELECT username, role, admin_id, created_by FROM users")
    all_users = [dict(r) for r in cur.fetchall()]
    
    # 2. Statistics
    total_admins = len([u for u in all_users if u["role"] in ("admin", "super_admin")])
    total_workers = len([u for u in all_users if u["role"] == "worker"])
    
    # 3. Hierarchy Mapping (Admins -> Workers they created)
    hierarchy = {}
    for u in all_users:
        if u["role"] in ("admin", "super_admin"):
            hierarchy[u["username"]] = {
                "role": u["role"],
                "workers_count": 0,
                "workers": []
            }
            
    for u in all_users:
        creator = u["created_by"]
        if creator in hierarchy and u["role"] == "worker":
            hierarchy[creator]["workers_count"] += 1
            hierarchy[creator]["workers"].append(u["username"])
            
    # 4. Global Audit Stats (Total actions)
    cur.execute("SELECT COUNT(*) FROM audit_log")
    total_actions = cur.fetchone()[0]
    
    # 5. Live Node Status
    from ...core.worker_state import get_live_nodes
    live_nodes = get_live_nodes()
    
    return {
        "users": all_users,
        "stats": {
            "total_users": len(all_users),
            "total_admins": total_admins,
            "total_workers": total_workers,
            "total_actions": total_actions,
            "total_live_nodes": len(live_nodes),
            "active_sessions": len(SSE_CONNECTIONS)
        },
        "hierarchy": hierarchy,
        "live_nodes": live_nodes
    }

@router.get("/super/analysis")
async def get_super_analysis(user=Depends(require_super_admin), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    
    # 1. Audit Log Distribution
    cur.execute("""
        SELECT action, COUNT(*) as count 
        FROM audit_log 
        GROUP BY action 
        ORDER BY count DESC
    """)
    audit_dist = [dict(r) for r in cur.fetchall()]
    
    # 2. Storage Analysis (Aggregate sightings and objects by admin)
    cur.execute("""
        SELECT admin_id, COUNT(*) as count
        FROM (
            SELECT admin_id FROM sightings
            UNION ALL
            SELECT admin_id FROM object_detections
        )
        GROUP BY admin_id
        ORDER BY count DESC
    """)
    storage_rows = cur.fetchall()
    
    storage_stats = []
    for row in storage_rows:
        count = row["count"]
        # Mocking size: Assume avg 0.25MB per snapshot entry
        storage_stats.append({
            "admin_id": row["admin_id"],
            "count": count,
            "size_mb": round(count * 0.25, 2)
        })
        
    return {
        "audit_distribution": audit_dist,
        "storage_stats": storage_stats
    }

@router.delete("/users/{username}")
async def delete_user(username: str, request: Request, user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    if username == "admin" or username == "master_admin":
        raise HTTPException(status_code=400, detail="Cannot delete core admin accounts")
    
    cur = db.cursor()
    cur.execute("SELECT role FROM users WHERE username = ?", (username,))
    target = cur.fetchone()
    
    if target and target["role"] in ("admin", "super_admin") and user["role"] != "super_admin":
         raise HTTPException(status_code=403, detail="Admins cannot delete other admins")

    db.execute("DELETE FROM users WHERE username = ?", (username,))
    db.commit()
    write_log(db, username=user["username"], role=user["role"], action="delete_user", target=username, detail=f"Deleted user {username}", ip=request.client.host, admin_id=user["admin_id"])
    return {"ok": True}
