from fastapi import APIRouter, Depends, HTTPException, Form, Request
import json
from ...core.security import get_current_user
from .service import save_node_roi, get_all_rois_for_user
from ..audit_log.router import write_log
from ...core.database import get_db
import sqlite3

router = APIRouter(prefix="/api/roi", tags=["ROI"])

@router.post("/save")
async def save_roi(
    node_key: str = Form(None),
    camera_id: str = Form(None),
    roi: str = Form(...), # "[x1, y1, x2, y2]" or ""
    request: Request = None,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db)
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

    try:
        if not roi or roi == 'null' or roi == "":
            save_node_roi(node_key, None)
            write_log(db, username=user["username"], role=user["role"], action="roi_clear", target=node_key, detail=f"Cleared ROI for {node_key}", ip=request.client.host if request else "")
            return {"status": "ok", "message": "ROI cleared"}
            
        roi_list = json.loads(roi)
        if len(roi_list) != 4:
            raise ValueError("ROI must have 4 coordinates")
            
        save_node_roi(node_key, roi_list)
        write_log(db, username=user["username"], role=user["role"], action="roi_save", target=node_key, detail=f"Saved ROI for {node_key}: {roi_list}", ip=request.client.host if request else "")
        print(f"[ROI] Feature Saved for {node_key}: {roi_list}")
        return {"status": "ok", "message": "ROI saved", "roi": roi_list}
    except Exception as e:
        print(f"[!] ROI Feature Save error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/list")
async def get_worker_rois(user=Depends(get_current_user)):
    """Returns local camera IDs and their assigned ROIs for the current worker."""
    rois = get_all_rois_for_user(user['username'])
    return {"status": "ok", "rois": rois}

# Legacy Alias Support for Worker Sync
@router.get("/worker/rois", include_in_schema=False)
async def legacy_get_rois(user=Depends(get_current_user)):
    return await get_worker_rois(user)

@router.post("/worker/roi", include_in_schema=False)
async def legacy_save_roi(
    node_key: str = Form(None),
    camera_id: str = Form(None),
    roi: str = Form(...),
    request: Request = None,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db)
):
    return await save_roi(node_key, camera_id, roi, request, user, db)
