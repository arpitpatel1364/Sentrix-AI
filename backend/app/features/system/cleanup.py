from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile, Request
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import os
import shutil
import numpy as np
from datetime import datetime, timedelta
from ...core.database import get_db
from ..audit_log.router import write_log
from ...core.security import require_admin
from ...core.config import SNAPSHOTS_DIR, SIMILARITY_THRESHOLD
from ...core import face_engine
from ...core.face_engine import QDRANT_AVAILABLE, get_embedding, bytes_to_cv2

router = APIRouter(prefix="/system")

@router.post("/cleanup")
async def cleanup_records(
    time_range: str = Query(..., description="Range: 1h, 24h, 7d, 30d, 90d, 1y"),
    person_id: Optional[str] = Query(None, description="Optional biometric ID to filter"),
    target: str = Query("all", description="Targets: all, sightings, objects"),
    request: Request = None,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Deletes snapshot records and physical files based on date range and biometric search.
    """
    try:
        # 1. Calculate Cutoff Timestamp
        now = datetime.utcnow()
        if time_range == "1h":
            cutoff = now - timedelta(hours=1)
        elif time_range == "24h":
            cutoff = now - timedelta(days=1)
        elif time_range == "7d":
            cutoff = now - timedelta(days=7)
        elif time_range == "30d":
            cutoff = now - timedelta(days=30)
        elif time_range == "90d":
            cutoff = now - timedelta(days=90)
        elif time_range == "1y":
            cutoff = now - timedelta(days=365)
        else:
            raise HTTPException(status_code=400, detail="Invalid time range")

        cutoff_str = cutoff.isoformat()
        
        counts = {"sightings": 0, "objects": 0, "files_removed": 0}
        
        # 2. Cleanup Sightings (Biometric)
        if target in ["all", "sightings"]:
            query = "SELECT id, snapshot_path FROM sightings WHERE timestamp < :cutoff"
            params = {"cutoff": cutoff_str}
            
            if person_id:
                query += " AND person_id = :person_id"
                params["person_id"] = person_id
                
            res = await db.execute(text(query), params)
            sightings = res.fetchall()
            
            for s in sightings:
                sid, path = s._mapping["id"], s._mapping["snapshot_path"]
                # File cleanup
                full_path = SNAPSHOTS_DIR / path
                if full_path.exists():
                    full_path.unlink()
                    counts["files_removed"] += 1
                
                # Qdrant cleanup
                if QDRANT_AVAILABLE and face_engine.QDRANT_CLIENT:
                    try:
                        face_engine.QDRANT_CLIENT.delete(
                            collection_name="sightings",
                            points_selector=[sid]
                        )
                    except: pass
                
                counts["sightings"] += 1
                
            # DB deletion
            delete_query = "DELETE FROM sightings WHERE timestamp < :cutoff"
            delete_params = {"cutoff": cutoff_str}
            if person_id:
                delete_query += " AND person_id = :person_id"
                delete_params["person_id"] = person_id
            await db.execute(text(delete_query), delete_params)

        # 3. Cleanup Object Detections
        if target in ["all", "objects"]:
            cutoff_space_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
            
            query = "SELECT id, snapshot_path FROM object_detections WHERE timestamp < :cutoff"
            params = {"cutoff": cutoff_space_str}
            
            res = await db.execute(text(query), params)
            objects = res.fetchall()
            
            for o in objects:
                oid, path = o._mapping["id"], o._mapping["snapshot_path"]
                full_path = SNAPSHOTS_DIR / path
                if full_path.exists():
                    full_path.unlink()
                    counts["files_removed"] += 1
                counts["objects"] += 1
                
            await db.execute(text("DELETE FROM object_detections WHERE timestamp < :cutoff"), {"cutoff": cutoff_space_str})

        await db.commit()
        await write_log(db, username=user["username"], role=user["role"], action="cleanup", target=target, detail=f"Manual cleanup: {time_range} records for {target}. Removed {counts['sightings']+counts['objects']} total records.", ip=request.client.host if request else "")
        return {
            "status": "success",
            "message": f"Cleanup completed for range {time_range}",
            "details": counts
        }

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

@router.post("/cleanup/biometric/search")
async def search_biometric_sightings(
    files: List[UploadFile] = File(...),
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Finds sightings and files by searching for matches against uploaded reference photos.
    Synced with system search logic: Individual searches + lenient threshold (0.60).
    """
    try:
        all_results = {}
        DISCOVERY_THRESHOLD = 0.60 # Lenient threshold for more results
        
        for file in files:
            data = await file.read()
            img = bytes_to_cv2(data)
            if img is None: continue
            
            embedding = get_embedding(img)
            if embedding is None: continue
            
            # --- Search using Qdrant (Priority) ---
            if QDRANT_AVAILABLE and face_engine.QDRANT_CLIENT:
                try:
                    hits = face_engine.QDRANT_CLIENT.search(
                        collection_name="sightings",
                        query_vector=embedding.tolist(),
                        limit=30,
                        score_threshold=DISCOVERY_THRESHOLD
                    )
                    for hit in hits:
                        if hit.id in all_results and (hit.score * 100) <= all_results[hit.id]["confidence"]:
                            continue
                            
                        # Fetch metadata from SQLite
                        res = await db.execute(text("SELECT id, camera_id, location, timestamp, snapshot_path, person_name FROM sightings WHERE id = :id"), {"id": hit.id})
                        r = res.fetchone()
                        if r:
                            all_results[hit.id] = {
                                "id": r._mapping["id"],
                                "camera_id": r._mapping["camera_id"],
                                "location": r._mapping["location"],
                                "timestamp": r._mapping["timestamp"],
                                "snapshot": f"/api/snapshots/{r._mapping['snapshot_path']}",
                                "person_name": r._mapping["person_name"],
                                "confidence": round(hit.score * 100, 1)
                            }
                except Exception as e:
                    print(f"Cleanup Qdrant search error: {e}")

            # --- SQLite Fallback (if Qdrant fails or is not used) ---
            else:
                res = await db.execute(text("SELECT id, camera_id, location, timestamp, snapshot_path, person_name, embedding FROM sightings"))
                all_sightings = res.fetchall()
                for s in all_sightings:
                    emb_blob = s._mapping["embedding"]
                    if not emb_blob: continue
                    
                    sig = np.frombuffer(emb_blob, dtype=np.float32)
                    sim = float(np.dot(embedding, sig))
                    
                    if sim >= DISCOVERY_THRESHOLD:
                        conf = round(sim * 100, 1)
                        if s._mapping["id"] not in all_results or conf > all_results[s._mapping["id"]]["confidence"]:
                            all_results[s._mapping["id"]] = {
                                "id": s._mapping["id"],
                                "camera_id": s._mapping["camera_id"],
                                "location": s._mapping["location"],
                                "timestamp": s._mapping["timestamp"],
                                "snapshot": f"/api/snapshots/{s._mapping['snapshot_path']}",
                                "person_name": s._mapping["person_name"],
                                "confidence": conf
                            }

        # Final sorting and output
        final_results = sorted(all_results.values(), key=lambda x: x["confidence"], reverse=True)

        return {
            "status": "success",
            "matches": final_results[:100],
            "total_matches": len(final_results)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Biometric discovery failed: {str(e)}")

@router.post("/cleanup/biometric/purge")
async def purge_biometric_sightings(
    sighting_ids: List[str],
    request: Request = None,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Permanently deletes a confirmed list of sighting IDs.
    """
    try:
        counts = {"purged": 0, "files_removed": 0}
        
        # Fetch snapshot paths for file deletion
        query = f"SELECT id, snapshot_path FROM sightings WHERE id IN ({','.join([':id'+str(i) for i in range(len(sighting_ids))])})"
        params = {f"id{i}": sid for i, sid in enumerate(sighting_ids)}
        res = await db.execute(text(query), params)
        sightings_to_delete = res.fetchall()
        
        for s in sightings_to_delete:
            sid, path = s._mapping["id"], s._mapping["snapshot_path"]
            
            # 1. File removal
            full_path = SNAPSHOTS_DIR / path
            if full_path.exists():
                full_path.unlink()
                counts["files_removed"] += 1
            
            # 2. Qdrant removal
            if QDRANT_AVAILABLE and face_engine.QDRANT_CLIENT:
                try:
                    face_engine.QDRANT_CLIENT.delete(
                        collection_name="sightings",
                        points_selector=[sid]
                    )
                except: pass
            
            counts["purged"] += 1

        # 3. DB Deletion
        for i in range(0, len(sighting_ids), 500):
            chunk = sighting_ids[i:i + 500]
            query = f"DELETE FROM sightings WHERE id IN ({','.join([':id'+str(j) for j in range(len(chunk))])})"
            params = {f"id{j}": sid for j, sid in enumerate(chunk)}
            await db.execute(text(query), params)
            
        await db.commit()
        await write_log(db, username=user["username"], role=user["role"], action="cleanup", target="biometric_purge", detail=f"Purged {counts['purged']} specific biometric sightings.", ip=request.client.host if request else "")

        return {
            "status": "success",
            "message": f"Successfully purged {counts['purged']} sightings.",
            "details": counts
        }

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Purge failed: {str(e)}")
