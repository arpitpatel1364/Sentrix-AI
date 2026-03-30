from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form, BackgroundTasks
from typing import List
import uuid
import cv2
import numpy as np
import time
from datetime import datetime
from ...core.security import get_current_user, require_admin
from ...core.database import get_db
from ...core.face_engine import (
    get_embedding, bytes_to_cv2, match_wanted, QDRANT_CLIENT, QDRANT_AVAILABLE
)
from ...core.config import SNAPSHOTS_DIR
from ...core.worker_state import update_worker_heartbeat, ACTIVE_WORKERS, get_live_nodes
from ...core.sse_manager import SSE_CONNECTIONS, broadcast_alert
from qdrant_client.models import PointStruct

router = APIRouter(prefix="/api")

def _save_sighting_task(sighting_id: str, img: np.ndarray, sighting: dict, embedding: np.ndarray, camera_id: str, location: str, ts: str):
    try:
        if QDRANT_AVAILABLE and QDRANT_CLIENT:
            QDRANT_CLIENT.upsert(
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
    user=Depends(get_current_user)
):
    node_key = f"{user['username']}:{camera_id}"
    update_worker_heartbeat(node_key)
    
    data = await file.read()
    img = bytes_to_cv2(data)
    if img is None:
        raise HTTPException(status_code=400, detail="Invalid image")

    embedding = get_embedding(img)
    if embedding is None:
        return {"status": "no_face"}

    result = match_wanted(embedding)
    sighting_id = str(uuid.uuid4())
    ts = datetime.utcnow().isoformat()
    filename = f"{camera_id}/{sighting_id}.jpg"
    
    cam_dir = SNAPSHOTS_DIR / camera_id
    cam_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = SNAPSHOTS_DIR / filename
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
    with next(get_db()) as conn:
        conn.execute("""
            INSERT INTO sightings (id, camera_id, location, timestamp, uploaded_by, snapshot_path, matched, person_id, person_name, confidence, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sighting["id"], sighting["camera_id"], sighting["location"], sighting["timestamp"],
            sighting["uploaded_by"], sighting["snapshot_path"], sighting["matched"],
            sighting["person_id"], sighting["person_name"], sighting["confidence"],
            emb_blob
        ))
        conn.commit()

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
        return {"status": "match", "person": result["person"]["name"], "person_id": result["person"]["id"], "confidence": result["confidence"]}
    else:
        await broadcast_alert({
            "type": "new_sighting",
            "matched": False,
            "timestamp": ts,
            "camera_id": camera_id,
            "location": location,
            "snapshot": f"/api/snapshots/{filename}"
        })
        return {"status": "stored", "matched": False}

@router.get("/active-users")
async def active_users(user=Depends(require_admin)):
    sessions = list(SSE_CONNECTIONS.keys())
    live_nodes = get_live_nodes()
    return {
        "sessions": sessions,
        "nodes": live_nodes,
        "count": len(live_nodes)
    }

@router.get("/worker/stats")
async def worker_stats(user=Depends(get_current_user)):
    with next(get_db()) as conn:
        cur = conn.cursor()
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
            "is_active": any(k.startswith(f"{user['username']}:") for k in ACTIVE_WORKERS.keys())
        }
