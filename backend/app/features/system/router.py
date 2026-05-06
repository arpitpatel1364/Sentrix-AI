from fastapi import APIRouter, Depends, HTTPException, Request
import time
import shutil
import sqlite3
import os
import sys
import psutil
import uuid
import json
from datetime import datetime
from ...core.security import require_admin, get_current_user
from ...core.database import get_db, _add_user
from ...core.face_engine import QDRANT_AVAILABLE
from ...core import face_engine
from ...core.config import SNAPSHOTS_DIR, DB_PATH
from ...core.worker_state import get_live_nodes, WORKER_REGISTRY
from ...core.orchestrator import orchestrator
from qdrant_client.models import VectorParams, Distance

router = APIRouter(prefix="/api")

@router.get("/stats")
async def get_stats(user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    
    # Filter by admin_id
    admin_filter = "WHERE admin_id = ?"
    params = (user["admin_id"],)
    if user["admin_id"] == 0:
        admin_filter = ""
        params = ()

    cur.execute(f"SELECT COUNT(*) FROM sightings {admin_filter}", params)
    total_sightings = cur.fetchone()[0]
    
    cur.execute(f"SELECT COUNT(*) FROM sightings {(admin_filter + ' AND') if admin_filter else 'WHERE'} matched = 1", params)
    total_matches = cur.fetchone()[0]
    
    cur.execute(f"SELECT COUNT(*) FROM wanted {admin_filter}", params)
    total_wanted = cur.fetchone()[0]
    
    cur.execute(f"SELECT COUNT(*) FROM object_detections {admin_filter}", params)
    total_objects = cur.fetchone()[0]
    
    live_nodes = get_live_nodes()
    # Filter live nodes by admin_id if not super admin
    if user["admin_id"] != 0:
        live_nodes = [n for n in live_nodes if n.get("admin_id") == user["admin_id"]]
    
    return {
        "total_sightings": total_sightings,
        "total_matches": total_matches,
        "total_wanted": total_wanted,
        "total_objects": total_objects,
        "total_nodes": len(live_nodes)
    }

# ─── MESH CONTROL ───────────────────────────────────────────────────────────

@router.get("/mesh/status")
async def mesh_status(user=Depends(require_admin)):
    return {
        "status": orchestrator.get_status(),
        "mesh_active": any(orchestrator.get_status().values())
    }

@router.post("/mesh/start")
async def start_mesh(user=Depends(require_admin)):
    orchestrator.start_mesh()
    return {"ok": True, "message": "Mesh startup sequence initiated."}

@router.post("/mesh/stop")
async def stop_mesh(user=Depends(require_admin)):
    orchestrator.stop_mesh()
    return {"ok": True, "message": "Mesh shutdown sequence initiated."}

@router.post("/mesh/nodes/{node_id}/start")
async def start_node(node_id: str, user=Depends(get_current_user)):
    # Workers can start, admins can start.
    success = orchestrator.start_node(node_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to start node")
    
    # Audit log
    with sqlite3.connect(DB_PATH) as conn:
        from ...core.database import log_audit
        log_audit(conn, user["username"], user["role"], "START_NODE", target=node_id, detail="Detection node manual start", admin_id=user["admin_id"])
        
    return {"ok": True}

@router.post("/mesh/nodes/{node_id}/stop")
async def stop_node(node_id: str, user=Depends(require_admin)):
    # ONLY admins can stop
    orchestrator.stop_node(node_id)
    
    # Audit log
    with sqlite3.connect(DB_PATH) as conn:
        from ...core.database import log_audit
        log_audit(conn, user["username"], user["role"], "STOP_NODE", target=node_id, detail="Detection node manual stop", admin_id=user["admin_id"])
        
    return {"ok": True}

# ─── CAMERA CONFIGURATION (TOGGLES) ────────────────────────────────────────

@router.get("/cameras/config/{camera_id}")
async def get_camera_config(camera_id: str, user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    # Ownership check
    admin_filter = "AND admin_id = ?" if user["admin_id"] != 0 else ""
    params = (camera_id,) + ((user["admin_id"],) if user["admin_id"] != 0 else ())
    
    row = db.execute(
        f"SELECT face_enabled, obj_enabled, stream_enabled FROM cameras WHERE camera_id = ? {admin_filter}",
        params
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Camera config not found or access denied")
    return dict(row)

@router.post("/cameras/config/{camera_id}")
async def update_camera_config(
    camera_id: str,
    face: int = None,
    obj: int = None,
    stream: int = None,
    user=Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db)
):
    fields = []
    params = []
    if face is not None:
        fields.append("face_enabled = ?")
        params.append(face)
    if obj is not None:
        fields.append("obj_enabled = ?")
        params.append(obj)
    if stream is not None:
        fields.append("stream_enabled = ?")
        params.append(stream)
    
    if not fields:
        return {"ok": True, "message": "No changes requested"}
    
    params.append(camera_id)
    # Ownership check in update
    admin_filter = "AND admin_id = ?" if user["admin_id"] != 0 else ""
    if user["admin_id"] != 0:
        params.append(user["admin_id"])

    db.execute(f"UPDATE cameras SET {', '.join(fields)} WHERE camera_id = ? {admin_filter}", params)
    db.commit()

    # Update Registry for Fast Sync
    from ...core.worker_state import WORKER_REGISTRY
    for key in WORKER_REGISTRY:
        if key.endswith(f":{camera_id}"):
            reg = WORKER_REGISTRY[key]
            # Verify node belongs to this admin before updating live config
            if user["admin_id"] == 0 or reg.get("admin_id") == user["admin_id"]:
                if "config" not in reg: reg["config"] = {}
                if face is not None: reg["config"]["face_enabled"] = bool(face)
                if obj is not None: reg["config"]["obj_enabled"] = bool(obj)
                if stream is not None: reg["config"]["stream_enabled"] = bool(stream)
            
    return {"ok": True}

@router.post("/system/global-toggle")
async def global_toggle(
    feature: str, # 'face', 'obj', 'stream'
    enabled: int, # 0 or 1
    user=Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db)
):
    column = f"{feature}_enabled"
    if feature not in ('face', 'obj', 'stream'):
        raise HTTPException(status_code=400, detail="Invalid feature")
    
    # Filter by admin_id
    if user["admin_id"] != 0:
        db.execute(f"UPDATE cameras SET {column} = ? WHERE admin_id = ?", (enabled, user["admin_id"]))
    else:
        db.execute(f"UPDATE cameras SET {column} = ?", (enabled,))
    db.commit()
    
    # Update Registry for Fast Sync
    from ...core.worker_state import WORKER_REGISTRY
    for key in WORKER_REGISTRY:
        reg = WORKER_REGISTRY[key]
        if user["admin_id"] == 0 or reg.get("admin_id") == user["admin_id"]:
            if "config" not in reg: reg["config"] = {}
            reg["config"][f"{feature}_enabled"] = bool(enabled)
        
    return {"ok": True, "message": f"Global {feature} set to {enabled}"}

import os
import sys
import psutil
from ...core.config import SNAPSHOTS_DIR, DB_PATH

@router.get("/system/health")
async def get_system_health(user=Depends(require_admin)):
    # 1. Hardware Usage
    cpu_pct = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    
    # 2. Storage Metrics
    db_size = os.path.getsize(DB_PATH) if DB_PATH.exists() else 0
    
    snapshot_count = 0
    snapshot_size = 0
    if SNAPSHOTS_DIR.exists():
        for f in SNAPSHOTS_DIR.glob('**/*'):
            if f.is_file():
                snapshot_count += 1
                snapshot_size += f.stat().st_size
                
    disk = psutil.disk_usage(str(DB_PATH.parent))
    
    return {
        "cpu_usage": cpu_pct,
        "memory": {
            "total": mem.total,
            "available": mem.available,
            "percent": mem.percent
        },
        "storage": {
            "db_bytes": db_size,
            "snapshots_bytes": snapshot_size,
            "snapshots_count": snapshot_count,
            "disk_total": disk.total,
            "disk_free": disk.free,
            "disk_used": disk.used
        },
        "platform": sys.platform,
        "uptime": int(time.time() - psutil.boot_time()),
        "crowd_peaks": [],
        "alerts_today": 0
    }


@router.post("/camera-heartbeat")
async def camera_heartbeat(request: Request, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    """Worker reports headcount. Stored in crowd_density table."""
    body = await request.json()
    camera_id = body.get("camera_id")
    headcount = int(body.get("headcount", 0))
    ts = body.get("timestamp") or datetime.utcnow().isoformat()

    if not camera_id:
        raise HTTPException(status_code=400, detail="camera_id required")

    # Upsert into crowd_density
    hb_id = str(uuid.uuid4())
    db.execute("""
        INSERT INTO crowd_density (id, camera_id, headcount, timestamp, admin_id)
        VALUES (?, ?, ?, ?, ?)
    """, (hb_id, camera_id, headcount, ts, user["admin_id"]))
    db.commit()

    # Evaluate crowd_threshold alert rules
    from ..alert_rules.router import evaluate_rules
    await evaluate_rules({
        "type": "crowd_heartbeat",
        "camera_id": camera_id,
        "headcount": headcount,
        "timestamp": ts,
        "admin_id": user["admin_id"]
    }, db)

    return {"ok": True}


@router.get("/system/health")
async def system_health(user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    """Aggregated health dashboard: hardware + node counts + crowd peaks + alerts."""
    # Hardware
    cpu_pct = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    db_size = os.path.getsize(DB_PATH) if DB_PATH.exists() else 0
    snapshot_count, snapshot_size = 0, 0
    if SNAPSHOTS_DIR.exists():
        for f in SNAPSHOTS_DIR.glob('**/*'):
            if f.is_file():
                snapshot_count += 1
                snapshot_size += f.stat().st_size
    disk = psutil.disk_usage(str(DB_PATH.parent))

    # Live nodes
    live_nodes = get_live_nodes()
    if user["admin_id"] != 0:
        live_nodes = [n for n in live_nodes if n.get("admin_id") == user["admin_id"]]

    # Today's alerts
    today = datetime.utcnow().strftime("%Y-%m-%d")
    cur = db.cursor()
    if user["admin_id"] != 0:
        cur.execute("SELECT COUNT(*) FROM notification_log WHERE sent_at LIKE ? AND admin_id = ?",
                    (today + "%", user["admin_id"]))
    else:
        cur.execute("SELECT COUNT(*) FROM notification_log WHERE sent_at LIKE ?", (today + "%",))
    alerts_today = cur.fetchone()[0]

    # Crowd peaks
    if user["admin_id"] != 0:
        cur.execute("""
            SELECT camera_id, MAX(headcount) as peak
            FROM crowd_density
            WHERE timestamp LIKE ? AND admin_id = ?
            GROUP BY camera_id
        """, (today + "%", user["admin_id"]))
    else:
        cur.execute("""
            SELECT camera_id, MAX(headcount) as peak
            FROM crowd_density
            WHERE timestamp LIKE ?
            GROUP BY camera_id
        """, (today + "%",))
    peaks = [dict(r) for r in cur.fetchall()]

    return {
        "cpu_usage": cpu_pct,
        "memory": {"total": mem.total, "available": mem.available, "percent": mem.percent},
        "storage": {
            "db_bytes": db_size,
            "snapshots_bytes": snapshot_size,
            "snapshots_count": snapshot_count,
            "disk_total": disk.total,
            "disk_free": disk.free,
            "disk_used": disk.used
        },
        "platform": sys.platform,
        "uptime": int(time.time() - psutil.boot_time()),
        "nodes": {
            "active": len(live_nodes),
            "total": len([k for k, v in WORKER_REGISTRY.items() if user["admin_id"] == 0 or v.get("admin_id") == user["admin_id"]])
        },
        "alerts_today": alerts_today,
        "crowd_peaks": peaks
    }


@router.post("/system/reset")
async def system_reset(user=Depends(require_admin)):
    # Protection: Only Super Admin can reset the SYSTEM.
    if user["admin_id"] != 0:
         raise HTTPException(status_code=403, detail="Only Super Admin can reset the entire system.")
    from ...core.database import get_db_conn
    from ...core.worker_state import WORKER_REGISTRY
    
    try:
        # 1. Clear Memory Registry first to stop accepting new data briefly
        WORKER_REGISTRY.clear()

        with get_db_conn() as db:
            # 2. Purge DB Tables
            db.execute("DELETE FROM sightings")
            db.execute("DELETE FROM wanted")
            db.execute("DELETE FROM users WHERE username NOT IN ('admin', 'master_admin')")
            db.execute("DELETE FROM person_photos")
            db.execute("DELETE FROM object_detections")
            db.execute("DELETE FROM audit_log")
            db.execute("DELETE FROM notification_log")
            db.execute("DELETE FROM camera_stop_requests")
            db.execute("DELETE FROM alert_rules")
            
            # 3. Add default worker
            _add_user("worker1", "worker123", "worker")
            
            # Force commit now so tables are empty while we do files
            db.commit()

        # 4. Qdrant Reset
        if QDRANT_AVAILABLE and face_engine.QDRANT_CLIENT:
            try:
                face_engine.QDRANT_CLIENT.delete_collection("sightings")
                face_engine.QDRANT_CLIENT.delete_collection("watchlist")
                face_engine.QDRANT_CLIENT.create_collection("sightings", vectors_config=VectorParams(size=512, distance=Distance.COSINE))
                face_engine.QDRANT_CLIENT.create_collection("watchlist", vectors_config=VectorParams(size=512, distance=Distance.COSINE))
            except Exception as e:
                print(f"Qdrant reset error: {e}")

        # 5. File System Cleanup
        if SNAPSHOTS_DIR.exists():
            for item in SNAPSHOTS_DIR.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except Exception as fe:
                    print(f"File cleanup error for {item}: {fe}")
            SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

        return {"ok": True, "message": "System reset successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")
