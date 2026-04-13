from fastapi import APIRouter, Depends, HTTPException
import time
import shutil
from ...core.security import require_admin, get_current_user
from ...core.database import get_db, _add_user
from ...core.face_engine import (
    QDRANT_AVAILABLE
)
from ...core import face_engine
from ...core.config import SNAPSHOTS_DIR, DB_PATH
from ...core.worker_state import get_live_nodes, WORKER_REGISTRY
from ...core.orchestrator import orchestrator
from qdrant_client.models import VectorParams, Distance
import sqlite3
import json

router = APIRouter(prefix="/api")

@router.get("/stats")
async def get_stats(user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM sightings")
    total_sightings = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM sightings WHERE matched = 1")
    total_matches = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM wanted")
    total_wanted = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM object_detections")
    total_objects = cur.fetchone()[0]
    
    live_nodes = get_live_nodes()
    
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
        log_audit(conn, user["username"], user["role"], "START_NODE", target=node_id, detail="Detection node manual start")
        
    return {"ok": True}

@router.post("/mesh/nodes/{node_id}/stop")
async def stop_node(node_id: str, user=Depends(require_admin)):
    # ONLY admins can stop
    orchestrator.stop_node(node_id)
    
    # Audit log
    with sqlite3.connect(DB_PATH) as conn:
        from ...core.database import log_audit
        log_audit(conn, user["username"], user["role"], "STOP_NODE", target=node_id, detail="Detection node manual stop")
        
    return {"ok": True}

# ─── CAMERA CONFIGURATION (TOGGLES) ────────────────────────────────────────

@router.get("/cameras/config/{camera_id}")
async def get_camera_config(camera_id: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        "SELECT face_enabled, obj_enabled, stream_enabled FROM cameras WHERE camera_id = ?",
        (camera_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Camera config not found")
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
    db.execute(f"UPDATE cameras SET {', '.join(fields)} WHERE camera_id = ?", params)
    db.commit()

    # Update Registry for Fast Sync
    from ...core.worker_state import WORKER_REGISTRY
    # We don't have the username easily here without another query, 
    # but we can scan the registry for this camera_id
    for key in WORKER_REGISTRY:
        if key.endswith(f":{camera_id}"):
            reg = WORKER_REGISTRY[key]
            if "config" not in reg: reg["config"] = {}
            if face is not None: reg["config"]["face_enabled"] = bool(face)
            if obj is not None: reg["config"]["obj_enabled"] = bool(obj)
            if stream is not None: reg["config"]["stream_enabled"] = bool(stream)
            # Re-fetch node config for ROI etc might be overkill, but let's at least update these
            
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
    
    db.execute(f"UPDATE cameras SET {column} = ?", (enabled,))
    db.commit()
    
    # Update Registry for Fast Sync
    from ...core.worker_state import WORKER_REGISTRY
    for key in WORKER_REGISTRY:
        reg = WORKER_REGISTRY[key]
        if "config" not in reg: reg["config"] = {}
        reg["config"][f"{feature}_enabled"] = bool(enabled)
        
    return {"ok": True, "message": f"Global {feature} set to {enabled}"}

@router.post("/system/reset")
async def system_reset(user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    try:
        db.execute("DELETE FROM sightings")
        db.execute("DELETE FROM wanted")
        db.execute("DELETE FROM users WHERE username != 'admin'")
        db.execute("DELETE FROM person_photos")
        db.execute("DELETE FROM object_detections")
        db.execute("DELETE FROM audit_log")
        db.execute("DELETE FROM notification_log")
        db.execute("DELETE FROM camera_stop_requests")
        db.execute("DELETE FROM alert_rules")
        db.commit()
        
        _add_user("worker1", "worker123", "worker")

        if QDRANT_AVAILABLE and face_engine.QDRANT_CLIENT:
            try:
                face_engine.QDRANT_CLIENT.delete_collection("sightings")
                face_engine.QDRANT_CLIENT.delete_collection("watchlist")
                face_engine.QDRANT_CLIENT.create_collection("sightings", vectors_config=VectorParams(size=512, distance=Distance.COSINE))
                face_engine.QDRANT_CLIENT.create_collection("watchlist", vectors_config=VectorParams(size=512, distance=Distance.COSINE))
            except Exception as e:
                print(f"Qdrant reset error: {e}")

        if SNAPSHOTS_DIR.exists():
            for item in SNAPSHOTS_DIR.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

        return {"ok": True, "message": "System reset successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")
