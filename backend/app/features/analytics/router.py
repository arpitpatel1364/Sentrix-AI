"""
Analytics Feature
Provides time-series detection data, per-camera breakdown,
hourly activity heatmaps, and trend charts for the dashboard.
"""

from fastapi import APIRouter, Depends
from ...core.dependencies import require_admin
from ...core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime, timedelta
from collections import defaultdict

router = APIRouter(tags=["Analytics"])


@router.get("/analytics/overview")
async def analytics_overview(days: int = 7, user=Depends(require_admin),
                              db: AsyncSession = Depends(get_db)):
    """Daily totals for the last N days."""
    result = []
    for i in range(days - 1, -1, -1):
        d = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
        
        faces_res = await db.execute(text("SELECT COUNT(*) FROM sightings WHERE timestamp LIKE :d"), {"d": f"{d}%"})
        faces = faces_res.scalar()
        
        matches_res = await db.execute(text("SELECT COUNT(*) FROM sightings WHERE timestamp LIKE :d AND matched=TRUE"), {"d": f"{d}%"})
        matches = matches_res.scalar()
        
        objects_res = await db.execute(text("SELECT COUNT(*) FROM object_detections WHERE timestamp LIKE :d"), {"d": f"{d}%"})
        objects = objects_res.scalar()
        
        result.append({"date": d, "faces": faces, "matches": matches, "objects": objects})
    return result


@router.get("/analytics/hourly")
async def analytics_hourly(days: int = 1, user=Depends(require_admin),
                            db: AsyncSession = Depends(get_db)):
    """Hourly face detection count for heatmap — last N days merged."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    res = await db.execute(text("""
        SELECT substr(timestamp,12,2) as hour, COUNT(*) as cnt
        FROM sightings WHERE timestamp >= :cutoff
        GROUP BY hour ORDER BY hour
    """), {"cutoff": cutoff})
    
    rows = {r._mapping["hour"]: r._mapping["cnt"] for r in res.fetchall()}
    # Return all 24 hours even if zero
    return [{"hour": f"{h:02d}:00", "count": rows.get(f"{h:02d}", 0)} for h in range(24)]


@router.get("/analytics/per-camera")
async def analytics_per_camera(days: int = 7, user=Depends(require_admin),
                                db: AsyncSession = Depends(get_db)):
    """Per-camera detection totals for the last N days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    
    face_res = await db.execute(text("""
        SELECT camera_id, COUNT(*) as faces,
               SUM(CASE WHEN matched=TRUE THEN 1 ELSE 0 END) as matches
        FROM sightings WHERE timestamp >= :cutoff
        GROUP BY camera_id ORDER BY faces DESC
    """), {"cutoff": cutoff})
    face_rows = {r._mapping["camera_id"]: dict(r._mapping) for r in face_res.fetchall()}

    obj_res = await db.execute(text("""
        SELECT camera_id, COUNT(*) as objects
        FROM object_detections WHERE timestamp >= :cutoff
        GROUP BY camera_id
    """), {"cutoff": cutoff})
    obj_rows = {r._mapping["camera_id"]: r._mapping["objects"] for r in obj_res.fetchall()}

    all_cams = set(list(face_rows.keys()) + list(obj_rows.keys()))
    result = []
    for cam in all_cams:
        f = face_rows.get(cam, {"faces": 0, "matches": 0})
        result.append({
            "camera_id": cam,
            "faces": f["faces"],
            "matches": f["matches"],
            "objects": obj_rows.get(cam, 0),
        })
    return sorted(result, key=lambda x: x["faces"] + x["objects"], reverse=True)


@router.get("/analytics/top-objects")
async def analytics_top_objects(days: int = 7, limit: int = 10,
                                 user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Most frequently detected object labels."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    res = await db.execute(text("""
        SELECT object_label, COUNT(*) as count
        FROM object_detections WHERE timestamp >= :cutoff
        GROUP BY object_label ORDER BY count DESC LIMIT :limit
    """), {"cutoff": cutoff, "limit": limit})
    return [dict(r._mapping) for r in res.fetchall()]


@router.get("/analytics/watchlist-hits")
async def analytics_watchlist_hits(days: int = 7, user=Depends(require_admin),
                                    db: AsyncSession = Depends(get_db)):
    """Top matched watchlist persons over last N days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    res = await db.execute(text("""
        SELECT person_name, person_id, COUNT(*) as hits, AVG(confidence) as avg_conf
        FROM sightings WHERE matched=TRUE AND timestamp >= :cutoff
        GROUP BY person_id, person_name ORDER BY hits DESC LIMIT 10
    """), {"cutoff": cutoff})
    return [dict(r._mapping) for r in res.fetchall()]


@router.get("/analytics/timeline")
async def analytics_timeline(camera_id: str = None, hours: int = 24,
                              user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Minute-by-minute detection timeline (bucketed into 15-min slots)."""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

    if camera_id:
        res = await db.execute(text("""
            SELECT timestamp FROM sightings
            WHERE timestamp >= :cutoff AND camera_id = :camera_id ORDER BY timestamp ASC
        """), {"cutoff": cutoff, "camera_id": camera_id})
    else:
        res = await db.execute(text("SELECT timestamp FROM sightings WHERE timestamp >= :cutoff ORDER BY timestamp ASC"), {"cutoff": cutoff})

    buckets = defaultdict(int)
    for row in res.fetchall():
        ts = row._mapping["timestamp"][:16]  # "2025-01-01T14:35"
        # Round to 15 min bucket
        hour = int(ts[11:13])
        minute = (int(ts[14:16]) // 15) * 15
        bucket_key = f"{ts[:11]}{hour:02d}:{minute:02d}"
        buckets[bucket_key] += 1

    return [{"time": k, "count": v} for k, v in sorted(buckets.items())]
