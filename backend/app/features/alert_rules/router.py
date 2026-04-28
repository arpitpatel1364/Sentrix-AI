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
import sqlite3
import uuid
import json
from datetime import datetime

router = APIRouter(prefix="/api")


# ─── RULE CRUD ───────────────────────────────────────────────────────────────

@router.get("/alert-rules")
async def list_rules(user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    
    # Filter by admin_id
    admin_filter = "WHERE admin_id = ?"
    params = (user["admin_id"],)
    if user["admin_id"] == 0:
        admin_filter = ""
        params = ()

    cur.execute(f"""
        SELECT id, name, rule_type, camera_id, conditions, actions, enabled, created_at, admin_id
        FROM alert_rules {admin_filter} ORDER BY created_at DESC
    """, params)
    rules = [dict(r) for r in cur.fetchall()]
    for r in rules:
        r["conditions"] = json.loads(r["conditions"]) if r["conditions"] else {}
        r["actions"]    = json.loads(r["actions"])    if r["actions"]    else {}
    return rules


@router.post("/alert-rules")
async def create_rule(request: Request, user=Depends(require_admin),
                      db: sqlite3.Connection = Depends(get_db)):
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
    db.execute("""
        INSERT INTO alert_rules (id, name, rule_type, camera_id, conditions, actions, enabled, created_at, admin_id)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
    """, (rule_id, name, rule_type, camera_id,
          json.dumps(conditions), json.dumps(actions), now, user["admin_id"]))
    db.commit()
    return {"ok": True, "id": rule_id}


@router.put("/alert-rules/{rule_id}")
async def update_rule(rule_id: str, request: Request,
                      user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    body = await request.json()
    cur = db.cursor()
    # Ownership Check
    if user["admin_id"] == 0:
        cur.execute("SELECT id FROM alert_rules WHERE id = ?", (rule_id,))
    else:
        cur.execute("SELECT id FROM alert_rules WHERE id = ? AND admin_id = ?", (rule_id, user["admin_id"]))
        
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Rule not found or access denied")

    fields, vals = [], []
    for key in ("name", "rule_type", "camera_id"):
        if key in body:
            fields.append(f"{key} = ?")
            vals.append(body[key])
    if "conditions" in body:
        fields.append("conditions = ?")
        vals.append(json.dumps(body["conditions"]))
    if "actions" in body:
        fields.append("actions = ?")
        vals.append(json.dumps(body["actions"]))
    if "enabled" in body:
        fields.append("enabled = ?")
        vals.append(1 if body["enabled"] else 0)

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    vals.append(rule_id)
    if user["admin_id"] != 0:
        vals.append(user["admin_id"])
        db.execute(f"UPDATE alert_rules SET {', '.join(fields)} WHERE id = ? AND admin_id = ?", vals)
    else:
         db.execute(f"UPDATE alert_rules SET {', '.join(fields)} WHERE id = ?", vals)
    db.commit()
    return {"ok": True}


@router.delete("/alert-rules/{rule_id}")
async def delete_rule(rule_id: str, user=Depends(require_admin),
                      db: sqlite3.Connection = Depends(get_db)):
    if user["admin_id"] == 0:
        db.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,))
    else:
        db.execute("DELETE FROM alert_rules WHERE id = ? AND admin_id = ?", (rule_id, user["admin_id"]))
    db.commit()
    return {"ok": True}


@router.patch("/alert-rules/{rule_id}/toggle")
async def toggle_rule(rule_id: str, user=Depends(require_admin),
                      db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    if user["admin_id"] == 0:
        cur.execute("SELECT enabled FROM alert_rules WHERE id = ?", (rule_id,))
    else:
        cur.execute("SELECT enabled FROM alert_rules WHERE id = ? AND admin_id = ?", (rule_id, user["admin_id"]))
        
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    new_state = 0 if row["enabled"] else 1
    
    if user["admin_id"] == 0:
        db.execute("UPDATE alert_rules SET enabled = ? WHERE id = ?", (new_state, rule_id))
    else:
        db.execute("UPDATE alert_rules SET enabled = ? WHERE id = ? AND admin_id = ?", (new_state, rule_id, user["admin_id"]))
    db.commit()
    return {"ok": True, "enabled": bool(new_state)}


# ─── RULE EVALUATION (called internally from workers/sightings) ──────────────

def _load_active_rules(db: sqlite3.Connection, admin_id: int, camera_id: str = None):
    """Load all enabled rules, optionally filtered by camera."""
    cur = db.cursor()
    
    # Filter by admin_id
    admin_filter = "AND admin_id = ?"
    params = (admin_id,)
    if admin_id == 0:
        admin_filter = ""
        params = ()

    if camera_id:
        cur.execute(f"""
            SELECT * FROM alert_rules
            WHERE enabled=1 AND (camera_id='' OR camera_id=?) {admin_filter}
        """, (camera_id,) + params)
    else:
        cur.execute(f"SELECT * FROM alert_rules WHERE enabled=1 {admin_filter}", params)
    rules = [dict(r) for r in cur.fetchall()]
    for r in rules:
        r["conditions"] = json.loads(r["conditions"]) if r["conditions"] else {}
        r["actions"]    = json.loads(r["actions"])    if r["actions"]    else {}
    return rules


async def evaluate_rules(event: dict, db: sqlite3.Connection):
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
    admin_id    = event.get("admin_id")
    if admin_id is None:
        admin_id = 1

    rules = _load_active_rules(db, admin_id, camera_id)

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
