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
    On first registration, loads persisted ROI and location from DB.
    """
    from .database import get_db_conn

    if node_key not in WORKER_REGISTRY:
        roi = None
        location = "Unknown Location"
        with get_db_conn() as db:
            cur = db.cursor()
            cur.execute("SELECT roi, location FROM camera_configs WHERE id = ?", (node_key,))
            res = cur.fetchone()
            if res:
                roi = json.loads(res["roi"]) if res["roi"] else None
                location = res["location"] or location

            camera_id = node_key.split(":", 1)[1] if ":" in node_key else node_key
            cur.execute("SELECT location FROM cameras WHERE camera_id = ?", (camera_id,))
            cam = cur.fetchone()
            if cam and cam["location"]:
                location = cam["location"]

        WORKER_REGISTRY[node_key] = {
            "last_seen": 0.0,
            "roi": roi,
            "location": location,
        }

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
        WORKER_REGISTRY[node_key] = {"last_seen": 0.0, "roi": None, "location": ""}

    WORKER_REGISTRY[node_key]["roi"] = roi
    roi_str = json.dumps(roi) if roi is not None else None

    with get_db_conn() as db:
        db.execute(
            "INSERT OR REPLACE INTO camera_configs (id, roi) VALUES (?, ?)",
            (node_key, roi_str),
        )


def get_roi(node_key: str) -> list | None:
    state = WORKER_REGISTRY.get(node_key)
    return state["roi"] if state else None


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
                "roi":       state["roi"],
                "location":  state.get("location", ""),
                "age_s":     round(age, 1),
            })
        else:
            stale_keys.append(node_key)

    for k in stale_keys:
        WORKER_REGISTRY.pop(k, None)

    return live
