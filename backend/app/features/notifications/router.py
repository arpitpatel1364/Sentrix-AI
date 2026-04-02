"""
Notification System
Handles email (SMTP) and webhook (HTTP POST) dispatch for alert rules.
Configuration stored in DB — admin can set SMTP credentials and test channels.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from ...core.security import require_admin
from ...core.database import get_db
import sqlite3
import json
import aiohttp
import asyncio
from datetime import datetime

router = APIRouter(prefix="/api")


# ─── NOTIFICATION CONFIG ─────────────────────────────────────────────────────

@router.get("/notifications/config")
async def get_config(user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT key, value FROM notification_config")
    raw = {r["key"]: r["value"] for r in cur.fetchall()}
    # Mask password
    if "smtp_password" in raw:
        raw["smtp_password"] = "••••••••" if raw["smtp_password"] else ""
    return raw


@router.post("/notifications/config")
async def save_config(request: Request, user=Depends(require_admin),
                      db: sqlite3.Connection = Depends(get_db)):
    body = await request.json()
    allowed = {
        "smtp_host", "smtp_port", "smtp_user", "smtp_password",
        "smtp_from", "smtp_to",   # comma-separated recipient list
        "smtp_tls",               # "1" or "0"
    }
    for key, val in body.items():
        if key in allowed:
            db.execute("""
                INSERT INTO notification_config (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """, (key, str(val)))
    db.commit()
    return {"ok": True}


@router.post("/notifications/test-email")
async def test_email(user=Depends(require_admin), db: sqlite3.Connection = Depends(get_db)):
    """Send a test email using current SMTP config."""
    cfg = _load_config(db)
    if not cfg.get("smtp_host"):
        raise HTTPException(status_code=400, detail="SMTP not configured")
    try:
        await _send_email(cfg, "Sentrix-AI Test", "✅ Your notification channel is working correctly.")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notifications/history")
async def notification_history(limit: int = 50, user=Depends(require_admin),
                                db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("""
        SELECT id, channel, recipient, subject, status, error, sent_at
        FROM notification_log ORDER BY sent_at DESC LIMIT ?
    """, (limit,))
    return [dict(r) for r in cur.fetchall()]


# ─── INTERNAL DISPATCH ───────────────────────────────────────────────────────

def _load_config(db: sqlite3.Connection) -> dict:
    cur = db.cursor()
    cur.execute("SELECT key, value FROM notification_config")
    return {r["key"]: r["value"] for r in cur.fetchall()}


async def dispatch_notification(rule: dict, event: dict):
    """Called by alert_rules engine. Sends email and/or webhook."""
    from ...core.database import get_db_conn

    actions = rule.get("actions", {})
    rule_name = rule.get("name", "Alert")
    camera_id = event.get("camera_id", "?")
    person    = event.get("person_name", "")
    obj_label = event.get("object_label", "")
    ts        = event.get("timestamp", datetime.utcnow().isoformat())[:19].replace("T", " ")
    rule_type = rule.get("rule_type", "")

    # Build message
    if rule_type == "wanted_match":
        subject = f"🚨 WANTED MATCH: {person}"
        body    = f"Rule: {rule_name}\nCamera: {camera_id}\nPerson: {person}\nConfidence: {event.get('confidence',0)}%\nTime: {ts}"
    elif rule_type == "object_detected":
        subject = f"📦 Object Detected: {obj_label}"
        body    = f"Rule: {rule_name}\nCamera: {camera_id}\nObject: {obj_label}\nTime: {ts}"
    else:
        subject = f"⚠ Sentrix Alert: {rule_name}"
        body    = f"Rule: {rule_name}\nCamera: {camera_id}\nTime: {ts}\n\nEvent: {json.dumps(event, indent=2)}"

    # Email
    if actions.get("email"):
        with get_db_conn() as db:
            cfg = _load_config(db)
            if cfg.get("smtp_host"):
                asyncio.create_task(_send_email_logged(db, cfg, subject, body))

    # Webhook
    webhook_url = actions.get("webhook_url", "").strip()
    if webhook_url:
        asyncio.create_task(_send_webhook(webhook_url, {
            "rule": rule_name,
            "rule_type": rule_type,
            "camera_id": camera_id,
            "timestamp": ts,
            "event": event
        }))


async def _send_email(cfg: dict, subject: str, body: str):
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    host     = cfg.get("smtp_host", "")
    port     = int(cfg.get("smtp_port", 587))
    user     = cfg.get("smtp_user", "")
    password = cfg.get("smtp_password", "")
    from_    = cfg.get("smtp_from", user)
    to_list  = [t.strip() for t in cfg.get("smtp_to", "").split(",") if t.strip()]
    use_tls  = cfg.get("smtp_tls", "1") == "1"

    if not to_list:
        raise ValueError("No recipients configured")

    msg = MIMEMultipart()
    msg["From"]    = from_
    msg["To"]      = ", ".join(to_list)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    def _send():
        if use_tls:
            server = smtplib.SMTP(host, port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port)
        if user and password:
            server.login(user, password)
        server.sendmail(from_, to_list, msg.as_string())
        server.quit()

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send)


async def _send_email_logged(db, cfg: dict, subject: str, body: str):
    from ...core.database import get_db_conn
    import uuid
    log_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    recipients = cfg.get("smtp_to", "")
    try:
        await _send_email(cfg, subject, body)
        with get_db_conn() as db2:
            db2.execute("""
                INSERT INTO notification_log (id, channel, recipient, subject, status, error, sent_at)
                VALUES (?, 'email', ?, ?, 'sent', NULL, ?)
            """, (log_id, recipients, subject, now))
    except Exception as e:
        with get_db_conn() as db2:
            db2.execute("""
                INSERT INTO notification_log (id, channel, recipient, subject, status, error, sent_at)
                VALUES (?, 'email', ?, ?, 'failed', ?, ?)
            """, (log_id, recipients, subject, str(e)[:500], now))


async def _send_webhook(url: str, payload: dict):
    from ...core.database import get_db_conn
    import uuid
    log_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                status_ok = r.status < 400
        with get_db_conn() as db:
            db.execute("""
                INSERT INTO notification_log (id, channel, recipient, subject, status, error, sent_at)
                VALUES (?, 'webhook', ?, ?, ?, NULL, ?)
            """, (log_id, url, payload.get("rule","webhook"), "sent" if status_ok else "failed", now))
    except Exception as e:
        with get_db_conn() as db:
            db.execute("""
                INSERT INTO notification_log (id, channel, recipient, subject, status, error, sent_at)
                VALUES (?, 'webhook', ?, ?, 'failed', ?, ?)
            """, (log_id, url, payload.get("rule","webhook"), str(e)[:500], now))
