import time
import json

# { node_key: { "last_seen": float, "roi": [x1, y1, x2, y2] | None, "location": str } }
# x1, y1, x2, y2 are normalized coordinates (0.0 to 1.0)
WORKER_REGISTRY: dict[str, dict] = {}

# Heartbeat timeout — node considered offline after this many seconds
HEARTBEAT_TIMEOUT = 60


def update_worker_heartbeat(node_key: str):
    """
    Register or refresh a worker node heartbeat.
    On first registration, loads persisted ROI and detailed configuration from DB.
    """
    from .database import get_db_conn

    if node_key not in WORKER_REGISTRY or WORKER_REGISTRY[node_key].get("config") is None:
        cfg = {"roi": None, "face_enabled": True, "obj_enabled": True, "stream_enabled": True}
        location = "Unknown Location"
        with get_db_conn() as db:
            cur = db.cursor()
            camera_id = node_key.split(":", 1)[1] if ":" in node_key else node_key
            cur.execute("""
                SELECT roi, location, face_enabled, obj_enabled, stream_enabled 
                FROM cameras WHERE camera_id = ?
            """, (camera_id,))
            res = cur.fetchone()
            if res:
                cfg["roi"] = json.loads(res["roi"]) if res["roi"] else None
                cfg["face_enabled"] = bool(res["face_enabled"])
                cfg["obj_enabled"] = bool(res["obj_enabled"])
                cfg["stream_enabled"] = bool(res["stream_enabled"])
                location = res["location"] or location

        if node_key not in WORKER_REGISTRY:
            WORKER_REGISTRY[node_key] = {
                "last_seen": 0.0,
                "config": cfg,
                "location": location,
            }
        else:
            WORKER_REGISTRY[node_key]["config"] = cfg
            if not WORKER_REGISTRY[node_key].get("location"):
                WORKER_REGISTRY[node_key]["location"] = location

    WORKER_REGISTRY[node_key]["last_seen"] = time.time()


def remove_worker(node_key: str):
    WORKER_REGISTRY.pop(node_key, None)


def set_worker_roi(node_key: str, roi: list | None):
    """
    Save ROI to memory and persist to DB.
    roi = [x1, y1, x2, y2] in normalized (0.0-1.0) coordinates, or None to clear.
    """
    from .database import get_db_conn

    if node_key not in WORKER_REGISTRY:
        WORKER_REGISTRY[node_key] = {
            "last_seen": 0.0, 
            "config": {"roi": None, "face_enabled": True, "obj_enabled": True, "stream_enabled": True}, 
            "location": ""
        }

    camera_id = node_key.split(":", 1)[1] if ":" in node_key else node_key
    if WORKER_REGISTRY[node_key].get("config") is None:
        WORKER_REGISTRY[node_key]["config"] = {"roi": roi, "face_enabled": True, "obj_enabled": True, "stream_enabled": True}
    else:
        WORKER_REGISTRY[node_key]["config"]["roi"] = roi
    
    roi_str = json.dumps(roi) if roi is not None else None

    with get_db_conn() as db:
        db.execute(
            "UPDATE cameras SET roi = ? WHERE camera_id = ?",
            (roi_str, camera_id),
        )


def get_config(node_key: str) -> dict | None:
    state = WORKER_REGISTRY.get(node_key)
    return state.get("config") if state else None


def get_live_nodes() -> list[dict]:
    """Return nodes that checked in within HEARTBEAT_TIMEOUT seconds."""
    now = time.time()
    live = []
    stale_keys = []

    for node_key, state in WORKER_REGISTRY.items():
        age = now - state["last_seen"]
        if age < HEARTBEAT_TIMEOUT:
            user, cam_id = (node_key.split(":", 1) if ":" in node_key else ("unknown", node_key))
            live.append({
                "id":        node_key,
                "camera_id": cam_id,
                "user":      user,
                "last_seen": state["last_seen"],
                "roi":       state.get("config", {}).get("roi"),
                "location":  state.get("location", ""),
                "age_s":     round(age, 1),
            })
        else:
            stale_keys.append(node_key)

    for k in stale_keys:
        WORKER_REGISTRY.pop(k, None)

    return live
