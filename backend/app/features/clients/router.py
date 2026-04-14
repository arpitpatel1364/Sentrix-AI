import uuid
import secrets
import bcrypt
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, distinct

from ...core.database import get_db
from ...core.dependencies import require_admin
from ...core.models import Client, User, WorkerKey, Worker, Camera, Sighting
from ...core.face_engine import QDRANT_CLIENT, QDRANT_AVAILABLE
from ..audit_log.router import write_log

router = APIRouter(prefix="/admin/clients")

@router.get("/")
async def list_clients(
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns a list of all clients with metadata.
    NEVER includes image URLs or visual data.
    """
    # Subqueries for counts
    camera_counts = (
        select(Camera.client_id, func.count(Camera.id).label("count"))
        .group_by(Camera.client_id)
        .subquery()
    )
    worker_counts = (
        select(Worker.client_id, func.count(Worker.id).label("count"))
        .group_by(Worker.client_id)
        .subquery()
    )

    query = (
        select(
            Client,
            func.coalesce(camera_counts.c.count, 0).label("camera_count"),
            func.coalesce(worker_counts.c.count, 0).label("worker_count")
        )
        .outerjoin(camera_counts, Client.id == camera_counts.c.client_id)
        .outerjoin(worker_counts, Client.id == worker_counts.c.client_id)
    )

    result = await db.execute(query)
    rows = result.all()

    output = []
    for client, cam_count, work_count in rows:
        output.append({
            "id": str(client.id),
            "name": client.name,
            "status": client.status,
            "permissions": client.permissions,
            "camera_count": cam_count,
            "worker_count": work_count,
            "created_at": client.created_at.isoformat() if client.created_at else None
        })
    
    return output

@router.post("/")
async def create_client(
    request: Request,
    body: dict,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Provision new client + user + worker_key + qdrant_collection.
    Returns credentials (once only).
    """
    client_name = body.get("client_name")
    perms = body.get("permissions", {})
    if not client_name:
        raise HTTPException(status_code=400, detail="client_name required")

    # 1. Create Client
    client_id = uuid.uuid4()
    qdrant_collection = f"client_{str(client_id)}_faces"
    new_client = Client(
        id=client_id,
        name=client_name,
        permissions=perms,
        qdrant_collection=qdrant_collection,
        status="active"
    )
    db.add(new_client)

    # 2. Create User
    email = f"{client_name.lower().replace(' ', '_')}@sentrix.ai"
    password = secrets.token_urlsafe(12)
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    new_user = User(
        username=email,
        password_hash=password_hash,
        role="client",
        client_id=client_id
    )
    db.add(new_user)

    # 3. Create Default Worker Key
    api_key = secrets.token_urlsafe(36)
    api_key_hash = bcrypt.hashpw(api_key.encode(), bcrypt.gensalt()).decode()

    new_worker_key = WorkerKey(
        client_id=client_id,
        api_key_hash=api_key_hash,
        label="Default Worker"
    )
    db.add(new_worker_key)

    # 4. Create Qdrant Collection
    if QDRANT_AVAILABLE and QDRANT_CLIENT:
        from qdrant_client.models import Distance, VectorParams
        try:
            QDRANT_CLIENT.create_collection(
                collection_name=qdrant_collection,
                vectors_config=VectorParams(size=512, distance=Distance.COSINE)
            )
        except Exception:
            pass

    await db.commit()
    await write_log(db, username=_admin.username, role=_admin.role, action="create_client", target=client_name, detail=f"Provisioned new client {client_name}", ip=request.client.host)

    return {
        "client_id": str(client_id),
        "email": email,
        "password": password,
        "client_api_key": api_key,
        "qdrant_collection": qdrant_collection
    }

@router.get("/{client_id}")
async def get_client_detail(
    client_id: uuid.UUID,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns detailed client info, workers, cameras, and today's detection count.
    NO thumbnails, NO snapshots, NO stream URLs.
    """
    client_res = await db.execute(select(Client).where(Client.id == client_id))
    client = client_res.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Workers
    worker_res = await db.execute(select(Worker).where(Worker.client_id == client_id))
    workers = worker_res.scalars().all()

    # Cameras
    camera_res = await db.execute(select(Camera).where(Camera.client_id == client_id))
    cameras = camera_res.scalars().all()

    # Detection count today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    count_res = await db.execute(
        select(func.count(Sighting.id))
        .where(Sighting.client_id == client_id)
        .where(Sighting.timestamp >= today_start)
    )
    detection_count = count_res.scalar()

    return {
        "info": {
            "id": str(client.id),
            "name": client.name,
            "status": client.status,
            "permissions": client.permissions,
            "created_at": client.created_at
        },
        "workers": [
            {"label": w.label, "status": w.status, "last_seen": w.last_seen}
            for w in workers
        ],
        "cameras": [
            {"name": c.name, "status": c.status} # NO stream_url
            for c in cameras
        ],
        "detection_count_today": detection_count
    }

@router.patch("/{client_id}")
async def update_client(
    client_id: uuid.UUID,
    body: dict,
    request: Request,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Update status or permissions.
    """
    client_res = await db.execute(select(Client).where(Client.id == client_id))
    client = client_res.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    new_status = body.get("status")
    new_perms = body.get("permissions")

    if new_status:
        client.status = new_status
    if new_perms:
        client.permissions = new_perms

    await db.commit()
    await write_log(db, username=_admin.username, role=_admin.role, action="update_client", target=client.name, detail=f"Updated client metadata/status", ip=request.client.host)
    return {"ok": True}

@router.patch("/{client_id}/permissions")
async def replace_permissions(
    client_id: uuid.UUID,
    body: dict,
    request: Request,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Replaces entire permissions JSON for the client.
    """
    client_res = await db.execute(select(Client).where(Client.id == client_id))
    client = client_res.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    client.permissions = body
    await db.commit()
    await write_log(db, username=_admin.username, role=_admin.role, action="update_permissions", target=client.name, detail=f"Replaced client permissions", ip=request.client.host)
    return {"ok": True}

@router.post("/{client_id}/workers/add-key")
async def add_worker_key(
    client_id: uuid.UUID,
    body: dict,
    request: Request,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Generates new CLIENT_API_KEY for an additional worker.
    Returns plaintext key once.
    """
    label = body.get("label", "Additional Worker")
    
    api_key = secrets.token_urlsafe(36)
    api_key_hash = bcrypt.hashpw(api_key.encode(), bcrypt.gensalt()).decode()

    new_wk = WorkerKey(
        client_id=client_id,
        api_key_hash=api_key_hash,
        label=label
    )
    db.add(new_wk)
    await db.commit()

    await write_log(db, username=_admin.username, role=_admin.role, action="add_worker_key", target=str(client_id), detail=f"Added worker key: {label}", ip=request.client.host)
    return {"client_api_key": api_key}

@router.delete("/{client_id}")
async def delete_client(
    client_id: uuid.UUID,
    request: Request,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Soft delete: set status = "suspended".
    Also delete client's Qdrant collection.
    """
    client_res = await db.execute(select(Client).where(Client.id == client_id))
    client = client_res.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    client.status = "suspended"

    # Delete Qdrant collection
    if QDRANT_AVAILABLE and QDRANT_CLIENT and client.qdrant_collection:
        try:
            QDRANT_CLIENT.delete_collection(client.qdrant_collection)
        except Exception:
            pass

    await db.commit()
    await write_log(db, username=_admin.username, role=_admin.role, action="suspend_client", target=client.name, detail="Client suspended and Qdrant collection deleted", ip=request.client.host)
    return {"ok": True}
