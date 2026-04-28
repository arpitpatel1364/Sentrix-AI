"""
Analytics Feature
Provides time-series detection data, per-camera breakdown,
hourly activity heatmaps, and trend charts for the dashboard.
"""

from fastapi import APIRouter, Depends
from ...core.security import require_admin
from ...core.database import get_db
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

router = APIRouter(prefix="/api")


@router.get("/analytics/overview")
async def analytics_overview(days: int = 7, user=Depends(require_admin),
                              db: sqlite3.Connection = Depends(get_db)):
    """Daily totals for the last N days — faces + objects + matches."""
    cur = db.cursor()
    result = []
    
    # Filter by admin_id
    admin_filter = "AND admin_id = ?"
    params = (user["admin_id"],)
    if user["admin_id"] == 0:
        admin_filter = ""
        params = ()

    for i in range(days - 1, -1, -1):
        d = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
        cur.execute(f"SELECT COUNT(*) FROM sightings WHERE timestamp LIKE ? {admin_filter}", (f"{d}%",) + params)
        faces = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM sightings WHERE timestamp LIKE ? AND matched=1 {admin_filter}", (f"{d}%",) + params)
        matches = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM object_detections WHERE timestamp LIKE ? {admin_filter}", (f"{d}%",) + params)
        objects = cur.fetchone()[0]
        result.append({"date": d, "faces": faces, "matches": matches, "objects": objects})
    return result


@router.get("/analytics/hourly")
async def analytics_hourly(days: int = 1, user=Depends(require_admin),
                            db: sqlite3.Connection = Depends(get_db)):
    """Hourly face detection count for heatmap — last N days merged."""
    cur = db.cursor()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    
    admin_filter = "AND admin_id = ?"
    params = (cutoff, user["admin_id"])
    if user["admin_id"] == 0:
        admin_filter = ""
        params = (cutoff,)

    cur.execute(f"""
        SELECT substr(timestamp,12,2) as hour, COUNT(*) as cnt
        FROM sightings WHERE timestamp >= ? {admin_filter}
        GROUP BY hour ORDER BY hour
    """, params)
    rows = {r["hour"]: r["cnt"] for r in cur.fetchall()}
    # Return all 24 hours even if zero
    return [{"hour": f"{h:02d}:00", "count": rows.get(f"{h:02d}", 0)} for h in range(24)]


@router.get("/analytics/per-camera")
async def analytics_per_camera(days: int = 7, user=Depends(require_admin),
                                db: sqlite3.Connection = Depends(get_db)):
    """Per-camera detection totals for the last N days."""
    cur = db.cursor()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    # Filter by admin_id
    admin_filter = "AND admin_id = ?"
    params = (cutoff, user["admin_id"])
    if user["admin_id"] == 0:
        admin_filter = ""
        params = (cutoff,)

    cur.execute(f"""
        SELECT camera_id, COUNT(*) as faces,
               SUM(CASE WHEN matched=1 THEN 1 ELSE 0 END) as matches
        FROM sightings WHERE timestamp >= ? {admin_filter}
        GROUP BY camera_id ORDER BY faces DESC
    """, params)
    face_rows = {r["camera_id"]: dict(r) for r in cur.fetchall()}

    cur.execute(f"""
        SELECT camera_id, COUNT(*) as objects
        FROM object_detections WHERE timestamp >= ? {admin_filter}
        GROUP BY camera_id
    """, params)
    obj_rows = {r["camera_id"]: r["objects"] for r in cur.fetchall()}

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
                                 user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    """Most frequently detected object labels."""
    cur = db.cursor()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    # Filter by admin_id
    admin_filter = "AND admin_id = ?"
    params = (cutoff, user["admin_id"], limit)
    if user["admin_id"] == 0:
        admin_filter = ""
        params = (cutoff, limit)

    cur.execute(f"""
        SELECT object_label, COUNT(*) as count
        FROM object_detections WHERE timestamp >= ? {admin_filter}
        GROUP BY object_label ORDER BY count DESC LIMIT ?
    """, params)
    return [dict(r) for r in cur.fetchall()]


@router.get("/analytics/watchlist-hits")
async def analytics_watchlist_hits(days: int = 7, user=Depends(require_admin),
                                    db: sqlite3.Connection = Depends(get_db)):
    """Top matched watchlist persons over last N days."""
    cur = db.cursor()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    # Filter by admin_id
    admin_filter = "AND admin_id = ?"
    params = (cutoff, user["admin_id"])
    if user["admin_id"] == 0:
        admin_filter = ""
        params = (cutoff,)

    cur.execute(f"""
        SELECT person_name, person_id, COUNT(*) as hits, AVG(confidence) as avg_conf
        FROM sightings WHERE matched=1 AND timestamp >= ? {admin_filter}
        GROUP BY person_id ORDER BY hits DESC LIMIT 10
    """, params)
    return [dict(r) for r in cur.fetchall()]


@router.get("/analytics/timeline")
async def analytics_timeline(camera_id: str = None, hours: int = 24,
                              user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    """Minute-by-minute detection timeline (bucketed into 15-min slots)."""
    cur = db.cursor()
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

    # Tenant Filtering logic
    admin_id = user["admin_id"]
    
    if camera_id:
        if admin_id == 0:
            query = "SELECT timestamp FROM sightings WHERE timestamp >= ? AND camera_id = ? ORDER BY timestamp ASC"
            params = (cutoff, camera_id)
        else:
            query = "SELECT timestamp FROM sightings WHERE timestamp >= ? AND camera_id = ? AND admin_id = ? ORDER BY timestamp ASC"
            params = (cutoff, camera_id, admin_id)
    else:
        if admin_id == 0:
            query = "SELECT timestamp FROM sightings WHERE timestamp >= ? ORDER BY timestamp ASC"
            params = (cutoff,)
        else:
            query = "SELECT timestamp FROM sightings WHERE timestamp >= ? AND admin_id = ? ORDER BY timestamp ASC"
            params = (cutoff, admin_id)

    cur.execute(query, params)

    buckets = defaultdict(int)
    for row in cur.fetchall():
        ts = row["timestamp"][:16]  # "2025-01-01T14:35"
        # Round to 15 min bucket
        hour = int(ts[11:13])
        minute = (int(ts[14:16]) // 15) * 15
        bucket_key = f"{ts[:11]}{hour:02d}:{minute:02d}"
        buckets[bucket_key] += 1

    return [{"time": k, "count": v} for k, v in sorted(buckets.items())]
