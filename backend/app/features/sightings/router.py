from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from fastapi.responses import StreamingResponse
from typing import List
import numpy as np
from ...core.security import require_admin
from ...core.database import get_db
from ...core.face_engine import (
    get_embedding, bytes_to_cv2, QDRANT_AVAILABLE, match_wanted
)
from ...core import face_engine
from ...core.config import SNAPSHOTS_DIR
import sqlite3

router = APIRouter(prefix="/api")

@router.get("/sightings")
async def get_sightings(limit: int = 50, user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM sightings")
    total_count = cur.fetchone()[0]

    cur.execute("""
        SELECT id, camera_id, location, timestamp, uploaded_by, snapshot_path, matched, person_id, person_name, confidence 
        FROM sightings ORDER BY timestamp DESC LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["snapshot"] = f"/api/snapshots/{r['snapshot_path']}"
    return {"sightings": rows, "total_count": total_count}

@router.get("/snapshots/{path:path}")
async def get_snapshot(path: str):
    full_path = SNAPSHOTS_DIR / path
    if not full_path.exists():
        raise HTTPException(status_code=404)
    return StreamingResponse(open(full_path, "rb"), media_type="image/jpeg")

@router.post("/search-face")
async def search_face(files: List[UploadFile] = File(...), user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    all_results = {}
    identified_person = "Unknown Person"
    
    for file in files:
        data = await file.read()
        img = bytes_to_cv2(data)
        embedding = get_embedding(img)
        if embedding is None:
            continue

        if identified_person == "Unknown Person":
            found = match_wanted(embedding)
            if found:
                identified_person = found["person"]["name"]

        if QDRANT_AVAILABLE and face_engine.QDRANT_CLIENT:
            try:
                hits = face_engine.QDRANT_CLIENT.search(
                    collection_name="sightings",
                    query_vector=embedding.tolist(),
                    limit=15
                )
                for hit in hits:
                    conf = round(hit.score * 100, 1)
                    if hit.id not in all_results or conf > all_results[hit.id]["confidence"]:
                        cur = db.cursor()
                        cur.execute("""
                            SELECT id, camera_id, location, timestamp, snapshot_path, matched, person_id, person_name, confidence 
                            FROM sightings WHERE id = ?
                        """, (hit.id,))
                        r = cur.fetchone()
                        if r:
                            item = dict(r)
                            item["snapshot"] = f"/api/snapshots/{item['snapshot_path']}"
                            item["confidence"] = conf
                            all_results[hit.id] = item
            except Exception as e:
                print(f"Global history search error: {e}")

    final_results = sorted(all_results.values(), key=lambda x: x["confidence"], reverse=True)
    
    return {
        "found": len(final_results) > 0,
        "person": identified_person,
        "total_count": len(final_results),
        "matches": final_results[:20]
    }
