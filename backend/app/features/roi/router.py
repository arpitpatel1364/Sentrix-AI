from fastapi import APIRouter, Depends, HTTPException, Form, Request
import json
import sqlite3
from ...core.security import get_current_user
from .service import save_node_roi, get_all_configs_for_admin
from ..audit_log.router import write_log
from ...core.database import get_db

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
    
    # Permission check: Only admins/super_admins of the same admin_id or the owner of the node can set ROI
    # node_key is usually username:camera_id
    if ":" in node_key:
        target_user = node_key.split(":")[0]
    else:
        # If no colon, assume the current user owns it if it's just a camera_id
        target_user = user["username"]

    # Fetch target user's admin_id
    cur = db.cursor()
    cur.execute("SELECT admin_id FROM users WHERE username = ?", (target_user,))
    row = cur.fetchone()
    if not row:
         raise HTTPException(status_code=404, detail=f"Target user '{target_user}' not found for node_key '{node_key}'")
    target_admin_id = row["admin_id"]

    if user["admin_id"] != 0 and user["admin_id"] != target_admin_id:
        raise HTTPException(status_code=403, detail="Not authorized to set ROI for a different tenant's node")
    
    if user["role"] not in ("admin", "super_admin") and user["username"] != target_user:
        raise HTTPException(status_code=403, detail="Not authorized to set ROI for this node")

    try:
        if not roi or roi == 'null' or roi == "":
            save_node_roi(node_key, None)
            write_log(db, username=user["username"], role=user["role"], action="roi_clear", target=node_key, detail=f"Cleared ROI for {node_key}", ip=request.client.host if request else "", admin_id=user["admin_id"])
            return {"status": "ok", "message": "ROI cleared"}
            
        roi_list = json.loads(roi)
        if not isinstance(roi_list, list) or len(roi_list) != 4:
            raise ValueError("ROI must be a list of 4 coordinates [x1, y1, x2, y2]")
            
        save_node_roi(node_key, roi_list)
        write_log(db, username=user["username"], role=user["role"], action="roi_save", target=node_key, detail=f"Saved ROI for {node_key}: {roi_list}", ip=request.client.host if request else "", admin_id=user["admin_id"])
        print(f"[ROI] Feature Saved for {node_key}: {roi_list}")
        return {"status": "ok", "message": "ROI saved", "roi": roi_list}
    except Exception as e:
        print(f"[!] ROI Feature Save error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/list")
async def get_worker_configs(user=Depends(get_current_user)):
    """Returns all camera configs (ROI + toggles) for the current worker's tenant."""
    configs = get_all_configs_for_admin(user['admin_id'])
    return {"status": "ok", "configs": configs}

# Legacy Alias Support for Worker Sync
@router.get("/worker/configs", include_in_schema=False)
@router.get("/worker/rois", include_in_schema=False)
async def legacy_get_configs(user=Depends(get_current_user)):
    """Handle both legacy /worker/configs and worker's /worker/rois endpoints."""
    return await get_worker_configs(user)

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

