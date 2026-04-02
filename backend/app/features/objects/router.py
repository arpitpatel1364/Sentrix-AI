from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from fastapi.responses import StreamingResponse
from typing import List
import uuid
import time
import os
from ...core.security import require_admin, get_current_user
from ...core.database import get_db
from ...core.config import SNAPSHOTS_DIR
from ...core.sse_manager import SSE_CONNECTIONS
from ...core.worker_state import update_worker_heartbeat, WORKER_REGISTRY
import sqlite3
import json

router = APIRouter(prefix="/api")

@router.post("/upload-object")
async def upload_object(
    camera_id: str = Form(...),
    location: str = Form(...),
    object_label: str = Form(...),
    confidence: float = Form(...),
    file: UploadFile = File(...),
    user=Depends(get_current_user),   # Workers (role=worker) can upload
    db: sqlite3.Connection = Depends(get_db)
):
    try:
        # Sanitization & Validation
        object_label = object_label.strip().lower() if object_label else "unknown"
        if confidence < 0 or confidence > 1:
            # Fallback for percentage vs 0-1 range
            if confidence > 1: confidence /= 100.0

        # Register node heartbeat so it shows as active
        camera_id = camera_id.strip().rstrip(".").strip() # Sanitize paths
        node_key = f"{user['username']}:{camera_id}"
        update_worker_heartbeat(node_key)

        obj_id = str(uuid.uuid4())
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Save snapshot in camera-specific directory
        cam_dir = SNAPSHOTS_DIR / camera_id
        cam_dir.mkdir(parents=True, exist_ok=True)
        
        # Systematic Filename Generation
        now_str = time.strftime("%Y%m%d_%H%M%S")
        safe_label = object_label.replace(" ", "_").lower()
        short_uuid = obj_id[:8]
        filename = f"obj_{now_str}_{safe_label}_{camera_id}_{short_uuid}.jpg"
        file_path = cam_dir / filename
        content = await file.read()
        if not content:
            raise ValueError("Empty file uploaded")

        with open(file_path, "wb") as f:
            f.write(content)
            
        # Save to DB
        db.execute("""
            INSERT INTO object_detections (id, camera_id, location, timestamp, object_label, confidence, snapshot_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (obj_id, camera_id, location, timestamp, object_label, confidence, f"{camera_id}/{filename}"))
        db.commit()

        # Broadcast SSE Alert to all admin dashboards
        payload = {
            "type": "new_object",
            "camera_id": camera_id,
            "location": location,
            "object_label": object_label,
            "confidence": confidence,
            "snapshot": f"/api/snapshots/{camera_id}/{filename}",
            "timestamp": timestamp
        }
        for user_queues in SSE_CONNECTIONS.values():
            for q in user_queues:
                try:
                    q.put_nowait(payload)
                except Exception:
                    pass
        
        return {
            "status": "ok",
            "object_id": obj_id,
            "roi": WORKER_REGISTRY.get(node_key, {}).get("roi")
        }
    except Exception as e:
        print(f"[!] Backend Error in upload_object: {e}")
        # Log to a file if possible for deeper forensics
        raise HTTPException(status_code=500, detail=f"Object upload failed: {str(e)}")

@router.get("/objects")
async def get_objects(limit: int = 50, user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM object_detections")
    total_count = cur.fetchone()[0]

    cur.execute("""
        SELECT id, camera_id, location, timestamp, object_label, confidence, snapshot_path 
        FROM object_detections ORDER BY timestamp DESC LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["snapshot"] = f"/api/snapshots/{r['snapshot_path']}"
    return {"objects": rows, "total_count": total_count}
