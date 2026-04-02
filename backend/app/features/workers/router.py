from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form, BackgroundTasks
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
from ...core.face_engine import (
    get_embedding, bytes_to_cv2, match_wanted, QDRANT_AVAILABLE
)
from ...core import face_engine
from ...core.config import SNAPSHOTS_DIR
from ...core.worker_state import update_worker_heartbeat, get_live_nodes, set_worker_roi
from ...core.sse_manager import SSE_CONNECTIONS, broadcast_alert
from ...core.stream_state import update_live_frame, get_live_frame, LIVE_FRAMES
from qdrant_client.models import PointStruct
import sqlite3

router = APIRouter(prefix="/api")

def _save_sighting_task(sighting_id: str, img: np.ndarray, sighting: dict, embedding: np.ndarray, camera_id: str, location: str, ts: str):
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
                        "person_name": sighting["person_name"]
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
    node_key = f"{user['username']}:{camera_id}"
    update_worker_heartbeat(node_key)
    
    data = await file.read()
    img = bytes_to_cv2(data)
    if img is None:
        raise HTTPException(status_code=400, detail="Invalid image")

    embedding = get_embedding(img)
    if embedding is None:
        return {
            "status": "no_face",
            "roi": WORKER_REGISTRY.get(node_key, {}).get("roi")
        }

    result = match_wanted(embedding)
    sighting_id = str(uuid.uuid4())
    ts = datetime.utcnow().isoformat()
    
    cam_dir = SNAPSHOTS_DIR / camera_id
    cam_dir.mkdir(parents=True, exist_ok=True)
    snap_filename = f"{sighting_id}.jpg"
    filename = f"{camera_id}/{snap_filename}"   # DB path: cam-1/uuid.jpg
    snapshot_path = cam_dir / snap_filename     # File path: SNAPSHOTS_DIR/cam-1/uuid.jpg
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
        "confidence": 0.0
    }

    if result:
        sighting["matched"] = True
        sighting["person_name"] = result["person"]["name"]
        sighting["person_id"] = result["person"]["id"]
        sighting["confidence"] = result["confidence"]
        
    emb_blob = embedding.astype(np.float32).tobytes()
    db.execute("""
        INSERT INTO sightings (id, camera_id, location, timestamp, uploaded_by, snapshot_path, matched, person_id, person_name, confidence, embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sighting["id"], sighting["camera_id"], sighting["location"], sighting["timestamp"],
        sighting["uploaded_by"], sighting["snapshot_path"], sighting["matched"],
        sighting["person_id"], sighting["person_name"], sighting["confidence"],
        emb_blob
    ))
    db.commit()

    background_tasks.add_task(_save_sighting_task, sighting_id, img, sighting, embedding, camera_id, location, ts)

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
        })
        # ── Alert Rules Engine ───────────────────────────────────────────
        from ...features.alert_rules.router import evaluate_rules
        await evaluate_rules({
            "type": "face", "camera_id": camera_id, "matched": True,
            "confidence": result["confidence"],
            "person_name": result["person"]["name"],
            "timestamp": ts,
        }, db)
        return {
            "status": "match",
            "person": result["person"]["name"],
            "person_id": result["person"]["id"],
            "confidence": result["confidence"],
            "roi": WORKER_REGISTRY.get(node_key, {}).get("roi")
        }
    else:
        await broadcast_alert({
            "type": "new_sighting",
            "matched": False,
            "timestamp": ts,
            "camera_id": camera_id,
            "location": location,
            "snapshot": f"/api/snapshots/{filename}"
        })
        return {
            "status": "stored",
            "matched": False,
            "roi": WORKER_REGISTRY.get(node_key, {}).get("roi")
        }


@router.get("/active-users")
async def active_users(user=Depends(get_current_user)):
    from ...core.worker_state import get_live_nodes
    live_nodes = get_live_nodes()
    
    # Non-admins only see their own nodes
    if user["role"] != "admin":
        live_nodes = [n for n in live_nodes if n["user"] == user["username"]]
        
    sessions = list(SSE_CONNECTIONS.keys())
    return {
        "sessions": sessions,
        "nodes": live_nodes,
        "count": len(live_nodes)
    }

@router.post("/worker/roi")
async def save_roi(
    node_key: str = Form(None),
    camera_id: str = Form(None),
    roi: str = Form(...), # "[x1, y1, x2, y2]" or ""
    user=Depends(get_current_user)
):
    """Save ROI coordinates (normalized 0.0 - 1.0)."""
    # If node_key not provided, build it (admin likely uses node_key)
    if not node_key:
        if not camera_id:
            raise HTTPException(status_code=400, detail="Either node_key or camera_id required")
        node_key = f"{user['username']}:{camera_id}"
    
    # Permission check: Only admins or the owner of the node can set ROI
    target_user = node_key.split(":")[0]
    if user["role"] != "admin" and user["username"] != target_user:
        raise HTTPException(status_code=403, detail="Not authorized to set ROI for this node")

    import json
    try:
        if not roi or roi == 'null':
            set_worker_roi(node_key, None)
            return {"status": "ok", "message": "ROI cleared"}
            
        roi_list = json.loads(roi)
        if len(roi_list) != 4:
            raise ValueError("ROI must have 4 coordinates")
            
        set_worker_roi(node_key, roi_list)
        return {"status": "ok", "message": "ROI saved", "roi": roi_list}
    except Exception as e:
        print(f"[!] ROI Save error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/worker/rois")
async def get_worker_rois(user=Depends(get_current_user)):
    """Returns local camera IDs and their assigned ROIs for the current worker."""
    from ...core.worker_state import WORKER_REGISTRY
    res = {}
    prefix = f"{user['username']}:"
    for node_key, info in WORKER_REGISTRY.items():
        if node_key.startswith(prefix):
            cam_id = node_key[len(prefix):]
            res[cam_id] = info.get("roi")
    return res


@router.get("/worker/stats")
async def worker_stats(user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("""
        SELECT id, camera_id, location, timestamp, snapshot_path 
        FROM sightings WHERE uploaded_by = ? ORDER BY timestamp DESC LIMIT 5
    """, (user["username"],))
    history = [dict(r) for r in cur.fetchall()]
    for h in history:
        h["snapshot"] = f"/api/snapshots/{h['snapshot_path']}"
        
    cur.execute("SELECT COUNT(*) FROM sightings WHERE uploaded_by = ?", (user["username"],))
    total_count = cur.fetchone()[0]
    
    return {
        "total_detections": total_count,
        "recent_history": history,
        "is_active": any(k.startswith(f"{user['username']}:") for k in WORKER_REGISTRY.keys())
    }

@router.post("/worker/offline")
async def worker_offline(camera_id: str = Form(...), user=Depends(get_current_user)):
    from ...core.worker_state import remove_worker
    node_key = f"{user['username']}:{camera_id}"
    remove_worker(node_key)
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
    node_key = f"{user['username']}:{camera_id}"
    update_worker_heartbeat(node_key)
    
    data = await file.read()
    update_live_frame(node_key, data)
    return {
        "ok": True,
        "roi": WORKER_REGISTRY.get(node_key, {}).get("roi")
    }

@router.get("/stream/{camera_id}", response_class=StreamingResponse)
async def stream_camera(camera_id: str):
    """Produces the MJPEG stream for the frontend UI."""
    async def frame_generator():
        while True:
            import asyncio
            frame = get_live_frame(camera_id)
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
