"""
Camera Management Feature
Handles full CRUD for camera registrations, location assignment,
and per-camera metadata (stream URL, description, status).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from ...core.security import require_admin, get_current_user
from ...core.database import get_db
from ..audit_log.router import write_log
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
    
    # Filter by admin_id
    admin_filter = "WHERE admin_id = ?"
    params = (user["admin_id"],)
    if user["admin_id"] == 0:
        admin_filter = ""
        params = ()

    cur.execute(f"""
        SELECT id, camera_id, name, location, description, stream_url,
               floor_plan_x, floor_plan_y, roi, added_by, added_at,
               face_enabled, obj_enabled, stream_enabled, admin_id
        FROM cameras {admin_filter} ORDER BY added_at DESC
    """, params)
    cameras = [dict(r) for r in cur.fetchall()]

    live_nodes = get_live_nodes()
    # Map (admin_id, camera_id) -> node_key to prevent multi-tenant clobbering
    lookup = {(n.get("admin_id"), n["camera_id"]): n["id"] for n in live_nodes}

    # Attach live status and node_key
    for cam in cameras:
        key = (cam["admin_id"], cam["camera_id"])
        cam["online"] = key in lookup
        cam["node_key"] = lookup.get(key)

        # Attach latest sighting for this camera (filtered by admin_id for accuracy)
        cur.execute("""
            SELECT timestamp, matched, person_name, confidence
            FROM sightings WHERE camera_id = ? AND admin_id = ?
            ORDER BY timestamp DESC LIMIT 1
        """, (cam["camera_id"], cam["admin_id"]))
        last = cur.fetchone()
        cam["last_seen"] = dict(last) if last else None

        # ROI is already in cam["roi"] from the main SELECT, just need to parse it
        cam["roi"] = json.loads(cam["roi"]) if cam.get("roi") else None

        # Count detections today (filtered by admin_id)
        today = datetime.utcnow().strftime("%Y-%m-%d")
        cur.execute("""
            SELECT COUNT(*) FROM sightings
            WHERE camera_id = ? AND admin_id = ? AND timestamp LIKE ?
        """, (cam["camera_id"], cam["admin_id"], f"{today}%"))
        cam["detections_today"] = cur.fetchone()[0]

        # Convert integers to bools
        cam["face_enabled"]   = bool(cam.get("face_enabled", 1))
        cam["obj_enabled"]    = bool(cam.get("obj_enabled", 1))
        cam["stream_enabled"] = bool(cam.get("stream_enabled", 1))

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
    face_en     = body.get("face_enabled", True)
    obj_en      = body.get("obj_enabled", True)
    strm_en     = body.get("stream_enabled", True)

    if not camera_id or not name:
        raise HTTPException(status_code=400, detail="camera_id and name are required")

    cur = db.cursor()
    cur.execute("SELECT id FROM cameras WHERE camera_id = ? AND admin_id = ?", (camera_id, user["admin_id"]))
    if cur.fetchone():
        raise HTTPException(status_code=409, detail="Camera ID already exists for this tenant")

    cam_pk = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    db.execute("""
        INSERT INTO cameras
          (id, camera_id, name, location, description, stream_url, floor_plan_x, floor_plan_y, added_by, added_at, face_enabled, obj_enabled, stream_enabled, admin_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (cam_pk, camera_id, name, location, description, stream_url,
          floor_x, floor_y, user["username"], now, 1 if face_en else 0, 1 if obj_en else 0, 1 if strm_en else 0, user["admin_id"]))
    db.commit()
    write_log(db, username=user["username"], role=user["role"], action="add_camera", target=camera_id, detail=f"Registered camera '{name}' ({camera_id}) at {location}", ip=request.client.host, admin_id=user["admin_id"])
    return {"ok": True, "id": cam_pk, "camera_id": camera_id}


@router.put("/cameras/{camera_id}")
async def update_camera(camera_id: str, request: Request,
                        user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    body = await request.json()
    cur = db.cursor()
    # Ownership Check
    if user["admin_id"] == 0:
        cur.execute("SELECT id FROM cameras WHERE camera_id = ?", (camera_id,))
    else:
        cur.execute("SELECT id FROM cameras WHERE camera_id = ? AND admin_id = ?", (camera_id, user["admin_id"]))
        
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Camera not found or access denied")

    fields, vals = [], []
    for key in ("name", "location", "description", "stream_url", "floor_plan_x", "floor_plan_y", "face_enabled", "obj_enabled", "stream_enabled"):
        if key in body:
            fields.append(f"{key} = ?")
            if key.endswith("_enabled"):
                vals.append(1 if body[key] else 0)
            else:
                vals.append(body[key])

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    vals.append(camera_id)
    # Strict ownership check in update
    admin_filter = "AND admin_id = ?" if user["admin_id"] != 0 else ""
    if user["admin_id"] != 0:
        vals.append(user["admin_id"])

    db.execute(f"UPDATE cameras SET {', '.join(fields)} WHERE camera_id = ? {admin_filter}", vals)
    db.commit()
    write_log(db, username=user["username"], role=user["role"], action="update_camera", target=camera_id, detail=f"Updated camera {camera_id}", ip=request.client.host, admin_id=user["admin_id"])
    return {"ok": True}


@router.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: str, request: Request, user=Depends(require_admin),
                         db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    # Ownership Check
    if user["admin_id"] == 0:
        cur.execute("SELECT id FROM cameras WHERE camera_id = ?", (camera_id,))
    else:
        cur.execute("SELECT id FROM cameras WHERE camera_id = ? AND admin_id = ?", (camera_id, user["admin_id"]))
        
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Camera not found or access denied")

    if user["admin_id"] == 0:
        db.execute("DELETE FROM cameras WHERE camera_id = ?", (camera_id,))
    else:
        db.execute("DELETE FROM cameras WHERE camera_id = ? AND admin_id = ?", (camera_id, user["admin_id"]))
    db.commit()
    write_log(db, username=user["username"], role=user["role"], action="delete_camera", target=camera_id, detail=f"Removed camera {camera_id}", ip=request.client.host, admin_id=user["admin_id"])
    return {"ok": True}


@router.put("/cameras/{camera_id}/position")
async def update_camera_position(camera_id: str, request: Request,
                                  user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    """Update floor-plan pin coordinates (0-100 percent)."""
    body = await request.json()
    x = body.get("x", 50.0)
    y = body.get("y", 50.0)
    
    # Ownership Check
    admin_filter = "AND admin_id = ?" if user["admin_id"] != 0 else ""
    params = (x, y, camera_id) + ((user["admin_id"],) if user["admin_id"] != 0 else ())
    
    db.execute(f"UPDATE cameras SET floor_plan_x = ?, floor_plan_y = ? WHERE camera_id = ? {admin_filter}",
               params)
    db.commit()
    return {"ok": True}


@router.post("/cameras/config/{camera_id}")
async def set_camera_config_flags(
    camera_id: str,
    face: int = None,
    obj: int = None,
    stream: int = None,
    user=Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db)
):
    """Legacy/Quick toggle for camera features (face, obj, stream)."""
    from ...core.worker_state import update_worker_config

    updates = {}
    if face is not None:   updates["face_enabled"] = bool(face)
    if obj is not None:    updates["obj_enabled"] = bool(obj)
    if stream is not None: updates["stream_enabled"] = bool(stream)

    if not updates:
        raise HTTPException(status_code=400, detail="No config fields provided")

    update_worker_config(camera_id, updates, user["admin_id"])
    write_log(db, username=user["username"], role=user["role"], action="camera_config", target=camera_id, detail=f"Updated config flags: {updates}", admin_id=user["admin_id"])
    
    return {"ok": True, "updated": updates}
