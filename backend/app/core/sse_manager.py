import asyncio
import json
from typing import List, Dict

# active SSE connections: { username: [asyncio.Queue, ...] }
SSE_CONNECTIONS: dict[str, List[asyncio.Queue]] = {}

async def broadcast_alert(payload: dict):
    for queues in SSE_CONNECTIONS.values():
        for q in queues:
            try:
                await q.put(payload)
            except Exception:
                pass
