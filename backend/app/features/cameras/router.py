"""
Camera Management Feature
Handles full CRUD for camera registrations, location assignment,
and per-camera metadata (stream URL, description, status).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from ...core.security import require_admin, get_current_user
from ...core.database import get_db
from ...core.worker_state import WORKER_REGISTRY, get_live_nodes
import sqlite3
import json
import uuid
from datetime import datetime

router = APIRouter(prefix="/api")


# ─── CAMERA CRUD ────────────────────────────────────────────────────────────

@router.get("/cameras")
async def list_cameras(user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("""
        SELECT id, camera_id, name, location, description, stream_url,
               floor_plan_x, floor_plan_y, added_by, added_at
        FROM cameras ORDER BY added_at DESC
    """)
    cameras = [dict(r) for r in cur.fetchall()]

    live_nodes = get_live_nodes()
    live_ids = {n["camera_id"] for n in live_nodes}

    # Attach live status
    for cam in cameras:
        cam["online"] = cam["camera_id"] in live_ids

        # Attach latest sighting for this camera
        cur.execute("""
            SELECT timestamp, matched, person_name, confidence
            FROM sightings WHERE camera_id = ?
            ORDER BY timestamp DESC LIMIT 1
        """, (cam["camera_id"],))
        last = cur.fetchone()
        cam["last_seen"] = dict(last) if last else None

        # Attach ROI from camera_configs
        cur.execute("SELECT roi FROM camera_configs WHERE id LIKE ?", (f"%:{cam['camera_id']}",))
        roi_row = cur.fetchone()
        cam["roi"] = json.loads(roi_row["roi"]) if roi_row and roi_row["roi"] else None

        # Count detections today
        today = datetime.utcnow().strftime("%Y-%m-%d")
        cur.execute("""
            SELECT COUNT(*) FROM sightings
            WHERE camera_id = ? AND timestamp LIKE ?
        """, (cam["camera_id"], f"{today}%"))
        cam["detections_today"] = cur.fetchone()[0]

    return cameras


@router.post("/cameras")
async def add_camera(request: Request, user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    body = await request.json()
    camera_id   = body.get("camera_id", "").strip()
    name        = body.get("name", "").strip()
    location    = body.get("location", "").strip()
    description = body.get("description", "").strip()
    stream_url  = body.get("stream_url", "").strip()
    floor_x     = body.get("floor_plan_x", 50.0)
    floor_y     = body.get("floor_plan_y", 50.0)

    if not camera_id or not name:
        raise HTTPException(status_code=400, detail="camera_id and name are required")

    cur = db.cursor()
    cur.execute("SELECT id FROM cameras WHERE camera_id = ?", (camera_id,))
    if cur.fetchone():
        raise HTTPException(status_code=409, detail="Camera ID already exists")

    cam_pk = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    db.execute("""
        INSERT INTO cameras
          (id, camera_id, name, location, description, stream_url, floor_plan_x, floor_plan_y, added_by, added_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (cam_pk, camera_id, name, location, description, stream_url,
          floor_x, floor_y, user["username"], now))
    db.commit()
    return {"ok": True, "id": cam_pk, "camera_id": camera_id}


@router.put("/cameras/{camera_id}")
async def update_camera(camera_id: str, request: Request,
                        user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    body = await request.json()
    cur = db.cursor()
    cur.execute("SELECT id FROM cameras WHERE camera_id = ?", (camera_id,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Camera not found")

    fields, vals = [], []
    for key in ("name", "location", "description", "stream_url", "floor_plan_x", "floor_plan_y"):
        if key in body:
            fields.append(f"{key} = ?")
            vals.append(body[key])

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    vals.append(camera_id)
    db.execute(f"UPDATE cameras SET {', '.join(fields)} WHERE camera_id = ?", vals)
    db.commit()
    return {"ok": True}


@router.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: str, user=Depends(require_admin),
                        db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT id FROM cameras WHERE camera_id = ?", (camera_id,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Camera not found")

    db.execute("DELETE FROM cameras WHERE camera_id = ?", (camera_id,))
    db.execute("DELETE FROM camera_configs WHERE id LIKE ?", (f"%:{camera_id}",))
    db.commit()
    return {"ok": True}


@router.put("/cameras/{camera_id}/position")
async def update_camera_position(camera_id: str, request: Request,
                                  user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    """Update floor-plan pin coordinates (0-100 percent)."""
    body = await request.json()
    x = body.get("x", 50.0)
    y = body.get("y", 50.0)
    db.execute("UPDATE cameras SET floor_plan_x = ?, floor_plan_y = ? WHERE camera_id = ?",
               (x, y, camera_id))
    db.commit()
    return {"ok": True}
