import time
import json

# { node_key: { "last_seen": float, "roi": [x1, y1, x2, y2] | None, "location": str } }
# x1, y1, x2, y2 are normalized coordinates (0.0 to 1.0)
WORKER_REGISTRY: dict[str, dict] = {}

# Heartbeat timeout — node considered offline after this many seconds
HEARTBEAT_TIMEOUT = 60


def update_worker_heartbeat(node_key: str, client_id: str = None):
    """
    Register or refresh a worker node heartbeat in memory.
    On first registration, we use default configs. Multi-tenant configs are loaded 
    via the workers/router or camera handlers.
    """
    if node_key not in WORKER_REGISTRY or WORKER_REGISTRY[node_key].get("config") is None:
        cfg = {"roi": None, "face_enabled": True, "obj_enabled": True, "stream_enabled": True}
        location = "Remote Worker"
        
        if node_key not in WORKER_REGISTRY:
            WORKER_REGISTRY[node_key] = {
                "last_seen": 0.0,
                "config": cfg,
                "location": location,
                "client_id": client_id,
            }
        else:
            WORKER_REGISTRY[node_key]["config"] = cfg
            if client_id:
                WORKER_REGISTRY[node_key]["client_id"] = client_id
            if not WORKER_REGISTRY[node_key].get("location"):
                WORKER_REGISTRY[node_key]["location"] = location
    else:
        if client_id:
            WORKER_REGISTRY[node_key]["client_id"] = client_id

    WORKER_REGISTRY[node_key]["last_seen"] = time.time()


def remove_worker(node_key: str):
    WORKER_REGISTRY.pop(node_key, None)


def set_worker_roi(node_key: str, roi: list | None):
    """
    Save ROI to memory. 
    DB persistence for ROI is now handled by the ROI table and dedicated models.
    """
    if node_key not in WORKER_REGISTRY:
        WORKER_REGISTRY[node_key] = {
            "last_seen": 0.0, 
            "config": {"roi": None, "face_enabled": True, "obj_enabled": True, "stream_enabled": True}, 
            "location": "",
            "client_id": None
        }

    if WORKER_REGISTRY[node_key].get("config") is None:
        WORKER_REGISTRY[node_key]["config"] = {"roi": roi, "face_enabled": True, "obj_enabled": True, "stream_enabled": True}
    else:
        WORKER_REGISTRY[node_key]["config"]["roi"] = roi


def get_config(node_key: str) -> dict | None:
    state = WORKER_REGISTRY.get(node_key)
    return state.get("config") if state else None


def get_live_nodes(client_id: str = None) -> list[dict]:
    """Return nodes that checked in within HEARTBEAT_TIMEOUT seconds."""
    now = time.time()
    live = []
    stale_keys = []

    for node_key, state in WORKER_REGISTRY.items():
        # Filtering for multi-tenancy
        if client_id and state.get("client_id") != client_id:
            continue

        age = now - state["last_seen"]
        if age < HEARTBEAT_TIMEOUT:
            # We no longer assume 'username:camera_id' format strictly,
            # but we can try to extract camera_id if it's there.
            cam_id = node_key.split(":", 1)[1] if ":" in node_key else node_key
            user   = node_key.split(":", 1)[0] if ":" in node_key else "system"
            
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


def update_worker_config(camera_id: str, updates: dict):
    """Update configurations (face/obj/stream toggles) in memory."""
    # Memory update for all nodes matching this camera_id
    for node_key, state in WORKER_REGISTRY.items():
        if node_key.endswith(f":{camera_id}") or node_key == camera_id:
            if "config" not in state:
                state["config"] = {"roi": None, "face_enabled": True, "obj_enabled": True, "stream_enabled": True}
            for k, v in updates.items():
                if k in ("face_enabled", "obj_enabled", "stream_enabled"):
                    state["config"][k] = bool(v)

