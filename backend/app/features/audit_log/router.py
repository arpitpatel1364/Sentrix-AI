"""
audit_log.py
============
FastAPI router for the Audit Log feature.

Endpoints:
  GET /api/audit-log         — paginated log, admin only, filter by action
  GET /api/audit-log/export  — download as CSV

Helper:
  write_log(db, username, role, action, target, detail, ip)
    Call this from any other router to record an action.

Wire into app/main.py:
  from app.features.audit_log.router import router as audit_router
  app.include_router(audit_router)

Table used: audit_log  (created in database.py)
Columns:  id, timestamp, username, role, action, target, detail, ip_address
"""

import csv
import io
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
import sqlite3

from ...core.security import get_current_user, require_admin
from ...core.database import get_db

router = APIRouter(prefix="/api")


# ─────────────────────────────────────────────────────────────────────────────
# write_log — call this from any other router to record an event
# ─────────────────────────────────────────────────────────────────────────────
def write_log(
    db: sqlite3.Connection,
    username: str,
    action: str,
    role: str = "",
    target: str = "",
    detail: str = "",
    ip: str = "",
):
    """
    Insert one audit log row synchronously.

    Parameters
    ----------
    db       : sqlite3 connection from get_db() or get_db_conn()
    username : who performed the action
    action   : short verb — e.g. 'login', 'add_camera', 'delete_person'
    role     : user role at time of action (admin / worker)
    target   : the object acted on — camera_id, person_id, username, etc.
    detail   : human-readable sentence describing what happened
    ip       : client IP (pass request.client.host)

    Example usage in another router:
        from app.features.audit_log.router import write_log
        write_log(db, username=user["username"], role=user["role"],
                  action="delete_person", target=person_id,
                  detail=f"Deleted {person_name}", ip=request.client.host)
    """
    entry_id = str(uuid.uuid4())
    ts = datetime.utcnow().isoformat()
    db.execute(
        """
        INSERT INTO audit_log (id, timestamp, username, role, action, target, detail, ip_address)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (entry_id, ts, username, role, action, target, detail, ip),
    )
    db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/audit-log
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/audit-log")
def get_audit_log(
    action: Optional[str] = Query(None, description="Filter by action type"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user=Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    Return paginated audit log. Admin only.
    Supports filtering by action type (e.g. 'login', 'delete_person').
    """
    conditions = []
    params = []

    if action:
        conditions.append("action = ?")
        params.append(action)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    total = db.execute(
        f"SELECT COUNT(*) FROM audit_log {where}", params
    ).fetchone()[0]

    rows = db.execute(
        f"""
        SELECT id, timestamp, username, role, action, target, detail, ip_address AS ip
        FROM audit_log
        {where}
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()

    return {
        "logs":   [dict(r) for r in rows],
        "total":  total,
        "limit":  limit,
        "offset": offset,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/audit-log/export  — CSV download
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/audit-log/export")
def export_audit_log(
    action: Optional[str] = Query(None),
    _user=Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
):
    """Download the full audit log as a CSV file. Admin only."""
    conditions = []
    params = []
    if action:
        conditions.append("action = ?")
        params.append(action)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = db.execute(
        f"""
        SELECT timestamp, username, role, action, target, detail, ip_address
        FROM audit_log {where}
        ORDER BY timestamp DESC
        LIMIT 50000
        """,
        params,
    ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "Username", "Role", "Action", "Target", "Detail", "IP"])
    for r in rows:
        writer.writerow(list(r))

    output.seek(0)
    filename = f"sentrix_audit_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
