from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from fastapi.responses import StreamingResponse
from typing import List
import uuid
import time
import os
from ...core.security import require_admin, get_current_user
from ...core.database import get_db
from ...core.config import SNAPSHOTS_DIR
from ...core.sse_manager import SSE_CONNECTIONS, broadcast_alert
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

        # Verify camera ownership
        cur = db.cursor()
        user_admin_id = user["admin_id"]
            
        print(f"[DEBUG] upload_object: cam={camera_id}, admin=ID:{user_admin_id}, user={user['username']}")
        
        # Ownership Check: Super Admin (0) can upload anywhere; others must own camera
        if user_admin_id == 0:
            cur.execute("SELECT id FROM cameras WHERE camera_id = ?", (camera_id,))
        else:
            cur.execute("SELECT id FROM cameras WHERE camera_id = ? AND admin_id = ?", (camera_id, user_admin_id))
            
        if not cur.fetchone():
            raise HTTPException(status_code=403, detail="Unauthorized camera access")

        node_key = f"{user['username']}:{camera_id}"
        update_worker_heartbeat(node_key, user_admin_id)

        obj_id = str(uuid.uuid4())
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Save snapshot in tenant-isolated directory: SNAPSHOTS_DIR/{admin_id}/{camera_id}/
        admin_id_val = user["admin_id"]
        cam_dir = SNAPSHOTS_DIR / str(admin_id_val) / camera_id
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
            INSERT INTO object_detections (id, camera_id, location, timestamp, object_label, confidence, snapshot_path, admin_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (obj_id, camera_id, location, timestamp, object_label, confidence, f"{admin_id_val}/{camera_id}/{filename}", user["admin_id"]))
        db.commit()

        # Broadcast SSE Alert to all admin dashboards
        payload = {
            "type": "new_object",
            "camera_id": camera_id,
            "location": location,
            "object_label": object_label,
            "confidence": confidence,
            "snapshot": f"/api/snapshots/{admin_id_val}/{camera_id}/{filename}",
            "timestamp": timestamp,
            "admin_id": user["admin_id"]
        }
        # Broadcast SSE Alert to the correct admin dashboard
        await broadcast_alert(payload)
        
        # ── Alert Rules Engine ───────────────────────────────────────────
        from ...features.alert_rules.router import evaluate_rules
        await evaluate_rules({
            "type": "object", 
            "camera_id": camera_id, 
            "object_label": object_label,
            "confidence": confidence * 100.0, # Scale to 0-100 for rules engine
            "timestamp": timestamp,
            "admin_id": user["admin_id"]
        }, db)

        return {
            "status": "ok",
            "object_id": obj_id,
            "config": WORKER_REGISTRY.get(node_key, {}).get("config")
        }
    except Exception as e:
        print(f"[!] Backend Error in upload_object: {e}")
        # Log to a file if possible for deeper forensics
        raise HTTPException(status_code=500, detail=f"Object upload failed: {str(e)}")

@router.get("/objects")
async def get_objects(limit: int = 50, user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    
    # Filter by admin_id
    admin_filter = "WHERE admin_id = ?"
    params = (user["admin_id"],)
    if user["admin_id"] == 0:
        admin_filter = ""
        params = ()

    cur.execute(f"SELECT COUNT(*) FROM object_detections {admin_filter}", params)
    total_count = cur.fetchone()[0]

    cur.execute(f"""
        SELECT id, camera_id, location, timestamp, object_label, confidence, snapshot_path 
        FROM object_detections 
        {admin_filter}
        ORDER BY timestamp DESC LIMIT ?
    """, params + (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["snapshot"] = f"/api/snapshots/{r['snapshot_path']}"
    return {"objects": rows, "total_count": total_count}
