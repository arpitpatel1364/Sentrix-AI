"""
stop_requests.py
================
FastAPI router for the Worker Camera Stop Request flow.

How it works
------------
1. Worker runs worker_start.py, which opens the browser.
   Admin registers cameras from the dashboard.

2. If a worker wants to stop a camera, worker_start.py calls:
     POST /api/stop-requests
   with camera_id and a reason. The request lands in camera_stop_requests
   table with status='pending'.

3. Admin sees a badge in the sidebar on the "Stop Requests" page.
   Admin clicks Approve or Deny.

4. worker_start.py polls GET /api/stop-requests/my-status every 10s.
   - "approved" → worker_start.py terminates worker_agent cleanly.
   - "denied"   → worker_start.py logs it and keeps running.

Wire into app/main.py:
  from app.features.stop_requests.router import router as stop_router
  app.include_router(stop_router)

Table used: camera_stop_requests (created in database.py)
Columns: id, camera_id, worker_user, reason, status,
         requested_at, reviewed_by, reviewed_at
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
import sqlite3

from ...core.security import get_current_user, require_admin
from ...core.database import get_db
from ...core.sse_manager import broadcast_alert

router = APIRouter(prefix="/api")


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/stop-requests
# Worker submits a stop request for one of its cameras
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/stop-requests")
async def create_stop_request(
    request: Request,
    camera_id: str = Form(...),
    reason: str = Form(""),
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    Worker calls this when it wants to stop a camera.
    A pending request is created — admin must approve before the
    worker actually shuts down.
    """
    # Don't create a duplicate if one is already pending
    existing = db.execute(
        """
        SELECT id FROM camera_stop_requests
        WHERE worker_user = ? AND camera_id = ? AND status = 'pending'
        """,
        (user["username"], camera_id),
    ).fetchone()

    if existing:
        return {"status": "already_pending", "request_id": existing["id"]}

    # Get camera location for display in dashboard
    cam = db.execute(
        "SELECT location FROM cameras WHERE camera_id = ?", (camera_id,)
    ).fetchone()
    location = cam["location"] if cam else ""

    req_id = str(uuid.uuid4())
    ts = datetime.utcnow().isoformat()

    db.execute(
        """
        INSERT INTO camera_stop_requests
          (id, camera_id, worker_user, reason, status, requested_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
        """,
        (req_id, camera_id, user["username"], reason.strip(), ts),
    )
    db.commit()

    # Audit log
    try:
        from ...features.audit_log.router import write_log
        write_log(
            db,
            username=user["username"],
            role=user.get("role", "worker"),
            action="stop_request",
            target=camera_id,
            detail=f"Stop requested. Reason: {reason[:120]}",
            ip=request.client.host if request.client else "",
        )
    except Exception:
        pass

    # Push SSE notification to all admin dashboards
    await broadcast_alert({
        "type":       "stop_request",
        "worker":     user["username"],
        "camera_id":  camera_id,
        "location":   location,
        "request_id": req_id,
        "reason":     reason[:120],
    })

    return {"status": "pending", "request_id": req_id}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/stop-requests/my-status?camera_id=cam-1
# Worker polls this to know if its request was approved or denied
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/stop-requests/my-status")
def get_my_stop_status(
    camera_id: str,
    user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    Returns the latest stop request status for this worker+camera.
    worker_start.py polls this every 10 seconds.
    """
    row = db.execute(
        """
        SELECT id, status, reviewed_by, reviewed_at
        FROM camera_stop_requests
        WHERE worker_user = ? AND camera_id = ?
        ORDER BY requested_at DESC
        LIMIT 1
        """,
        (user["username"], camera_id),
    ).fetchone()

    if not row:
        return {"status": "no_request"}

    return {
        "request_id":  row["id"],
        "status":      row["status"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/stop-requests
# Admin lists all requests
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/stop-requests")
def list_stop_requests(
    status: Optional[str] = None,
    _user=Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
):
    """Admin: list all camera stop requests, newest first."""
    conditions = []
    params = []
    if status:
        conditions.append("status = ?")
        params.append(status)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = db.execute(
        f"""
        SELECT id,
               worker_user    AS worker_username,
               camera_id,
               reason,
               status,
               requested_at,
               reviewed_by    AS resolved_by,
               reviewed_at    AS resolved_at,
               '' AS location
        FROM camera_stop_requests
        {where}
        ORDER BY requested_at DESC
        LIMIT 300
        """,
        params,
    ).fetchall()

    # Enrich with camera location from cameras table
    results = []
    for r in rows:
        row = dict(r)
        cam = db.execute(
            "SELECT location FROM cameras WHERE camera_id = ?", (r["camera_id"],)
        ).fetchone()
        row["location"] = cam["location"] if cam else ""
        results.append(row)

    return {"requests": results}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/stop-requests/{id}/approve
# Admin approves — worker will stop that camera
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/stop-requests/{request_id}/approve")
async def approve_stop_request(
    request_id: str,
    req: Request,
    user=Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute(
        "SELECT * FROM camera_stop_requests WHERE id = ?", (request_id,)
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Request not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Already {row['status']}")

    ts = datetime.utcnow().isoformat()
    db.execute(
        """
        UPDATE camera_stop_requests
        SET status = 'approved', reviewed_by = ?, reviewed_at = ?
        WHERE id = ?
        """,
        (user["username"], ts, request_id),
    )
    db.commit()

    # Audit
    try:
        from ...features.audit_log.router import write_log
        write_log(
            db,
            username=user["username"],
            role=user.get("role", "admin"),
            action="stop_approve",
            target=row["camera_id"],
            detail=f"Approved stop request from worker '{row['worker_user']}'",
            ip=req.client.host if req.client else "",
        )
    except Exception:
        pass

    # SSE so the dashboard badge refreshes
    await broadcast_alert({
        "type":        "stop_approved",
        "camera_id":   row["camera_id"],
        "worker":      row["worker_user"],
        "approved_by": user["username"],
    })

    return {"status": "approved"}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/stop-requests/{id}/deny
# Admin denies — worker keeps running
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/stop-requests/{request_id}/deny")
async def deny_stop_request(
    request_id: str,
    req: Request,
    user=Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute(
        "SELECT * FROM camera_stop_requests WHERE id = ?", (request_id,)
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Request not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Already {row['status']}")

    ts = datetime.utcnow().isoformat()
    db.execute(
        """
        UPDATE camera_stop_requests
        SET status = 'denied', reviewed_by = ?, reviewed_at = ?
        WHERE id = ?
        """,
        (user["username"], ts, request_id),
    )
    db.commit()

    # Audit
    try:
        from ...features.audit_log.router import write_log
        write_log(
            db,
            username=user["username"],
            role=user.get("role", "admin"),
            action="stop_deny",
            target=row["camera_id"],
            detail=f"Denied stop request from worker '{row['worker_user']}'",
            ip=req.client.host if req.client else "",
        )
    except Exception:
        pass

    return {"status": "denied"}
