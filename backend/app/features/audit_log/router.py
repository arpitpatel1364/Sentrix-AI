"""
audit_log.py
============
FastAPI router for the Audit Log feature. Optimized for async PostgreSQL.
"""

import csv
import io
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ...core.dependencies import require_admin
from ...core.database import get_db

router = APIRouter(tags=["Audit"])


# ─────────────────────────────────────────────────────────────────────────────
# write_log — call this from any other router to record an event
# ─────────────────────────────────────────────────────────────────────────────
async def write_log(
    db: AsyncSession,
    username: str,
    action: str,
    role: str = "",
    target: str = "",
    detail: str = "",
    ip: str = "",
):
    """
    Insert one audit log row asynchronously.
    """
    entry_id = str(uuid.uuid4())
    ts = datetime.utcnow().isoformat()
    await db.execute(
        text("""
        INSERT INTO audit_log (id, timestamp, username, role, action, target, detail, ip_address)
        VALUES (:id, :timestamp, :username, :role, :action, :target, :detail, :ip)
        """),
        {
            "id": entry_id,
            "timestamp": ts,
            "username": username,
            "role": role,
            "action": action,
            "target": target,
            "detail": detail,
            "ip": ip
        },
    )
    await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/audit-log
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/audit-log")
async def get_audit_log(
    action: Optional[str] = Query(None, description="Filter by action type"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Return paginated audit log. Admin only.
    """
    conditions = []
    params = {"limit": limit, "offset": offset}

    if action:
        conditions.append("action = :action")
        params["action"] = action

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    count_res = await db.execute(
        text(f"SELECT COUNT(*) FROM audit_log {where}"), params
    )
    total = count_res.scalar()

    rows_res = await db.execute(
        text(f"""
        SELECT id, timestamp, username, role, action, target, detail, ip_address AS ip
        FROM audit_log
        {where}
        ORDER BY timestamp DESC
        LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = rows_res.mappings().all()

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
async def export_audit_log(
    action: Optional[str] = Query(None),
    _user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Download the full audit log as a CSV file. Admin only."""
    conditions = []
    params = {}
    if action:
        conditions.append("action = :action")
        params["action"] = action
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows_res = await db.execute(
        text(f"""
        SELECT timestamp, username, role, action, target, detail, ip_address
        FROM audit_log {where}
        ORDER BY timestamp DESC
        LIMIT 50000
        """),
        params,
    )
    rows = rows_res.all()

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
