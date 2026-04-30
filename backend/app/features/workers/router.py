from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from ...core.worker_state import WORKER_REGISTRY
from typing import List
import uuid
import cv2
import numpy as np
import time
from datetime import datetime
from ...core.security import get_current_user, require_admin
from ...core.database import get_db
from ..audit_log.router import write_log
from ...core.face_engine import (
    get_embedding, bytes_to_cv2, match_wanted, QDRANT_AVAILABLE
)
from ...core import face_engine
from ...core.config import SNAPSHOTS_DIR
from ...core.worker_state import update_worker_heartbeat, get_live_nodes
from ...core.sse_manager import SSE_CONNECTIONS, broadcast_alert
from ...core.stream_state import (
    update_live_frame, get_live_frame, LIVE_FRAMES,
    update_live_packets, subscribe_packets
)
from qdrant_client.models import PointStruct
import sqlite3

router = APIRouter(prefix="/api")

def _save_sighting_task(sighting_id: str, img: np.ndarray, sighting: dict, embedding: np.ndarray, camera_id: str, location: str, ts: str, admin_id: int):
    try:
        if QDRANT_AVAILABLE and face_engine.QDRANT_CLIENT:
            face_engine.QDRANT_CLIENT.upsert(
                collection_name="sightings",
                points=[PointStruct(
                    id=sighting_id,
                    vector=embedding.tolist(),
                    payload={
                        "camera_id": camera_id,
                        "location": location,
                        "timestamp": ts,
                        "person_id": sighting["person_id"],
                        "person_name": sighting["person_name"],
                        "admin_id": admin_id
                    }
                )]
            )
    except Exception as e:
        print(f"Error in background task: {e}")

@router.post("/upload-frame")
async def upload_frame(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    camera_id: str = Form("cam-1"),
    location: str = Form("unknown"),
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db)
):
    # Verify camera ownership
    cur = db.cursor()
    user_admin_id = user["admin_id"]

    print(f"[DEBUG] upload_frame: cam={camera_id}, admin=ID:{user_admin_id}, user={user['username']}")
    
    # Ownership Check: Super Admin (0) can upload to any camera; others must own it
    if user_admin_id == 0:
        cur.execute("SELECT id, location FROM cameras WHERE camera_id = ?", (camera_id,))
    else:
        cur.execute("SELECT id, location FROM cameras WHERE camera_id = ? AND admin_id = ?", (camera_id, user_admin_id))
    
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=403, detail=f"Camera {camera_id} is not registered for your account.")

    node_key = f"{user['username']}:{camera_id}"
    is_new = update_worker_heartbeat(node_key, user["admin_id"])
    
    if is_new:
        await broadcast_alert({
            "type": "camera_online",
            "camera_id": camera_id,
            "location": row["location"] if row and "location" in row.keys() else location,
            "admin_id": user["admin_id"]
        })
    
    data = await file.read()
    img = bytes_to_cv2(data)
    if img is None:
        print(f"[DEBUG] upload_frame ERROR: cv2.imdecode failed for {camera_id}")
        raise HTTPException(status_code=400, detail="Invalid image")

    embedding = get_embedding(img)
    if embedding is None:
        print(f"[DEBUG] upload_frame: status=no_face for {camera_id} (img shape: {img.shape})")
        return {
            "status": "no_face",
            "config": WORKER_REGISTRY.get(node_key, {}).get("config")
        }

    result = match_wanted(embedding, user["admin_id"])
    sighting_id = str(uuid.uuid4())
    ts = datetime.utcnow().isoformat()
    
    # Systematic Filename Generation
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = (result["person"]["name"] if result else "unknown").replace(" ", "_").lower()
    short_uuid = sighting_id[:8]
    snap_filename = f"sight_{now_str}_{safe_name}_{camera_id}_{short_uuid}.jpg"
    
    # Tenant-isolated path: SNAPSHOTS_DIR/{admin_id}/{camera_id}/
    admin_id = user["admin_id"]
    cam_dir = SNAPSHOTS_DIR / str(admin_id) / camera_id
    cam_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{admin_id}/{camera_id}/{snap_filename}"   # DB path: <admin_id>/cam-1/sight_...jpg
    snapshot_path = cam_dir / snap_filename                 # File path: SNAPSHOTS_DIR/<admin_id>/cam-1/sight_...jpg
    cv2.imwrite(str(snapshot_path), img, [cv2.IMWRITE_JPEG_QUALITY, 70])

    sighting = {
        "id": sighting_id,
        "camera_id": camera_id,
        "location": location,
        "timestamp": ts,
        "uploaded_by": user["username"],
        "snapshot_path": filename,
        "matched": False,
        "person_name": "Unknown",
        "person_id": None,
        "confidence": 0.0,
        "admin_id": user["admin_id"]
    }

    if result:
        sighting["matched"] = True
        sighting["person_name"] = result["person"]["name"]
        sighting["person_id"] = result["person"]["id"]
        sighting["confidence"] = result["confidence"]
        
    emb_blob = embedding.astype(np.float32).tobytes()
    db.execute("""
        INSERT INTO sightings (id, camera_id, location, timestamp, uploaded_by, snapshot_path, matched, person_id, person_name, confidence, embedding, admin_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sighting["id"], sighting["camera_id"], sighting["location"], sighting["timestamp"],
        sighting["uploaded_by"], sighting["snapshot_path"], sighting["matched"],
        sighting["person_id"], sighting["person_name"], sighting["confidence"],
        emb_blob, sighting["admin_id"]
    ))
    db.commit()

    background_tasks.add_task(_save_sighting_task, sighting_id, img, sighting, embedding, camera_id, location, ts, user["admin_id"])

    if result:
        await broadcast_alert({
            "type": "wanted_match",
            "id": sighting_id,
            "person_id": result["person"]["id"],
            "person_name": result["person"]["name"],
            "confidence": result["confidence"],
            "camera_id": camera_id,
            "location": location,
            "timestamp": ts,
            "snapshot": f"/api/snapshots/{filename}",
            "admin_id": user["admin_id"]
        })
        # ── Alert Rules Engine ───────────────────────────────────────────
        from ...features.alert_rules.router import evaluate_rules
        await evaluate_rules({
            "type": "face", "camera_id": camera_id, "matched": True,
            "confidence": result["confidence"],
            "person_name": result["person"]["name"],
            "timestamp": ts,
            "admin_id": user["admin_id"]
        }, db)
        return {
            "status": "match",
            "person": result["person"]["name"],
            "person_id": result["person"]["id"],
            "confidence": result["confidence"],
            "config": WORKER_REGISTRY.get(node_key, {}).get("config")
        }
    else:
        await broadcast_alert({
            "type": "new_sighting",
            "matched": False,
            "timestamp": ts,
            "camera_id": camera_id,
            "location": location,
            "snapshot": f"/api/snapshots/{filename}",
            "admin_id": user["admin_id"]
        })
        return {
            "status": "stored",
            "matched": False,
            "config": WORKER_REGISTRY.get(node_key, {}).get("config")
        }


@router.get("/active-users")
async def active_users(user=Depends(get_current_user)):
    from ...core.worker_state import get_live_nodes
    live_nodes = get_live_nodes()
    # Only super_admins see all nodes; admins and workers only see their tenant's nodes
    if user["role"] != "super_admin":
        live_nodes = [n for n in live_nodes if n.get("admin_id") == user["admin_id"] or n["user"] == user["username"]]
        
    sessions = list(SSE_CONNECTIONS.keys())
    return {
        "sessions": sessions,
        "nodes": live_nodes,
        "count": len(live_nodes)
    }

@router.get("/worker/stats")
async def worker_stats(user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    
    # Logic: Admin sees all sightings for their tenant; Worker only sees their own uploads.
    if user["role"] in ("admin", "super_admin"):
        admin_filter = "WHERE admin_id = ?"
        params = (user["admin_id"],)
        if user["admin_id"] == 0:
            admin_filter = ""
            params = ()
        
        cur.execute(f"""
            SELECT id, camera_id, location, timestamp, snapshot_path 
            FROM sightings {admin_filter} ORDER BY timestamp DESC LIMIT 5
        """, params)
        history = [dict(r) for r in cur.fetchall()]
        
        cur.execute(f"SELECT COUNT(*) FROM sightings {admin_filter}", params)
        total_count = cur.fetchone()[0]
    else:
        # Worker role: only see their own uploads
        cur.execute("""
            SELECT id, camera_id, location, timestamp, snapshot_path 
            FROM sightings WHERE uploaded_by = ? ORDER BY timestamp DESC LIMIT 5
        """, (user["username"],))
        history = [dict(r) for r in cur.fetchall()]
        
        cur.execute("SELECT COUNT(*) FROM sightings WHERE uploaded_by = ?", (user["username"],))
        total_count = cur.fetchone()[0]
    
    return {
        "total_detections": total_count,
        "recent_history": history,
        "is_active": any(k.startswith(f"{user['username']}:") for k in WORKER_REGISTRY.keys())
    }

@router.post("/worker/offline")
async def worker_offline(request: Request, camera_id: str = Form(...), user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    from ...core.worker_state import remove_worker
    node_key = f"{user['username']}:{camera_id}"
    remove_worker(node_key)
    from ...core.sse_manager import broadcast_alert
    await broadcast_alert({
        "type": "camera_offline",
        "camera_id": camera_id,
        "detail": f"Camera {camera_id} went offline",
        "admin_id": user["admin_id"]
    })
    
    print(f"[-] Worker Offline Notification: {node_key}")
    return {"status": "offline_logged"}

# --- LIVE STREAMING ENDPOINTS ---
@router.post("/upload-live")
async def upload_live(
    file: UploadFile = File(...),
    camera_id: str = Form("cam-1"),
    user=Depends(get_current_user)
):
    """Worker pushes raw camera frames for live streaming."""
    # Verify camera ownership
    from ...core.database import get_db_conn
    with get_db_conn() as db:
        cur = db.cursor()
        if user["admin_id"] == 0:
            cur.execute("SELECT id FROM cameras WHERE camera_id = ?", (camera_id,))
        else:
            cur.execute("SELECT id FROM cameras WHERE camera_id = ? AND admin_id = ?", (camera_id, user["admin_id"]))
        
        if not cur.fetchone():
            raise HTTPException(status_code=403, detail="Unauthorized camera access")

    node_key = f"{user['username']}:{camera_id}"
    is_new = update_worker_heartbeat(node_key, user["admin_id"])
    
    if is_new:
        from ...core.sse_manager import broadcast_alert
        await broadcast_alert({
            "type": "camera_online",
            "camera_id": camera_id,
            "location": WORKER_REGISTRY.get(node_key, {}).get("location", "Unknown"),
            "admin_id": user["admin_id"]
        })
    
    data = await file.read()
    update_live_frame(node_key, data)
    return {
        "ok": True,
        "config": WORKER_REGISTRY.get(node_key, {}).get("config")
    }

@router.get("/stream/{node_key}", response_class=StreamingResponse)
async def stream_camera(node_key: str, user=Depends(get_current_user)):
    """Produces the MJPEG stream for the frontend UI."""
    # Verify access: super_admin sees all, others see only their own nodes
    if user["role"] != "super_admin":
        from ...core.worker_state import WORKER_REGISTRY
        if node_key not in WORKER_REGISTRY or WORKER_REGISTRY[node_key].get("admin_id") != user["admin_id"]:
             raise HTTPException(status_code=403, detail="Stream access denied")

    async def frame_generator():
        while True:
            import asyncio
            frame = get_live_frame(node_key)
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                await asyncio.sleep(0.01)  # Minimal sleep to allow other tasks without lagging the stream
            else:
                # No frame yet or source disconnected
                await asyncio.sleep(0.3)
                continue
                
    return StreamingResponse(
        frame_generator(), 
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

# --- H.264 HIGH-PERFORMANCE STREAMING ---

@router.post("/upload-live-h264")
async def upload_live_h264(
    request: Request,
    user=Depends(get_current_user)
):
    """Higher performance: Worker pushes encoded H.264 packets."""
    # camera_id is sent as a query param by the worker (raw binary body)
    camera_id = request.query_params.get("camera_id", "cam-1")
    # Verify camera ownership
    from ...core.database import get_db_conn
    with get_db_conn() as db:
        cur = db.cursor()
        user_admin_id = user["admin_id"]
        
        if user_admin_id == 0:
            cur.execute("SELECT id FROM cameras WHERE camera_id = ?", (camera_id,))
        else:
            cur.execute("SELECT id FROM cameras WHERE camera_id = ? AND admin_id = ?", (camera_id, user_admin_id))
            
        if not cur.fetchone():
            raise HTTPException(status_code=403, detail="Unauthorized camera access")

    node_key = f"{user['username']}:{camera_id}"
    update_worker_heartbeat(node_key, user_admin_id)
    
    # Read raw body binary
    data = await request.body()
    update_live_packets(node_key, data)
    
    return {"ok": True}

@router.get("/stream-h264/{node_key}", response_class=StreamingResponse)
async def stream_h264(node_key: str, user=Depends(get_current_user)):
    """Produces the H.264 (MPEG-TS) stream for the frontend UI."""
    # Verify access: super_admin sees all, others see only their own nodes
    if user["role"] != "super_admin":
        from ...core.worker_state import WORKER_REGISTRY
        if node_key not in WORKER_REGISTRY or WORKER_REGISTRY[node_key].get("admin_id") != user["admin_id"]:
             raise HTTPException(status_code=403, detail="Stream access denied")

    return StreamingResponse(
        subscribe_packets(node_key),
        media_type="video/mp2t"
    )
