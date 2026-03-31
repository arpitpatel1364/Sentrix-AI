from fastapi import APIRouter, Depends, HTTPException
import time
import shutil
from ...core.security import require_admin
from ...core.database import get_db, _add_user
from ...core.face_engine import (
    QDRANT_AVAILABLE
)
from ...core import face_engine
from ...core.config import SNAPSHOTS_DIR
from ...core.worker_state import ACTIVE_WORKERS
from qdrant_client.models import VectorParams, Distance
import sqlite3

router = APIRouter(prefix="/api")

@router.get("/stats")
async def get_stats(user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM sightings")
    total_sightings = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM sightings WHERE matched = 1")
    total_matches = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM wanted")
    total_wanted = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM object_detections")
    total_objects = cur.fetchone()[0]
    
    now = time.time()
    live_nodes = [k for k, v in ACTIVE_WORKERS.items() if now - v < 60]
    
    return {
        "total_sightings": total_sightings,
        "total_matches": total_matches,
        "total_wanted": total_wanted,
        "total_objects": total_objects,
        "total_nodes": len(live_nodes)
    }

@router.post("/system/reset")
async def system_reset(user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    try:
        db.execute("DELETE FROM sightings")
        db.execute("DELETE FROM wanted")
        db.execute("DELETE FROM users WHERE username != 'admin'")
        db.execute("DELETE FROM person_photos")
        db.commit()
        
        _add_user("worker1", "worker123", "worker")

        if QDRANT_AVAILABLE and face_engine.QDRANT_CLIENT:
            try:
                face_engine.QDRANT_CLIENT.delete_collection("sightings")
                face_engine.QDRANT_CLIENT.delete_collection("watchlist")
                face_engine.QDRANT_CLIENT.create_collection("sightings", vectors_config=VectorParams(size=512, distance=Distance.COSINE))
                face_engine.QDRANT_CLIENT.create_collection("watchlist", vectors_config=VectorParams(size=512, distance=Distance.COSINE))
            except Exception as e:
                print(f"Qdrant reset error: {e}")

        if SNAPSHOTS_DIR.exists():
            for item in SNAPSHOTS_DIR.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

        return {"ok": True, "message": "System reset successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")
