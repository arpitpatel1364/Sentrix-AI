from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from fastapi.responses import FileResponse
from typing import List
import uuid
import cv2
import numpy as np
from datetime import datetime
from ...core.security import require_admin
from ...core.database import get_db
from ...core.face_engine import (
    get_embedding, bytes_to_cv2, QDRANT_CLIENT, QDRANT_AVAILABLE
)
from ...core.config import INTEL_DIR
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue

router = APIRouter(prefix="/api")

@router.get("/wanted")
async def get_wanted(user=Depends(require_admin)):
    with next(get_db()) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT w.id, w.name, w.added_by, w.added_at, 
                   COUNT(p.id) as photo_count,
                   (SELECT id FROM person_photos WHERE person_id = w.id LIMIT 1) as primary_photo
            FROM wanted w LEFT JOIN person_photos p ON w.id = p.person_id
            GROUP BY w.id ORDER BY w.added_at DESC
        """)
        return [dict(r) for r in cur.fetchall()]

@router.get("/wanted/{person_id}/photos")
async def get_person_photos(person_id: str, user=Depends(require_admin)):
    with next(get_db()) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, added_at FROM person_photos WHERE person_id = ? ORDER BY added_at ASC", (person_id,))
        return [dict(r) for r in cur.fetchall()]

@router.get("/intel-photos/{photo_id}")
async def get_intel_photo(photo_id: str):
    path = INTEL_DIR / f"{photo_id}.jpg"
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path)

@router.post("/wanted")
async def add_wanted(
    files: List[UploadFile] = File(...),
    name: str = Form(...),
    user=Depends(require_admin)
):
    name_str = name.strip()
    pids_processed = []

    for file in files:
        data = await file.read()
        img = bytes_to_cv2(data)
        embedding = get_embedding(img)
        if embedding is None:
            continue

        with next(get_db()) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM wanted WHERE name = ?", (name_str,))
            row = cur.fetchone()
            
            if row:
                pid = row["id"]
                cur.execute("SELECT COUNT(*) FROM person_photos WHERE person_id = ?", (pid,))
                if cur.fetchone()[0] >= 15:
                    continue
            else:
                pid = str(uuid.uuid4())
                now = datetime.utcnow().isoformat()
                cur.execute("INSERT INTO wanted (id, name, added_by, added_at) VALUES (?, ?, ?, ?)",
                        (pid, name_str, user["username"], now))

            photo_id = str(uuid.uuid4())
            now = datetime.utcnow().isoformat()
            
            photo_path = INTEL_DIR / f"{photo_id}.jpg"
            cv2.imwrite(str(photo_path), img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            
            emb_blob = embedding.astype(np.float32).tobytes()
            cur.execute("INSERT INTO person_photos (id, person_id, embedding, snapshot_path, added_at) VALUES (?, ?, ?, ?, ?)",
                    (photo_id, pid, emb_blob, f"{photo_id}.jpg", now))
            conn.commit()

            if QDRANT_AVAILABLE and QDRANT_CLIENT:
                try:
                    QDRANT_CLIENT.upsert(
                        collection_name="watchlist",
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

    return {"status": "success", "count": len(pids_processed), "name": name_str}

@router.delete("/wanted/{person_id}")
async def remove_wanted(person_id: str, user=Depends(require_admin)):
    with next(get_db()) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM person_photos WHERE person_id = ?", (person_id,))
        photo_rows = cur.fetchall()
        for row in photo_rows:
            photo_id = row["id"]
            path = INTEL_DIR / f"{photo_id}.jpg"
            if path.exists():
                try: path.unlink()
                except: pass
        
        conn.execute("DELETE FROM person_photos WHERE person_id = ?", (person_id,))
        conn.execute("DELETE FROM wanted WHERE id = ?", (person_id,))
        conn.commit()
    
    if QDRANT_AVAILABLE and QDRANT_CLIENT:
        try:
            QDRANT_CLIENT.delete(
                collection_name="watchlist",
                points_selector=Filter(
                    must=[FieldCondition(key="person_id", match=MatchValue(value=person_id))]
                )
            )
        except Exception as e:
            print(f"Qdrant purge error: {e}")
        
    return {"ok": True}

@router.delete("/wanted/{person_id}/photos/{photo_id}")
async def delete_intel_photo(person_id: str, photo_id: str, user=Depends(require_admin)):
    with next(get_db()) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM person_photos WHERE id = ? AND person_id = ?", (photo_id, person_id))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Neural sample not found.")
        
        path = INTEL_DIR / f"{photo_id}.jpg"
        if path.exists():
            try: path.unlink()
            except: pass
        
        conn.execute("DELETE FROM person_photos WHERE id = ?", (photo_id,))
        conn.commit()
    
    if QDRANT_AVAILABLE and QDRANT_CLIENT:
        try:
            QDRANT_CLIENT.delete(collection_name="watchlist", points_selector=[photo_id])
        except Exception as e:
            print(f"Qdrant single purge error: {e}")
            
    return {"ok": True}
