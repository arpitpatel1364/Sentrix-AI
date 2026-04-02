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
    for i in range(days - 1, -1, -1):
        d = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
        cur.execute("SELECT COUNT(*) FROM sightings WHERE timestamp LIKE ?", (f"{d}%",))
        faces = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM sightings WHERE timestamp LIKE ? AND matched=1", (f"{d}%",))
        matches = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM object_detections WHERE timestamp LIKE ?", (f"{d}%",))
        objects = cur.fetchone()[0]
        result.append({"date": d, "faces": faces, "matches": matches, "objects": objects})
    return result


@router.get("/analytics/hourly")
async def analytics_hourly(days: int = 1, user=Depends(require_admin),
                            db: sqlite3.Connection = Depends(get_db)):
    """Hourly face detection count for heatmap — last N days merged."""
    cur = db.cursor()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    cur.execute("""
        SELECT substr(timestamp,12,2) as hour, COUNT(*) as cnt
        FROM sightings WHERE timestamp >= ?
        GROUP BY hour ORDER BY hour
    """, (cutoff,))
    rows = {r["hour"]: r["cnt"] for r in cur.fetchall()}
    # Return all 24 hours even if zero
    return [{"hour": f"{h:02d}:00", "count": rows.get(f"{h:02d}", 0)} for h in range(24)]


@router.get("/analytics/per-camera")
async def analytics_per_camera(days: int = 7, user=Depends(require_admin),
                                db: sqlite3.Connection = Depends(get_db)):
    """Per-camera detection totals for the last N days."""
    cur = db.cursor()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    cur.execute("""
        SELECT camera_id, COUNT(*) as faces,
               SUM(CASE WHEN matched=1 THEN 1 ELSE 0 END) as matches
        FROM sightings WHERE timestamp >= ?
        GROUP BY camera_id ORDER BY faces DESC
    """, (cutoff,))
    face_rows = {r["camera_id"]: dict(r) for r in cur.fetchall()}

    cur.execute("""
        SELECT camera_id, COUNT(*) as objects
        FROM object_detections WHERE timestamp >= ?
        GROUP BY camera_id
    """, (cutoff,))
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
    cur.execute("""
        SELECT object_label, COUNT(*) as count
        FROM object_detections WHERE timestamp >= ?
        GROUP BY object_label ORDER BY count DESC LIMIT ?
    """, (cutoff, limit))
    return [dict(r) for r in cur.fetchall()]


@router.get("/analytics/watchlist-hits")
async def analytics_watchlist_hits(days: int = 7, user=Depends(require_admin),
                                    db: sqlite3.Connection = Depends(get_db)):
    """Top matched watchlist persons over last N days."""
    cur = db.cursor()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    cur.execute("""
        SELECT person_name, person_id, COUNT(*) as hits, AVG(confidence) as avg_conf
        FROM sightings WHERE matched=1 AND timestamp >= ?
        GROUP BY person_id ORDER BY hits DESC LIMIT 10
    """, (cutoff,))
    return [dict(r) for r in cur.fetchall()]


@router.get("/analytics/timeline")
async def analytics_timeline(camera_id: str = None, hours: int = 24,
                              user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    """Minute-by-minute detection timeline (bucketed into 15-min slots)."""
    cur = db.cursor()
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

    if camera_id:
        cur.execute("""
            SELECT timestamp FROM sightings
            WHERE timestamp >= ? AND camera_id = ? ORDER BY timestamp ASC
        """, (cutoff, camera_id))
    else:
        cur.execute("SELECT timestamp FROM sightings WHERE timestamp >= ? ORDER BY timestamp ASC", (cutoff,))

    buckets = defaultdict(int)
    for row in cur.fetchall():
        ts = row["timestamp"][:16]  # "2025-01-01T14:35"
        # Round to 15 min bucket
        hour = int(ts[11:13])
        minute = (int(ts[14:16]) // 15) * 15
        bucket_key = f"{ts[:11]}{hour:02d}:{minute:02d}"
        buckets[bucket_key] += 1

    return [{"time": k, "count": v} for k, v in sorted(buckets.items())]
