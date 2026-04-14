from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ...core.database import get_db
from ...core.models import Sighting, Worker, Client, Camera, Watchlist
from ...core.security import get_current_user
from ..workers.router import validate_worker_key
from ...core.face_engine import QDRANT_CLIENT, QDRANT_AVAILABLE
from ...core.sse_manager import broadcast_alert, SSE_CONNECTIONS
from qdrant_client.models import PointStruct
from ...core.worker_state import update_worker_heartbeat
import uuid
from datetime import datetime
from typing import List, Optional

router = APIRouter(prefix="/api", tags=["Inference"])

@router.post("/inference/result")
async def inference_result(
    payload: dict,
    auth: tuple = Depends(validate_worker_key),
    db: AsyncSession = Depends(get_db),
    request: Request = None # To get authorization header if needed
):
    client_id, _ = auth
    
    # Register heartbeat
    camera_id = payload.get("camera_id") # UUID or alias
    worker_id = payload.get("worker_id")
    # For now, we use the camera_id as the node_key in the registry
    update_worker_heartbeat(camera_id, client_id=str(client_id))
    # We need the API key for the media token. 
    # It's in the Authorization header.
    auth_header = request.headers.get("Authorization", "")
    api_key = auth_header.split(" ")[1] if " " in auth_header else ""

    worker_id = payload.get("worker_id")
    camera_id = payload.get("camera_id") # This should now be the UUID
    dtype = payload.get("type")
    label = payload.get("label")
    confidence = payload.get("confidence")
    bbox = payload.get("bbox")
    snapshot_path = payload.get("snapshot_path")
    timestamp = payload.get("timestamp")

    # 1. Store sighting in DB
    s_uuid = str(uuid.uuid4())
    new_sighting = Sighting(
        id=s_uuid,
        camera_id=camera_id,
        location="Unknown",
        timestamp=timestamp,
        snapshot_path=snapshot_path,
        matched=(dtype == "face" and label not in ["person", "Unknown"]),
        person_name=label,
        confidence=confidence,
        client_id=client_id,
        worker_id=uuid.UUID(worker_id) if worker_id else None
    )
    db.add(new_sighting)
    await db.commit()

    # 2. Get worker info
    worker_res = await db.execute(select(Worker).where(Worker.id == uuid.UUID(worker_id)))
    worker = worker_res.scalar_one_or_none()
    
    snapshot_url = None
    if worker and worker.media_base_url:
        # Append token for media server access
        snapshot_url = f"{worker.media_base_url}/snapshots/{snapshot_path}?token={api_key}"

    alert_data = {
        "event": "detection",
        "data": {
            "type": dtype,
            "label": label,
            "confidence": confidence,
            "camera_name": camera_id, # Frontend should resolve name from ID
            "timestamp": timestamp,
            "snapshot_url": snapshot_url
        }
    }
    
    # Broadcast
    if str(client_id) in SSE_CONNECTIONS:
        for q in SSE_CONNECTIONS[str(client_id)]:
             try: await q.put(alert_data)
             except: pass

    return {"received": True}

@router.post("/qdrant/search")
async def qdrant_search(
    payload: dict,
    auth: tuple = Depends(validate_worker_key),
    db: AsyncSession = Depends(get_db)
):
    client_id, _ = auth
    embedding = payload.get("embedding")
    threshold = payload.get("threshold", 0.6)

    if not QDRANT_AVAILABLE or not QDRANT_CLIENT:
        return {"matched": False}

    client_res = await db.execute(select(Client).where(Client.id == client_id))
    client = client_res.scalar_one_or_none()
    if not client or not client.qdrant_collection:
        return {"matched": False}

    try:
        results = QDRANT_CLIENT.search(
            collection_name=client.qdrant_collection,
            query_vector=embedding,
            limit=1
        )
        if results and results[0].score >= threshold:
            return {
                "matched": True,
                "person_name": results[0].payload.get("name", "Unknown"),
                "confidence": results[0].score
            }
    except Exception:
        pass

    return {"matched": False}

@router.post("/qdrant/upsert")
async def qdrant_upsert(
    payload: dict,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if user["role"] != "client" or not user.get("client_id"):
         raise HTTPException(status_code=403, detail="Forbidden")
    
    client_id = user["client_id"]
    person_name = payload.get("person_name")
    embedding = payload.get("embedding")

    client_res = await db.execute(select(Client).where(Client.id == client_id))
    client = client_res.scalar_one_or_none()
    
    if QDRANT_AVAILABLE and QDRANT_CLIENT and client.qdrant_collection:
        vector_id = str(uuid.uuid1())
        QDRANT_CLIENT.upsert(
            collection_name=client.qdrant_collection,
            points=[PointStruct(
                id=vector_id,
                vector=embedding,
                payload={"name": person_name}
            )]
        )
        return {"vector_id": vector_id}
    
    raise HTTPException(status_code=500, detail="Qdrant unavailable")

@router.delete("/qdrant/vectors/{vector_id}")
async def qdrant_delete(
    vector_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if user["role"] != "client" or not user.get("client_id"):
         raise HTTPException(status_code=403, detail="Forbidden")
    
    client_id = user["client_id"]
    client_res = await db.execute(select(Client).where(Client.id == client_id))
    client = client_res.scalar_one_or_none()
    
    if QDRANT_AVAILABLE and QDRANT_CLIENT and client.qdrant_collection:
        QDRANT_CLIENT.delete(
            collection_name=client.qdrant_collection,
            points_selector=[vector_id]
        )
        return {"ok": True}
    
    raise HTTPException(status_code=500, detail="Qdrant unavailable")
