import asyncio
import json
from typing import List, Dict

# active SSE connections: { username: [ {"queue": asyncio.Queue, "admin_id": int}, ... ] }
SSE_CONNECTIONS: dict[str, List[dict]] = {}

# System-level alert types that the Master Admin (admin_id 0) should always see
SYSTEM_ALERT_TYPES = {
    "camera_offline", 
    "camera_online", 
    "stop_request", 
    "stop_approved", 
    "system_health",
    "maintenance_notice"
}

async def broadcast_alert(payload: dict):
    target_admin_id = payload.get("admin_id")
    alert_type = payload.get("type")
    
    for username, active_sessions in SSE_CONNECTIONS.items():
        for session in active_sessions:
            try:
                user_admin_id = session.get("admin_id")
                
                # Logic:
                # 1. If it's the target tenant, send it.
                # 2. If it's a Super Admin (0), only send it if it's a SYSTEM level alert.
                # 3. If target_admin_id is None, it's a global system alert, send to everyone.
                
                is_target = (target_admin_id is not None and user_admin_id == target_admin_id)
                is_master = (user_admin_id == 0)
                is_system = (alert_type in SYSTEM_ALERT_TYPES or target_admin_id is None)
                
                # Super Admin (0) sees EVERYTHING across all tenants
                if is_target or is_master or is_system:
                    await session["queue"].put(payload)
                    
            except Exception as e:
                print(f"SSE Broadcast error for {username}: {e}")
