import time
import asyncio
from collections import deque

# { camera_id: { "frame": bytes, "timestamp": float } }
LIVE_FRAMES = {}

# { camera_id: deque(maxlen=100) } - Buffer for H.264 packets
LIVE_PACKETS = {}

# { camera_id: list(asyncio.Queue) } - Active listeners for H.264
PACKET_LISTENERS = {}

def update_live_frame(camera_id, frame_bytes):
    """Store the latest raw frame for a camera (Legacy MJPEG fallback)."""
    LIVE_FRAMES[camera_id] = {
        "frame": frame_bytes,
        "timestamp": time.time()
    }

def get_live_frame(camera_id):
    """Retrieve the latest frame for a camera if not stale."""
    state = LIVE_FRAMES.get(camera_id)
    if not state:
        for k, v in LIVE_FRAMES.items():
            if k.endswith(f":{camera_id}"):
                state = v
                break
                
    if state and (time.time() - state["timestamp"]) < 3.0:
        return state["frame"]
    return None

def update_live_packets(camera_id, packet_bytes):
    """Store H.264 packets and broadcast to all listeners."""
    if camera_id not in LIVE_PACKETS:
        LIVE_PACKETS[camera_id] = deque(maxlen=200)
    
    LIVE_PACKETS[camera_id].append(packet_bytes)
    
    # Broadcast to active workers
    if camera_id in PACKET_LISTENERS:
        for q in PACKET_LISTENERS[camera_id]:
            try:
                q.put_nowait(packet_bytes)
            except asyncio.QueueFull:
                pass

async def subscribe_packets(camera_id):
    """Create a queue for a new client listener."""
    q = asyncio.Queue(maxsize=100)
    
    # Send existing buffer for faster startup
    if camera_id in LIVE_PACKETS:
        for p in LIVE_PACKETS[camera_id]:
            q.put_nowait(p)
            
    if camera_id not in PACKET_LISTENERS:
        PACKET_LISTENERS[camera_id] = []
    
    PACKET_LISTENERS[camera_id].append(q)
    try:
        while True:
            yield await q.get()
    finally:
        if camera_id in PACKET_LISTENERS and q in PACKET_LISTENERS[camera_id]:
            PACKET_LISTENERS[camera_id].remove(q)
