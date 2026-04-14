"""
Alert Rules Engine
Configurable rules that trigger enhanced alerts based on
detection events: zone entry/exit, loitering, specific object types,
wanted matches, and time-based schedules.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from ...core.security import require_admin
from ...core.database import get_db
from ...core.sse_manager import broadcast_alert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import uuid
import json
from datetime import datetime

router = APIRouter(prefix="/api")


# ─── RULE CRUD ───────────────────────────────────────────────────────────────

@router.get("/alert-rules")
async def list_rules(user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    res = await db.execute(text("""
        SELECT id, name, rule_type, camera_id, conditions, actions, enabled, created_at
        FROM alert_rules ORDER BY created_at DESC
    """))
    rules = [dict(r._mapping) for r in res.fetchall()]
    for r in rules:
        r["conditions"] = json.loads(r["conditions"]) if r["conditions"] else {}
        r["actions"]    = json.loads(r["actions"])    if r["actions"]    else {}
    return rules


@router.post("/alert-rules")
async def create_rule(request: Request, user=Depends(require_admin),
                      db: AsyncSession = Depends(get_db)):
    body = await request.json()
    name      = body.get("name", "").strip()
    rule_type = body.get("rule_type", "")  # wanted_match | object_detected | loitering | any_face
    camera_id = body.get("camera_id", "")  # "" = all cameras
    conditions = body.get("conditions", {})
    actions    = body.get("actions", {})   # notify_email | webhook | dashboard_popup

    if not name or not rule_type:
        raise HTTPException(status_code=400, detail="name and rule_type are required")

    VALID_TYPES = {"wanted_match", "object_detected", "loitering", "any_face", "high_confidence"}
    if rule_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"rule_type must be one of {VALID_TYPES}")

    rule_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    await db.execute(text("""
        INSERT INTO alert_rules (id, name, rule_type, camera_id, conditions, actions, enabled, created_at)
        VALUES (:id, :name, :rule_type, :camera_id, :conditions, :actions, 1, :created_at)
    """), {
        "id": rule_id,
        "name": name,
        "rule_type": rule_type,
        "camera_id": camera_id,
        "conditions": json.dumps(conditions),
        "actions": json.dumps(actions),
        "created_at": now
    })
    await db.commit()
    return {"ok": True, "id": rule_id}


@router.put("/alert-rules/{rule_id}")
async def update_rule(rule_id: str, request: Request,
                      user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    body = await request.json()
    res = await db.execute(text("SELECT id FROM alert_rules WHERE id = :id"), {"id": rule_id})
    if not res.fetchone():
        raise HTTPException(status_code=404, detail="Rule not found")

    fields, params = [], {"id": rule_id}
    for key in ("name", "rule_type", "camera_id"):
        if key in body:
            fields.append(f"{key} = :{key}")
            params[key] = body[key]
    if "conditions" in body:
        fields.append("conditions = :conditions")
        params["conditions"] = json.dumps(body["conditions"])
    if "actions" in body:
        fields.append("actions = :actions")
        params["actions"] = json.dumps(body["actions"])
    if "enabled" in body:
        fields.append("enabled = :enabled")
        params["enabled"] = 1 if body["enabled"] else 0

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    query = f"UPDATE alert_rules SET {', '.join(fields)} WHERE id = :id"
    await db.execute(text(query), params)
    await db.commit()
    return {"ok": True}


@router.delete("/alert-rules/{rule_id}")
async def delete_rule(rule_id: str, user=Depends(require_admin),
                      db: AsyncSession = Depends(get_db)):
    await db.execute(text("DELETE FROM alert_rules WHERE id = :id"), {"id": rule_id})
    await db.commit()
    return {"ok": True}


@router.patch("/alert-rules/{rule_id}/toggle")
async def toggle_rule(rule_id: str, user=Depends(require_admin),
                      db: AsyncSession = Depends(get_db)):
    res = await db.execute(text("SELECT enabled FROM alert_rules WHERE id = :id"), {"id": rule_id})
    row = res.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    new_state = 0 if row._mapping["enabled"] else 1
    await db.execute(text("UPDATE alert_rules SET enabled = :state WHERE id = :id"), {"state": new_state, "id": rule_id})
    await db.commit()
    return {"ok": True, "enabled": bool(new_state)}


# ─── RULE EVALUATION (called internally from workers/sightings) ──────────────

async def _load_active_rules(db: AsyncSession, camera_id: str = None):
    """Load all enabled rules, optionally filtered by camera."""
    if camera_id:
        res = await db.execute(text("""
            SELECT * FROM alert_rules
            WHERE enabled=1 AND (camera_id='' OR camera_id=:camera_id)
        """), {"camera_id": camera_id})
    else:
        res = await db.execute(text("SELECT * FROM alert_rules WHERE enabled=1"))
    
    rules = [dict(r._mapping) for r in res.fetchall()]
    for r in rules:
        r["conditions"] = json.loads(r["conditions"]) if r["conditions"] else {}
        r["actions"]    = json.loads(r["actions"])    if r["actions"]    else {}
    return rules


async def evaluate_rules(event: dict, db: AsyncSession):
    """
    Evaluate all active rules against a detection event.
    event keys: type, camera_id, matched, confidence, person_name,
                object_label, timestamp
    """
    event_type  = event.get("type")       # "face" | "object"
    camera_id   = event.get("camera_id", "")
    matched     = event.get("matched", False)
    confidence  = event.get("confidence", 0.0)
    person_name = event.get("person_name", "")
    object_label = event.get("object_label", "")
    timestamp   = event.get("timestamp", datetime.utcnow().isoformat())

    rules = await _load_active_rules(db, camera_id)

    for rule in rules:
        cond    = rule["conditions"]
        actions = rule["actions"]
        fired   = False

        if rule["rule_type"] == "wanted_match" and event_type == "face" and matched:
            fired = True

        elif rule["rule_type"] == "any_face" and event_type == "face":
            fired = True

        elif rule["rule_type"] == "high_confidence" and event_type == "face":
            min_conf = cond.get("min_confidence", 90.0)
            if confidence >= min_conf:
                fired = True

        elif rule["rule_type"] == "object_detected" and event_type == "object":
            target = cond.get("object_label", "").lower()
            if not target or object_label.lower() == target:
                fired = True

        if fired:
            alert_payload = {
                "type": "rule_alert",
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "rule_type": rule["rule_type"],
                "camera_id": camera_id,
                "timestamp": timestamp,
                "event": event,
                "actions": actions,
            }
            await broadcast_alert(alert_payload)

            # Email / webhook handled by notification engine (see notifications/router.py)
            if actions.get("email") or actions.get("webhook_url"):
                from ..notifications.router import dispatch_notification
                await dispatch_notification(rule, event)
