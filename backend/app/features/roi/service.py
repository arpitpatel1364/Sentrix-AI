import json
from typing import List, Optional, Tuple
from ...core.worker_state import set_worker_roi, WORKER_REGISTRY

def is_point_in_roi(x: float, y: float, roi: List[float]) -> bool:
    """
    Check if a normalized point (0.0 - 1.0) is within the ROI box.
    ROI form: [x1, y1, x2, y2]
    """
    if not roi or len(roi) != 4:
        return True # Default to full frame if ROI is missing
    
    x1, y1, x2, y2 = roi
    # Handle potentially inverted coordinates
    min_x, max_x = min(x1, x2), max(x1, x2)
    min_y, max_y = min(y1, y2), max(y1, y2)
    
    return min_x <= x <= max_x and min_y <= y <= max_y

def is_box_in_roi(bbox_norm: Tuple[float, float, float, float], roi: List[float]) -> bool:
    """
    Check if the center of a normalized bounding box is within the ROI.
    bbox_norm can be (cx, cy, w, h) or [x1, y1, x2, y2]
    """
    if len(bbox_norm) != 4: return True
    
    # Check if it looks like [x1, y1, x2, y2] where x2 > x1
    if bbox_norm[2] > bbox_norm[0] and bbox_norm[3] > bbox_norm[1]:
        cx = (bbox_norm[0] + bbox_norm[2]) / 2
        cy = (bbox_norm[1] + bbox_norm[3]) / 2
    else:
        # Assume (cx, cy, w, h)
        cx, cy, _, _ = bbox_norm
        
    return is_point_in_roi(cx, cy, roi)

def save_node_roi(node_key: str, roi_list: Optional[List[float]]):
    """Save ROI to memory and the primary 'cameras' table."""
    from ...core.database import get_db_conn
    
    set_worker_roi(node_key, roi_list)

def get_node_roi(node_key: str) -> Optional[List[float]]:
    """Get active ROI for a node, falling back to DB if needed."""
    state = WORKER_REGISTRY.get(node_key)
    if state and state.get("config") and state["config"].get("roi") is not None:
        return state["config"]["roi"]
    
    # Fallback to DB
    from ...core.database import get_db_conn
    camera_id = node_key.split(":", 1)[1] if ":" in node_key else node_key
    
    roi = None
    with get_db_conn() as db:
        cur = db.cursor()
        cur.execute("SELECT roi FROM cameras WHERE camera_id = ?", (camera_id,))
        row = cur.fetchone()
        if row and row["roi"]:
            roi = json.loads(row["roi"])
    
    # Update local state if found
    if roi is not None:
        if state:
            if "config" not in state:
                state["config"] = {"roi": roi, "face_enabled": True, "obj_enabled": True, "stream_enabled": True}
            else:
                state["config"]["roi"] = roi
        else:
            WORKER_REGISTRY[node_key] = {
                "last_seen": 0.0, 
                "config": {"roi": roi, "face_enabled": True, "obj_enabled": True, "stream_enabled": True}, 
                "location": ""
            }
            
    return roi

def get_all_configs_for_user(username: str) -> dict:
    """Returns all camera configs (ROI + toggles) for a specific user."""
    from ...core.database import get_db_conn
    res = {}
    with get_db_conn() as db:
        cur = db.cursor()
        cur.execute("""
            SELECT camera_id, roi, face_enabled, obj_enabled, stream_enabled 
            FROM cameras WHERE added_by = ?
        """, (username,))
        for row in cur.fetchall():
            res[row["camera_id"]] = {
                "roi": json.loads(row["roi"]) if row["roi"] else None,
                "face_enabled": bool(row["face_enabled"]),
                "obj_enabled": bool(row["obj_enabled"]),
                "stream_enabled": bool(row["stream_enabled"])
            }
    return res
