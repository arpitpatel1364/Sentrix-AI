import asyncio
import json
from typing import List, Dict, Optional
import uuid

# active SSE connections: { client_id_or_admin: [asyncio.Queue, ...] }
SSE_CONNECTIONS: dict[str, List[asyncio.Queue]] = {}

async def broadcast_alert(payload: dict, client_id: Optional[uuid.UUID] = None):
    """
    Broadcast to a specific client OR all admins if client_id is None.
    If client_id is provided, also broadcast to all admins.
    """
    targets = ["admin"]
    if client_id:
        targets.append(str(client_id))
    
    for target in targets:
        if target in SSE_CONNECTIONS:
            for q in SSE_CONNECTIONS[target]:
                try:
                    await q.put(payload)
                except Exception:
                    pass

async def add_connection(target: str, queue: asyncio.Queue):
    if target not in SSE_CONNECTIONS:
        SSE_CONNECTIONS[target] = []
    SSE_CONNECTIONS[target].append(queue)

async def remove_connection(target: str, queue: asyncio.Queue):
    if target in SSE_CONNECTIONS:
        if queue in SSE_CONNECTIONS[target]:
            SSE_CONNECTIONS[target].remove(queue)
        if not SSE_CONNECTIONS[target]:
            del SSE_CONNECTIONS[target]
