"""
Camera Management Feature
Handles full CRUD for camera registrations, location assignment,
and per-camera metadata (stream URL, description, status).
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func, and_

from ...core.dependencies import get_current_user, require_admin
from ...core.database import get_db
from ...core.models import Camera, Sighting, Worker
from ..audit_log.router import write_log
from ...core.worker_state import get_live_nodes

router = APIRouter(prefix="/cameras")

# ─── CAMERA CRUD ────────────────────────────────────────────────────────────

@router.get("/")
async def list_cameras(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """
    List cameras. Clients see only their own cameras. Admins see everything.
    """
    query = select(Camera).order_by(Camera.added_at.desc())
    if user.role == "client":
        query = query.where(Camera.client_id == user.client_id)
    
    result = await db.execute(query)
    cameras = result.scalars().all()

    live_nodes = get_live_nodes()
    id_to_key = {n["camera_id"]: n["id"] for n in live_nodes}

    output = []
    for cam in cameras:
        # Latest sighting for this camera
        sighting_query = (
            select(Sighting)
            .where(Sighting.camera_id == cam.camera_id)
            .order_by(Sighting.timestamp.desc())
            .limit(1)
        )
        s_res = await db.execute(sighting_query)
        last_sighting = s_res.scalar_one_or_none()

        # Detections today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        count_res = await db.execute(
            select(func.count(Sighting.id))
            .where(Sighting.camera_id == cam.camera_id)
            .where(Sighting.timestamp >= today_start)
        )
        detections_today = count_res.scalar()

        cam_dict = {
            "id": str(cam.id),
            "camera_id": cam.camera_id,
            "name": cam.name,
            "location": cam.location,
            "description": cam.description,
            "stream_url": cam.stream_url,
            "floor_plan_x": cam.floor_plan_x,
            "floor_plan_y": cam.floor_plan_y,
            "roi": json.loads(cam.roi) if cam.roi else None,
            "added_by": cam.added_by,
            "added_at": cam.added_at,
            "face_enabled": bool(cam.face_enabled),
            "obj_enabled": bool(cam.obj_enabled),
            "stream_enabled": bool(cam.stream_enabled),
            "online": cam.camera_id in id_to_key,
            "node_key": id_to_key.get(cam.camera_id),
            "last_seen": {
                "timestamp": last_sighting.timestamp,
                "matched": last_sighting.matched,
                "person_name": last_sighting.person_name,
                "confidence": last_sighting.confidence
            } if last_sighting else None,
            "detections_today": detections_today,
            "client_id": str(cam.client_id)
        }
        output.append(cam_dict)

    return output

@router.post("/")
async def add_camera(request: Request, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """
    Registers a new camera. 
    """
    body = await request.json()
    camera_id   = body.get("camera_id", "").strip() or f"cam_{uuid.uuid4().hex[:8]}"
    name        = body.get("name", "").strip()
    location    = body.get("location", "").strip()
    description = body.get("description", "").strip()
    stream_url  = body.get("stream_url", "").strip()
    worker_id   = body.get("worker_id")
    
    # Determine client_id
    target_client_id = user.client_id
    if user.role == "admin":
        target_client_id = body.get("client_id")
        if not target_client_id:
            raise HTTPException(status_code=400, detail="client_id is required for admin to add a camera")
        try:
            target_client_id = uuid.UUID(target_client_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid client_id format")
    elif not target_client_id:
        raise HTTPException(status_code=403, detail="User not associated with a client")

    if not name:
        raise HTTPException(status_code=400, detail="Camera name is required")

    cam_pk = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    
    new_cam = Camera(
        id=cam_pk,
        camera_id=camera_id,
        name=name,
        location=location,
        description=description,
        stream_url=stream_url,
        added_by=user.username,
        added_at=now,
        face_enabled=1,
        obj_enabled=1,
        stream_enabled=1,
        client_id=target_client_id,
        worker_id=uuid.UUID(worker_id) if worker_id else None
    )
    db.add(new_cam)
    await db.commit()
    
    await write_log(db, username=user.username, role=user.role, action="add_camera", target=camera_id, detail=f"Registered camera '{name}' for client {target_client_id}", ip=request.client.host)
    return {"ok": True, "id": cam_pk, "camera_id": camera_id}

@router.put("/{camera_id}")
async def update_camera(camera_id: str, request: Request,
                        user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    body = await request.json()
    
    query = select(Camera).where(Camera.camera_id == camera_id)
    if user.role == "client":
        query = query.where(Camera.client_id == user.client_id)
    
    res = await db.execute(query)
    cam = res.scalar_one_or_none()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found or access denied")

    # Update fields
    for key in ("name", "location", "description", "stream_url", "floor_plan_x", "floor_plan_y", "face_enabled", "obj_enabled", "stream_enabled"):
        if key in body:
            val = body[key]
            if key.endswith("_enabled"):
                val = 1 if val else 0
            setattr(cam, key, val)

    await db.commit()
    return {"ok": True}

@router.delete("/{camera_id}")
async def delete_camera(camera_id: str, request: Request, user=Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    # Note: camera_id here refers to the primary key 'id' in the JS call deleteCamera(id)
    query = select(Camera).where(Camera.id == camera_id)
    if user.role == "client":
        query = query.where(Camera.client_id == user.client_id)
    
    res = await db.execute(query)
    cam = res.scalar_one_or_none()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found or access denied")

    await db.delete(cam)
    await db.commit()
    
    await write_log(db, username=user.username, role=user.role, action="delete_camera", target=str(cam.camera_id), detail=f"Removed camera {cam.camera_id}", ip=request.client.host)
    return {"ok": True}

@router.put("/{camera_id}/position")
async def update_camera_position(camera_id: str, request: Request,
                                  user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Update floor-plan pin coordinates (0-100 percent)."""
    body = await request.json()
    x = body.get("x", 50.0)
    y = body.get("y", 50.0)
    
    query = select(Camera).where(Camera.camera_id == camera_id)
    if user.role == "client":
        query = query.where(Camera.client_id == user.client_id)
        
    res = await db.execute(query)
    cam = res.scalar_one_or_none()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found or access denied")
        
    cam.floor_plan_x = x
    cam.floor_plan_y = y
    await db.commit()
    return {"ok": True}
