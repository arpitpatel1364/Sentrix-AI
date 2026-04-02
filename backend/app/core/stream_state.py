import time

# { camera_id: { "frame": bytes, "timestamp": float } }
LIVE_FRAMES = {}

def update_live_frame(camera_id, frame_bytes):
    """Store the latest raw frame for a camera."""
    LIVE_FRAMES[camera_id] = {
        "frame": frame_bytes,
        "timestamp": time.time()
    }

def get_live_frame(camera_id):
    """Retrieve the latest frame for a camera if not stale."""
    # Try exact match (node_key)
    state = LIVE_FRAMES.get(camera_id)
    
    # Fallback to suffix match (base camera_id)
    if not state:
        for k, v in LIVE_FRAMES.items():
            if k.endswith(f":{camera_id}"):
                state = v
                break
                
    if state and (time.time() - state["timestamp"]) < 3.0: # 3 second timeout for staleness
        return state["frame"]
    return None
