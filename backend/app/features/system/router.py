from fastapi import APIRouter, Depends, HTTPException
import time
import shutil
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from ...core.dependencies import get_current_user, require_admin
from ...core.database import get_db, _add_user
from ...core.face_engine import (
    QDRANT_AVAILABLE
)
from ...core import face_engine
from ...core.config import SNAPSHOTS_DIR
from ...core.worker_state import get_live_nodes, WORKER_REGISTRY
from ...core.orchestrator import orchestrator
from qdrant_client.models import VectorParams, Distance
import json

router = APIRouter(prefix="/system", tags=["System"])

@router.get("/health")
async def get_health(user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    import psutil
    import os
    
    # Simple metrics
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    
    # DB Size (approx for Postgres)
    db_size = "N/A"
    try:
        res = await db.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))"))
        db_size = res.scalar()
    except: pass

    live_nodes = get_live_nodes()
    
    return {
        "hub": {"cpu": cpu, "ram": ram},
        "db": {"size": db_size},
        "qdrant": {"vectors_count": "Pending"},
        "redis": {"sessions": 1},
        "workers": {"online": len(live_nodes), "total": len(live_nodes)} # Simplified
    }

@router.get("/stream/{node_key}")
async def proxy_stream(node_key: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """
    Proxies or redirects to the worker's media server for the live MJPEG stream.
    Expected node_key format: 'username:camera_id' or 'camera_id'
    """
    from fastapi.responses import RedirectResponse
    from ...core.models import Camera, Worker
    
    # Use split instead of rsplit to stay consistent with worker_state.py
    parts = node_key.split(":")
    cam_id = parts[-1]
    
    # Find Camera and Worker
    query = select(Camera).where(Camera.camera_id == cam_id)
    res = await db.execute(query)
    cam = res.scalar_one_or_none()
    
    if not cam or not cam.worker_id:
        raise HTTPException(status_code=404, detail="Camera or Worker node not found")
        
    worker_res = await db.execute(select(Worker).where(Worker.id == cam.worker_id))
    worker = worker_res.scalar_one_or_none()
    
    if not worker or not worker.media_base_url:
        raise HTTPException(status_code=503, detail="Worker media server offline or not configured")
        
    # Redirect to worker's media server. index 0 for now as we don't store index separately.
    # In a real environment, we'd proxy this to avoid exposing worker IPs directly.
    return RedirectResponse(url=f"{worker.media_base_url}/stream/0")


@router.get("/stats")
async def get_stats(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """
    Returns high-level statistics.
    Admins see global totals. Clients see only their own totals.
    """
    is_admin = user.role == "admin"
    client_id = user.client_id
    
    where_clause = ""
    params = {}
    
    if not is_admin:
        if not client_id:
            raise HTTPException(status_code=403, detail="Client user has no associated client ID")
        where_clause = "WHERE client_id = :cid"
        params = {"cid": client_id}

    # Count Sightings
    total_sightings = (await db.execute(
        text(f"SELECT COUNT(*) FROM sightings {where_clause}"), params
    )).scalar()
    
    # Count Matches
    match_where = "WHERE matched = TRUE"
    if not is_admin:
        match_where += " AND client_id = :cid"
    total_matches = (await db.execute(
        text(f"SELECT COUNT(*) FROM sightings {match_where}"), params
    )).scalar()
    
    # Count Watchlist
    total_watchlist = (await db.execute(
        text(f"SELECT COUNT(*) FROM watchlist {where_clause}"), params
    )).scalar()
    
    # Count Objects (Need to join with cameras if client_id missing in table)
    if is_admin:
        total_objects = (await db.execute(text("SELECT COUNT(*) FROM object_detections"))).scalar()
    else:
        # Join with cameras to filter by client_id
        total_objects = (await db.execute(
            text("""
                SELECT COUNT(*) FROM object_detections od
                JOIN cameras c ON od.camera_id = c.camera_id
                WHERE c.client_id = :cid
            """), params
        )).scalar()
    
    live_nodes = get_live_nodes(client_id=None if is_admin else str(client_id))
    
    return {
        "total_sightings": total_sightings,
        "total_matches": total_matches,
        "total_watchlist": total_watchlist,
        "total_wanted": total_watchlist,   # alias used by JS dashboard
        "total_objects": total_objects,
        "total_nodes": len(live_nodes)
    }

# ─── MESH CONTROL ───────────────────────────────────────────────────────────

@router.get("/mesh/status")
async def mesh_status(user=Depends(get_current_user)):
    """
    Returns the status of the orchestration mesh.
    Clients only see status for their own nodes.
    """
    is_admin = user.role == "admin"
    client_id = str(user.client_id) if not is_admin else None
    
    full_status = orchestrator.get_status()
    
    if is_admin:
        display_status = full_status
    else:
        # Filter status to only include nodes belonging to this client
        # Node keys in orchestrator status are usually 'username:camera_id'
        display_status = {}
        for key, val in full_status.items():
            if key.startswith(f"{user.username}:"):
                display_status[key] = val
                
    return {
        "status": display_status,
        "mesh_active": any(display_status.values())
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
async def start_node(node_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Workers can start, admins can start.
    success = orchestrator.start_node(node_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to start node")

    from ..audit_log.router import write_log
    await write_log(db, username=user.username, role=user.role, action="start_node", target=node_id, detail="Detection node manual start")
    return {"ok": True}

@router.post("/mesh/nodes/{node_id}/stop")
async def stop_node(node_id: str, user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    # ONLY admins can stop
    orchestrator.stop_node(node_id)

    from ..audit_log.router import write_log
    await write_log(db, username=user.username, role=user.role, action="stop_node", target=node_id, detail="Detection node manual stop")
    return {"ok": True}

# ─── CAMERA CONFIGURATION (TOGGLES) ────────────────────────────────────────

@router.get("/cameras/config/{camera_id}")
async def get_camera_config(camera_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        text("SELECT face_enabled, obj_enabled, stream_enabled FROM cameras WHERE camera_id = :camera_id"),
        {"camera_id": camera_id}
    )
    row = res.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Camera config not found")
    return dict(row._mapping)

@router.post("/cameras/config/{camera_id}")
async def update_camera_config(
    camera_id: str,
    face: int = None,
    obj: int = None,
    stream: int = None,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    fields = []
    params = {"camera_id": camera_id}
    if face is not None:
        fields.append("face_enabled = :face")
        params["face"] = face
    if obj is not None:
        fields.append("obj_enabled = :obj")
        params["obj"] = obj
    if stream is not None:
        fields.append("stream_enabled = :stream")
        params["stream"] = stream
    
    if not fields:
        return {"ok": True, "message": "No changes requested"}
    
    query = f"UPDATE cameras SET {', '.join(fields)} WHERE camera_id = :camera_id"
    await db.execute(text(query), params)
    await db.commit()

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

@router.post("/global-toggle")
async def global_toggle(
    feature: str, # 'face', 'obj', 'stream'
    enabled: int, # 0 or 1
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    column = f"{feature}_enabled"
    if feature not in ('face', 'obj', 'stream'):
        raise HTTPException(status_code=400, detail="Invalid feature")
    
    await db.execute(text(f"UPDATE cameras SET {column} = :enabled"), {"enabled": enabled})
    await db.commit()
    
    # Update Registry for Fast Sync
    from ...core.worker_state import WORKER_REGISTRY
    for key in WORKER_REGISTRY:
        reg = WORKER_REGISTRY[key]
        if "config" not in reg: reg["config"] = {}
        reg["config"][f"{feature}_enabled"] = bool(enabled)
        
    return {"ok": True, "message": f"Global {feature} set to {enabled}"}

@router.post("/reset")
async def system_reset(user=Depends(require_admin)):
    from ...core.database import get_db_conn
    from ...core.worker_state import WORKER_REGISTRY
    
    try:
        # 1. Clear Memory Registry first to stop accepting new data briefly
        WORKER_REGISTRY.clear()

        async with get_db_conn() as db:
            # 2. Purge DB Tables
            await db.execute(text("DELETE FROM sightings"))
            await db.execute(text("DELETE FROM watchlist"))
            await db.execute(text("DELETE FROM users WHERE username != 'admin'"))
            await db.execute(text("DELETE FROM person_photos"))
            await db.execute(text("DELETE FROM object_detections"))
            await db.execute(text("DELETE FROM audit_log"))
            await db.execute(text("DELETE FROM notification_log"))
            await db.execute(text("DELETE FROM camera_stop_requests"))
            await db.execute(text("DELETE FROM alert_rules"))
            
            # 3. Add default worker
            await _add_user("worker1", "worker123", "worker")
            
            # Force commit now so tables are empty while we do files
            await db.commit()

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

@router.get("/active-users")
async def active_users(user=Depends(get_current_user)):
    """
    Returns live nodes and sessions. Clients only see their own nodes.
    """
    client_id = str(user.client_id) if user.role == "client" else None
    live_nodes = get_live_nodes(client_id=client_id)
    # sessions list needed by JS pages (loadWorkers, loadSystem)
    return {"nodes": live_nodes, "sessions": live_nodes}
