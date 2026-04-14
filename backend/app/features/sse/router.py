from fastapi import APIRouter, Depends, Request
import asyncio
import json
from sse_starlette.sse import EventSourceResponse
from ...core.security import get_current_user
from ...core.sse_manager import add_connection, remove_connection
import uuid

router = APIRouter(prefix="/api/sse")

@router.get("/events")
async def sse_events(request: Request, user=Depends(get_current_user)):
    """
    SSE connection opened by client dashboard or admin dashboard.
    """
    queue = asyncio.Queue()
    
    # Target is either "admin" or the client_id string
    target = "admin" if user["role"] == "admin" else str(user.get("client_id"))
    
    await add_connection(target, queue)

    async def generator():
        yield {"event": "connected", "data": json.dumps({"role": user["role"], "client_id": str(user.get("client_id"))})}
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {"event": payload.get("event", "detection"), "data": json.dumps(payload.get("data", payload))}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            await remove_connection(target, queue)

    return EventSourceResponse(generator())
