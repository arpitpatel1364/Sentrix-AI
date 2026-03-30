from fastapi import APIRouter, Depends, Request
import asyncio
import json
from sse_starlette.sse import EventSourceResponse
from ...core.security import require_admin
from ...core.sse_manager import SSE_CONNECTIONS

router = APIRouter(prefix="/api")

@router.get("/stream")
async def sse_stream(request: Request, user=Depends(require_admin)):
    queue = asyncio.Queue()
    if user["username"] not in SSE_CONNECTIONS:
        SSE_CONNECTIONS[user["username"]] = []
    SSE_CONNECTIONS[user["username"]].append(queue)

    async def generator():
        yield {"event": "connected", "data": json.dumps({"user": user["username"]})}
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {"event": "alert", "data": json.dumps(payload)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            if user["username"] in SSE_CONNECTIONS:
                if queue in SSE_CONNECTIONS[user["username"]]:
                    SSE_CONNECTIONS[user["username"]].remove(queue)
                if not SSE_CONNECTIONS[user["username"]]:
                    SSE_CONNECTIONS.pop(user["username"])

    return EventSourceResponse(generator())
