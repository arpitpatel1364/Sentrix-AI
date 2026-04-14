import uuid
import cv2
import numpy as np
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, and_

from ...core.dependencies import get_current_user, require_admin
from ...core.database import get_db
from ...core.models import Watchlist, PersonPhoto, Client
from ..audit_log.router import write_log
from ...core.face_engine import (
    get_embedding, bytes_to_cv2, QDRANT_AVAILABLE
)
from ...core import face_engine
from ...core.config import INTEL_DIR
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue

router = APIRouter(prefix="/watchlist")

@router.get("/")
async def get_wanted(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """
    List watchlist subjects. Clients see only their own.
    """
    # Using subquery for counts
    photo_counts = (
        select(PersonPhoto.person_id, func.count(PersonPhoto.id).label("count"))
        .group_by(PersonPhoto.person_id)
        .subquery()
    )
    
    query = (
        select(Watchlist, func.coalesce(photo_counts.c.count, 0))
        .outerjoin(photo_counts, Watchlist.id == photo_counts.c.person_id)
        .order_by(Watchlist.added_at.desc())
    )
    
    if user.role == "client":
        query = query.where(Watchlist.client_id == user.client_id)
        
    res = await db.execute(query)
    rows = res.all()
    
    output = []
    for w, count in rows:
        # Get primary photo ID
        p_res = await db.execute(
            select(PersonPhoto.id)
            .where(PersonPhoto.person_id == w.id)
            .limit(1)
        )
        primary_photo = p_res.scalar_one_or_none()
        
        output.append({
            "id": w.id,
            "name": w.name,
            "added_by": w.added_by,
            "added_at": w.added_at,
            "photo_count": count,
            "primary_photo": primary_photo
        })
        
    return output

@router.get("/{person_id}/photos")
async def get_person_photos(person_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """
    List photo samples for a specific subject.
    """
    # Security check: Does this person belong to the user's client?
    w_query = select(Watchlist).where(Watchlist.id == person_id)
    if user.role == "client":
        w_query = w_query.where(Watchlist.client_id == user.client_id)
    
    w_res = await db.execute(w_query)
    if not w_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Subject not found or access denied")

    p_res = await db.execute(
        select(PersonPhoto.id, PersonPhoto.added_at)
        .where(PersonPhoto.person_id == person_id)
        .order_by(PersonPhoto.added_at.asc())
    )
    return [{"id": r[0], "added_at": r[1]} for r in p_res.all()]

@router.get("/intel-photos/{photo_id}")
async def get_intel_photo(photo_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Optional security: Check if photo_id belongs to a person in user's client
    # For speed, we might allow it if authenticated, or check DB
    path = INTEL_DIR / f"{photo_id}.jpg"
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path)

@router.post("/")
async def add_wanted(
    files: List[UploadFile] = File(...),
    name: str = Form(...),
    client_id: Optional[str] = Form(None),
    request: Request = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    name_str = name.strip()
    
    # Determine client_id
    target_client_id = user.client_id
    if user.role == "admin":
        if not client_id:
            raise HTTPException(status_code=400, detail="client_id is required for admin to add subjects")
        try:
            target_client_id = uuid.UUID(client_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid client_id format")
    
    if not target_client_id:
        raise HTTPException(status_code=400, detail="client_id required to add to watchlist")

    # Determine collection
    collection_name = "watchlist"
    c_res = await db.execute(select(Client).where(Client.id == target_client_id))
    client = c_res.scalar_one_or_none()
    if client and client.qdrant_collection:
        collection_name = client.qdrant_collection

    pids_processed = []

    for file in files:
        data = await file.read()
        img = bytes_to_cv2(data)
        embedding = get_embedding(img)
        if embedding is None:
            continue

        # Check if person exists for this client
        w_res = await db.execute(
            select(Watchlist).where(and_(Watchlist.name == name_str, Watchlist.client_id == target_client_id))
        )
        w_obj = w_res.scalar_one_or_none()
        
        if w_obj:
            pid = w_obj.id
            count_res = await db.execute(select(func.count(PersonPhoto.id)).where(PersonPhoto.person_id == pid))
            if count_res.scalar() >= 15:
                continue
        else:
            pid = str(uuid.uuid4())
            now = datetime.utcnow().isoformat()
            w_obj = Watchlist(id=pid, name=name_str, added_by=user.username, added_at=now, client_id=target_client_id)
            db.add(w_obj)

        photo_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        photo_path = INTEL_DIR / f"{photo_id}.jpg"
        cv2.imwrite(str(photo_path), img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        
        emb_blob = embedding.astype(np.float32).tobytes()
        new_photo = PersonPhoto(id=photo_id, person_id=pid, embedding=emb_blob, snapshot_path=f"{photo_id}.jpg", added_at=now)
        db.add(new_photo)
        await db.commit()

        if QDRANT_AVAILABLE and face_engine.QDRANT_CLIENT:
            try:
                face_engine.QDRANT_CLIENT.upsert(
                    collection_name=collection_name,
                    points=[PointStruct(
                        id=photo_id,
                        vector=embedding.tolist(),
                        payload={"person_id": pid, "person_name": name_str}
                    )]
                )
            except Exception as e:
                print(f"Qdrant sync error: {e}")
        
        pids_processed.append(photo_id)

    if not pids_processed:
        raise HTTPException(status_code=400, detail="No faces detected in any uploaded files.")

    await write_log(db, username=user.username, role=user.role, action="add_person", target=name_str, detail=f"Added '{name_str}' to client {target_client_id} watchlist", ip=request.client.host if request else "")
    return {"status": "success", "count": len(pids_processed), "name": name_str}

@router.delete("/{person_id}")
async def remove_wanted(person_id: str, request: Request, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """
    Remove subject and all photos.
    """
    w_query = select(Watchlist).where(Watchlist.id == person_id)
    if user.role == "client":
        w_query = w_query.where(Watchlist.client_id == user.client_id)
    
    res = await db.execute(w_query)
    w_obj = res.scalar_one_or_none()
    if not w_obj:
        raise HTTPException(status_code=404, detail="Subject not found or access denied")

    target_client_id = w_obj.client_id
    
    # Files cleanup
    p_res = await db.execute(select(PersonPhoto.id).where(PersonPhoto.person_id == person_id))
    photo_ids = [r[0] for r in p_res.all()]
    for photo_id in photo_ids:
        path = INTEL_DIR / f"{photo_id}.jpg"
        if path.exists():
            try: path.unlink()
            except: pass
    
    # DB cleanup
    await db.execute(delete(PersonPhoto).where(PersonPhoto.person_id == person_id))
    await db.delete(w_obj)
    await db.commit()
    
    await write_log(db, username=user.username, role=user.role, action="delete_person", target=person_id, detail=f"Deleted person ID {person_id}", ip=request.client.host)
    
    # Qdrant cleanup
    if QDRANT_AVAILABLE and face_engine.QDRANT_CLIENT:
        # Determine collection
        collection_name = "watchlist"
        c_res = await db.execute(select(Client).where(Client.id == target_client_id))
        client = c_res.scalar_one_or_none()
        if client and client.qdrant_collection:
            collection_name = client.qdrant_collection
            
        try:
            face_engine.QDRANT_CLIENT.delete(
                collection_name=collection_name,
                points_selector=Filter(
                    must=[FieldCondition(key="person_id", match=MatchValue(value=person_id))]
                )
            )
        except Exception as e:
            print(f"Qdrant purge error: {e}")
        
    return {"ok": True}

@router.delete("/{person_id}/photos/{photo_id}")
async def delete_intel_photo(person_id: str, photo_id: str, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Security check
    w_query = select(Watchlist).where(Watchlist.id == person_id)
    if user.role == "client":
        w_query = w_query.where(Watchlist.client_id == user.client_id)
    w_res = await db.execute(w_query)
    w_obj = w_res.scalar_one_or_none()
    if not w_obj:
        raise HTTPException(status_code=404, detail="Subject not found or access denied")
        
    p_res = await db.execute(select(PersonPhoto).where(and_(PersonPhoto.id == photo_id, PersonPhoto.person_id == person_id)))
    photo = p_res.scalar_one_or_none()
    if not photo:
        raise HTTPException(status_code=404, detail="Neural sample not found.")
    
    path = INTEL_DIR / f"{photo_id}.jpg"
    if path.exists():
        try: path.unlink()
        except: pass
    
    await db.delete(photo)
    await db.commit()
    
    if QDRANT_AVAILABLE and face_engine.QDRANT_CLIENT:
        collection_name = "watchlist"
        c_res = await db.execute(select(Client).where(Client.id == w_obj.client_id))
        client = c_res.scalar_one_or_none()
        if client and client.qdrant_collection:
            collection_name = client.qdrant_collection
            
        try:
            face_engine.QDRANT_CLIENT.delete(collection_name=collection_name, points_selector=[photo_id])
        except Exception:
            pass
            
    return {"ok": True}
