import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, Form, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from ...core.dependencies import get_current_user
from ...core.database import get_db
from ...core.models import Camera, Client
from ..audit_log.router import write_log
from ...core.worker_state import set_worker_roi, WORKER_REGISTRY

router = APIRouter(prefix="/roi", tags=["ROI"])

@router.post("/save")
async def save_roi(
    node_key: str = Form(None),           # user:cam_id
    camera_id: str = Form(None),         # cam_id
    roi: str = Form(...),                # "[x1, y1, x2, y2]" or ""
    request: Request = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Save ROI coordinates (normalized 0.0 - 1.0) and persist to DB."""
    
    # 1. Resolve camera_id and node_key
    if not camera_id:
        if not node_key or ":" not in node_key:
            raise HTTPException(status_code=400, detail="camera_id or valid node_key (user:cam) required")
        camera_id = node_key.split(":", 1)[1]
    
    if not node_key:
        node_key = f"{user.username}:{camera_id}"

    # 2. Permission Check & Fetch Camera
    query = select(Camera).where(Camera.camera_id == camera_id)
    if user.role == "client":
        query = query.where(Camera.client_id == user.client_id)
        
    res = await db.execute(query)
    camera = res.scalar_one_or_none()
    
    if not camera:
        raise HTTPException(status_code=403, detail="Not authorized to set ROI for this camera")

    try:
        # 3. Process ROI data
        if not roi or roi == 'null' or roi == "":
            camera.roi = None
            set_worker_roi(node_key, None)
            await db.commit()
            await write_log(db, username=user.username, role=user.role, action="roi_clear", target=camera_id, detail=f"Cleared ROI for {camera_id}", ip=request.client.host if request else "")
            return {"status": "ok", "message": "ROI cleared"}
            
        roi_list = json.loads(roi)
        if not isinstance(roi_list, list) or len(roi_list) != 4:
            raise ValueError("ROI must be a list of 4 coordinates")
            
        # 4. Save to DB and Memory
        camera.roi = json.dumps(roi_list)
        set_worker_roi(node_key, roi_list)
        await db.commit()
        
        await write_log(db, username=user.username, role=user.role, action="roi_save", target=camera_id, detail=f"Saved ROI for {camera_id}: {roi_list}", ip=request.client.host if request else "")
        return {"status": "ok", "message": "ROI saved", "roi": roi_list}
        
    except Exception as e:
        print(f"[!] ROI Save error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/list")
async def get_worker_configs(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Returns local camera configs (ROI + toggles) for the current tenant/user."""
    query = select(Camera)
    if user.role == "client":
        query = query.where(Camera.client_id == user.client_id)
        
    res = await db.execute(query)
    cameras = res.scalars().all()
    
    configs = {}
    for c in cameras:
        configs[c.camera_id] = {
            "roi": json.loads(c.roi) if c.roi else None,
            "face_enabled": bool(c.face_enabled),
            "obj_enabled": bool(c.obj_enabled),
            "stream_enabled": bool(c.stream_enabled)
        }
    return {"status": "ok", "configs": configs}

# --- Legacy Aliases ---
@router.get("/worker/rois", include_in_schema=False)
async def legacy_get_configs(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await get_worker_configs(user, db)

@router.post("/worker/roi", include_in_schema=False)
async def legacy_save_roi(
    node_key: str = Form(None),
    camera_id: str = Form(None),
    roi: str = Form(...),
    request: Request = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    return await save_roi(node_key, camera_id, roi, request, user, db)
