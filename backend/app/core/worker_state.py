import time

# { camera_id: last_seen_timestamp }
# camera_id is usually username:camera_id
ACTIVE_WORKERS: dict[str, float] = {}

def update_worker_heartbeat(node_key: str):
    ACTIVE_WORKERS[node_key] = time.time()

def get_live_nodes():
    now = time.time()
    live_nodes = []
    # Filter only those that checked in within the last 60 seconds
    for node_key, last_seen in list(ACTIVE_WORKERS.items()):
        if now - last_seen < 60:
            live_nodes.append(node_key)
        else:
            ACTIVE_WORKERS.pop(node_key, None)
    return live_nodes
