import time

# { node_key: { "last_seen": float, "roi": [x1, y1, x2, y2] | None } }
# x1, y1, x2, y2 are normalized coordinates (0.0 to 1.0)
WORKER_REGISTRY: dict[str, dict] = {}

def update_worker_heartbeat(node_key: str):
    from .database import get_db_conn
    import json
    
    if node_key not in WORKER_REGISTRY:
        with get_db_conn() as db:
            cur = db.cursor()
            cur.execute("SELECT roi FROM camera_configs WHERE id = ?", (node_key,))
            res = cur.fetchone()
            roi = json.loads(res[0]) if res and res[0] else None
            WORKER_REGISTRY[node_key] = {"last_seen": 0.0, "roi": roi}
            
    WORKER_REGISTRY[node_key]["last_seen"] = time.time()

def remove_worker(node_key: str):
    if node_key in WORKER_REGISTRY:
        del WORKER_REGISTRY[node_key]

def set_worker_roi(node_key: str, roi: list[float] | None):
    from .database import get_db_conn
    import json
    
    if node_key not in WORKER_REGISTRY:
        WORKER_REGISTRY[node_key] = {"last_seen": 0.0, "roi": None}
    WORKER_REGISTRY[node_key]["roi"] = roi
    
    # Persist to DB
    roi_str = json.dumps(roi) if roi else None
    with get_db_conn() as db:
        db.execute("INSERT OR REPLACE INTO camera_configs (id, roi) VALUES (?, ?)", (node_key, roi_str))

def get_live_nodes():
    now = time.time()
    live_nodes = []
    # Filter only those that checked in within the last 60 seconds
    for node_key, state in list(WORKER_REGISTRY.items()):
        if now - state["last_seen"] < 60:
            user = "unknown"
            node_id = node_key
            if ":" in node_key:
                user, node_id = node_key.split(":", 1)
            live_nodes.append({
                "id": node_key, 
                "camera_id": node_id,
                "user": user,
                "last_seen": state["last_seen"],
                "roi": state["roi"]
            })
        else:
            WORKER_REGISTRY.pop(node_key, None)
    return live_nodes
