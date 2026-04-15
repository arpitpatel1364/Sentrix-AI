from fastapi import APIRouter, Depends, HTTPException, Header, Request, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ...core.database import get_db
from ...core.models import Worker, WorkerKey, Client, Camera
from ...core.dependencies import get_current_user, require_admin
import uuid
import bcrypt
from datetime import datetime
from typing import List, Optional
from ...core.worker_state import update_worker_heartbeat

router = APIRouter(prefix="/workers", tags=["Workers"])

async def get_client_by_api_key(api_key: str, db: AsyncSession):
    # Performance fix: We should ideally have a key prefix or a fast lookup table.
    # For now, we still iterate but we can make it more explicit.
    result = await db.execute(select(WorkerKey))
    keys = result.scalars().all()
    for wk in keys:
        try:
            if bcrypt.checkpw(api_key.encode(), wk.api_key_hash.encode()):
                return wk.client_id, wk.id
        except Exception:
            continue
    return None, None

async def validate_worker_key(authorization: str = Header(...), db: AsyncSession = Depends(get_db)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    api_key = authorization.split(" ")[1]
    client_id, worker_key_id = await get_client_by_api_key(api_key, db)
    if not client_id:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return client_id, worker_key_id

@router.post("/register")
async def register_worker(
    payload: dict,
    auth: tuple = Depends(validate_worker_key),
    db: AsyncSession = Depends(get_db)
):
    client_id, worker_key_id = auth
    label = payload.get("label", "Unknown Worker")
    media_base_url = payload.get("media_base_url")
    cameras_data = payload.get("cameras", [])

    # 1. Get Client
    client_res = await db.execute(select(Client).where(Client.id == client_id))
    client = client_res.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # 2. Create or Update Worker
    # Check if worker with this label already exists for this client
    exist_worker_res = await db.execute(
        select(Worker).where(Worker.client_id == client_id).where(Worker.label == label)
    )
    worker = exist_worker_res.scalar_one_or_none()
    
    if worker:
        worker.media_base_url = media_base_url
        worker.status = "online"
        worker.last_seen = datetime.utcnow()
        worker_id = worker.id
    else:
        worker_id = uuid.uuid4()
        worker = Worker(
            id=worker_id,
            client_id=client_id,
            worker_key_id=worker_key_id,
            label=label,
            media_base_url=media_base_url,
            status="online",
            last_seen=datetime.utcnow()
        )
        db.add(worker)
    
    # 3. Create or Update Cameras
    camera_mapping = {}
    for cam in cameras_data:
        cam_name = cam.get("name", "Camera")
        # Check if camera exists for this worker
        exist_cam_res = await db.execute(
            select(Camera).where(Camera.worker_id == worker_id).where(Camera.name == cam_name)
        )
        camera = exist_cam_res.scalar_one_or_none()
        
        if camera:
            camera.stream_url = cam.get("rtsp_url", "")
            camera.status = "online"
        else:
            cam_uuid = str(uuid.uuid4())
            camera = Camera(
                id=cam_uuid,
                camera_id=f"cam_{cam_uuid[:8]}", # Unique camera ID
                name=cam_name,
                stream_url=cam.get("rtsp_url", ""),
                client_id=client_id,
                worker_id=worker_id,
                status="online"
            )
            db.add(camera)
        
        camera_mapping[cam_name] = camera.camera_id
    
    await db.commit()
    
    # Update memory registry
    for cam_name, cam_uuid in camera_mapping.items():
        update_worker_heartbeat(cam_uuid, client_id=str(client_id))
    
    return {
        "worker_id": str(worker_id),
        "qdrant_collection": client.qdrant_collection,
        "camera_mapping": camera_mapping
    }

@router.post("/{worker_id}/heartbeat")
async def worker_heartbeat(
    worker_id: uuid.UUID,
    payload: dict,
    auth: tuple = Depends(validate_worker_key),
    db: AsyncSession = Depends(get_db)
):
    client_id, _ = auth
    
    # Update worker status
    await db.execute(
        update(Worker)
        .where(Worker.id == worker_id)
        .where(Worker.client_id == client_id)
        .values(status="online", last_seen=datetime.utcnow())
    )
    
    # Update camera statuses
    camera_statuses = payload.get("camera_statuses", {})
    for cam_name, status in camera_statuses.items():
        await db.execute(
            update(Camera)
            .where(Camera.worker_id == worker_id)
            .where(Camera.name == cam_name)
            .values(status=status)
        )
    
    await db.commit()

    # Update memory registry
    for cam_name, status in camera_statuses.items():
        # Need to find camera_id for this name and worker
        cam_res = await db.execute(
            select(Camera.camera_id).where(Camera.worker_id == worker_id).where(Camera.name == cam_name)
        )
        cam_uuid = cam_res.scalar()
        if cam_uuid:
            update_worker_heartbeat(cam_uuid, client_id=str(client_id))

    return {"ok": True}

@router.get("/mine")
async def list_my_workers(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if user.role != "client" or not user.client_id:
        raise HTTPException(status_code=403, detail="Only clients can access this")
    
    client_id = user.client_id
    result = await db.execute(select(Worker).where(Worker.client_id == client_id))
    workers = result.scalars().all()
    
    output = []
    for w in workers:
        # Count cameras
        cam_res = await db.execute(select(Camera).where(Camera.worker_id == w.id))
        cam_count = len(cam_res.scalars().all())
        output.append({
            "worker_id": str(w.id),
            "label": w.label,
            "status": w.status,
            "last_seen": w.last_seen,
            "camera_count": cam_count
        })
    return output

@router.get("/")
async def list_all_workers(
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Worker, Client.name).join(Client, Worker.client_id == Client.id))
    rows = result.all()
    
    output = []
    for w, client_name in rows:
        cam_res = await db.execute(select(Camera).where(Camera.worker_id == w.id))
        cam_count = len(cam_res.scalars().all())
        output.append({
            "worker_id": str(w.id),
            "label": w.label,
            "client_name": client_name,
            "status": w.status,
            "last_seen": w.last_seen,
            "camera_count": cam_count
        })
    return output
