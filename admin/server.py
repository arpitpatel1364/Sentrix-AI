"""
CCTV Face Recognition System - Server
======================================
Single-file FastAPI backend.

SETUP:
  pip install fastapi uvicorn python-multipart insightface opencv-python qdrant-client numpy Pillow bcrypt python-jose[cryptography] sse-starlette

RUN:
  python server.py

PUT YOUR MODEL:
  Place your YOLOv8 face detection model at: models/best.pt
  InsightFace recognition model is auto-downloaded on first run into: models/insightface/

CAMERA WORKER CONNECTION:
  Each worker runs worker_agent.py on their local machine (with the camera).
  They log in with their credentials, then the agent streams face crops to this server.
"""

import os, time, uuid, json, asyncio, io, sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from contextlib import asynccontextmanager

import numpy as np
import cv2
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request, status, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import bcrypt
from sse_starlette.sse import EventSourceResponse

# ── optional: insightface + qdrant ──
try:
    import insightface
    from insightface.app import FaceAnalysis
    FACE_MODEL_AVAILABLE = True
except ImportError:
    FACE_MODEL_AVAILABLE = False
    print("⚠  insightface not installed. Face recognition disabled.")

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    print("⚠  qdrant-client not installed. Using in-memory store.")

# ══════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production-please-123")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 12
SIMILARITY_THRESHOLD = 0.75   # cosine similarity — lower = stricter
BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
DATA_DIR = BASE_DIR / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
DB_PATH = DATA_DIR / "cctv.db"

MODELS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
SNAPSHOTS_DIR.mkdir(exist_ok=True)

# ══════════════════════════════════════════════
#  IN-MEMORY STORES (replace with DB in prod)
# ══════════════════════════════════════════════
# active SSE connections: { username: [asyncio.Queue, ...] }
SSE_CONNECTIONS: dict[str, List[asyncio.Queue]] = {}
ACTIVE_WORKERS: dict[str, float] = {} # { camera_id: last_seen_timestamp }
FACE_APP = None
QDRANT_CLIENT = None

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sightings (
                id TEXT PRIMARY KEY,
                camera_id TEXT,
                location TEXT,
                timestamp TEXT,
                uploaded_by TEXT,
                snapshot_path TEXT,
                matched BOOLEAN,
                person_id TEXT,
                person_name TEXT,
                confidence REAL,
                embedding BLOB
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS wanted (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                embedding BLOB,
                added_by TEXT,
                added_at TEXT
            )
        """)
        conn.commit()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ══════════════════════════════════════════════
#  STARTUP
# ══════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    global FACE_APP, QDRANT_CLIENT

    # init database
    init_db()

    # seed default admin if not exists
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT username FROM users WHERE username = 'admin'")
        if not cur.fetchone():
            _add_user("admin", "admin123", "admin")
            print("✓ Seeded default admin: admin/admin123")
        
        cur.execute("SELECT username FROM users WHERE username = 'worker1'")
        if not cur.fetchone():
            _add_user("worker1", "worker123", "worker")
            print("✓ Seeded default worker: worker1/worker123")

    # load face model
    if FACE_MODEL_AVAILABLE:
        try:
            # Auto-detect CUDA
            providers = ["CPUExecutionProvider"]
            try:
                import onnxruntime as ort
                if "CUDAExecutionProvider" in ort.get_available_providers():
                    providers = ["CUDAExecutionProvider"]
                    print("🚀 GPU Detected: Using CUDAExecutionProvider for face recognition")
                else:
                    print("ℹ  Using CPU for face recognition (onnxruntime-gpu not found)")
            except Exception:
                pass

            FACE_APP = FaceAnalysis(
                name="buffalo_s",
                root=str(MODELS_DIR / "insightface"),
                providers=providers
            )
            # Use smaller det_size for speed (we mostly get face crops from the worker anyway)
            FACE_APP.prepare(ctx_id=0, det_size=(160, 160))
            print(f"✓ InsightFace model loaded (buffalo_s, {providers[0]})")
        except Exception as e:
            print(f"⚠  Could not load InsightFace: {e}")

    # init qdrant
    if QDRANT_AVAILABLE:
        try:
            # Persistent local storage for vectors
            target_path = str(DATA_DIR / "qdrant_storage")
            QDRANT_CLIENT = QdrantClient(path=target_path)
            
            # check if collections exist, if not create
            cols = QDRANT_CLIENT.get_collections().collections
            col_names = [c.name for c in cols]
            
            if "sightings" not in col_names:
                QDRANT_CLIENT.create_collection("sightings", vectors_config=VectorParams(size=512, distance=Distance.COSINE))
            if "wanted" not in col_names:
                QDRANT_CLIENT.create_collection("wanted", vectors_config=VectorParams(size=512, distance=Distance.COSINE))
            
            print(f"✓ Qdrant persistent storage started at {target_path}")
        except Exception as e:
            print(f"⚠  Qdrant error: {e}")

    yield
    print("Server shutting down.")


app = FastAPI(title="CCTV System", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# Mount static files for face snapshots (using the route below instead for manual control)
if not SNAPSHOTS_DIR.exists():
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

security = HTTPBearer(auto_error=False)


# ══════════════════════════════════════════════
#  AUTH HELPERS
# ══════════════════════════════════════════════
def _add_user(username: str, password: str, role: str):
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                     (username, hashed, role))
        conn.commit()

def _verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def _create_token(username: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": username, "role": role, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    token = None
    if credentials:
        token = credentials.credentials
    else:
        # EventSource can't set headers — accept token as query param for SSE
        token = request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    data = _decode_token(token)
    return {"username": data["sub"], "role": data["role"]}

def require_admin(user=Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


# ══════════════════════════════════════════════
#  FACE RECOGNITION HELPERS
# ══════════════════════════════════════════════
def get_embedding(img_array: np.ndarray) -> Optional[np.ndarray]:
    if FACE_APP is None:
        return None
    # Use max_num=1 for faster extraction
    faces = FACE_APP.get(img_array)
    if not faces:
        return None
    largest = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1]))
    emb = largest.embedding
    return emb / np.linalg.norm(emb)

def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))

def match_wanted(embedding: np.ndarray) -> Optional[dict]:
    # 1. Qdrant (Fast Vector Search)
    if QDRANT_AVAILABLE and QDRANT_CLIENT:
        try:
            hits = QDRANT_CLIENT.search("wanted", query_vector=embedding.tolist(), limit=1)
            if hits and hits[0].score >= SIMILARITY_THRESHOLD:
                return {"person": {"id": hits[0].id, "name": hits[0].payload["name"]}, "confidence": round(hits[0].score * 100, 1)}
        except Exception as e:
            print(f"Qdrant search error: {e}")
            
    # 2. SQLite Fallback
    with get_db() as conn:
        rows = conn.execute("SELECT id, name, embedding FROM wanted").fetchall()
        
    best_score, best_person = 0.0, None
    for r in rows:
        if r["embedding"]:
            score = cosine_sim(embedding, np.frombuffer(r["embedding"], dtype=np.float32))
            if score > best_score:
                best_score, best_person = score, {"id": r["id"], "name": r["name"]}
                
    if best_score >= SIMILARITY_THRESHOLD and best_person:
        return {"person": best_person, "confidence": round(best_score * 100, 1)}
    return None

def bytes_to_cv2(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)

def cv2_to_b64(img: np.ndarray) -> str:
    import base64
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode()

def get_snapshot_b64(filename: str) -> str:
    path = SNAPSHOTS_DIR / filename
    if not path.exists(): return ""
    import base64
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


# ══════════════════════════════════════════════
#  ALERT BROADCAST
# ══════════════════════════════════════════════
async def broadcast_alert(payload: dict):
    for queues in SSE_CONNECTIONS.values():
        for q in queues:
            try: await q.put(payload)
            except: pass


# ══════════════════════════════════════════════
#  API ROUTES
# ══════════════════════════════════════════════

# ── Auth ──
@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT password_hash, role FROM users WHERE username = ?", (username,))
        user = cur.fetchone()
        
    if not user or not _verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = _create_token(username, user["role"])
    return {"token": token, "username": username, "role": user["role"]}

@app.post("/api/logout")
async def logout(user=Depends(get_current_user)):
    SSE_CONNECTIONS.pop(user["username"], None)
    return {"ok": True}

# ── SSE stream ──
@app.get("/api/stream")
async def sse_stream(request: Request, user=Depends(require_admin)):
    queue = asyncio.Queue()
    if user["username"] not in SSE_CONNECTIONS:
        SSE_CONNECTIONS[user["username"]] = []
    SSE_CONNECTIONS[user["username"]].append(queue)

    async def generator():
        # send connected ping
        yield {"event": "connected", "data": json.dumps({"user": user["username"]})}
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {"event": "alert", "data": json.dumps(payload)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            if user["username"] in SSE_CONNECTIONS:
                if queue in SSE_CONNECTIONS[user["username"]]:
                    SSE_CONNECTIONS[user["username"]].remove(queue)
                if not SSE_CONNECTIONS[user["username"]]:
                    SSE_CONNECTIONS.pop(user["username"])

    return EventSourceResponse(generator())

# ── Upload frame (worker) ──
def _save_sighting_task(sighting_id: str, img: np.ndarray, sighting: dict, embedding: np.ndarray, camera_id: str, location: str, ts: str):
    """Background task to handle heavy I/O operations."""
    try:
        # 1. Save snapshot to disk (in a camera-specific folder)
        cam_dir = SNAPSHOTS_DIR / camera_id
        cam_dir.mkdir(parents=True, exist_ok=True)
        
        filename = sighting["snapshot_path"] # This now includes camera_id/ prefix
        snapshot_path = SNAPSHOTS_DIR / filename
        cv2.imwrite(str(snapshot_path), img, [cv2.IMWRITE_JPEG_QUALITY, 70]) 
        
        # 2. Store in Qdrant
        if QDRANT_AVAILABLE and QDRANT_CLIENT:
            QDRANT_CLIENT.upsert(
                collection_name="sightings",
                points=[PointStruct(
                    id=sighting_id,
                    vector=embedding.tolist(),
                    payload={
                        "camera_id": camera_id,
                        "location": location,
                        "timestamp": ts,
                        "person_id": sighting["person_id"],
                        "person_name": sighting["person_name"]
                    }
                )]
            )
    except Exception as e:
        print(f"Error in background task: {e}")

@app.post("/api/upload-frame")
async def upload_frame(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    camera_id: str = Form("cam-1"),
    location: str = Form("unknown"),
    user=Depends(get_current_user)
):
    # Record heartbeat with composite key (username:camera_id) to avoid collisions
    node_key = f"{user['username']}:{camera_id}"
    ACTIVE_WORKERS[node_key] = time.time()
    
    data = await file.read()
    img = bytes_to_cv2(data)
    if img is None:
        raise HTTPException(status_code=400, detail="Invalid image")

    embedding = get_embedding(img)
    if embedding is None:
        return {"status": "no_face"}

    result = match_wanted(embedding)
    sighting_id = str(uuid.uuid4())
    ts = datetime.utcnow().isoformat()
    # Save in subfolder matching the camera ID
    filename = f"{camera_id}/{sighting_id}.jpg"
    
    # helper to get b64 for SSE (keeps dashboard snappy)
    snapshot_b64 = cv2_to_b64(img)

    sighting = {
        "id": sighting_id,
        "camera_id": camera_id,
        "location": location,
        "timestamp": ts,
        "uploaded_by": user["username"],
        "snapshot_path": filename,
        "matched": False,
        "person_name": "Unknown",
        "person_id": None,
        "confidence": 0.0
    }

    if result:
        sighting["matched"] = True
        sighting["person_name"] = result["person"]["name"]
        sighting["person_id"] = result["person"]["id"]
        sighting["confidence"] = result["confidence"]
        
    # 1. Save to DB synchronously for dashboard consistency
    emb_blob = embedding.astype(np.float32).tobytes()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO sightings (id, camera_id, location, timestamp, uploaded_by, snapshot_path, matched, person_id, person_name, confidence, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sighting["id"], sighting["camera_id"], sighting["location"], sighting["timestamp"],
            sighting["uploaded_by"], sighting["snapshot_path"], sighting["matched"],
            sighting["person_id"], sighting["person_name"], sighting["confidence"],
            emb_blob
        ))
        conn.commit()

    # 2. Schedule heavy I/O tasks for background
    background_tasks.add_task(_save_sighting_task, sighting_id, img, sighting, embedding, camera_id, location, ts)

    if result:
        # broadcast a full alert (with image) to all users
        await broadcast_alert({
            "type": "wanted_match",
            "id": sighting_id,
            "person_name": result["person"]["name"],
            "confidence": result["confidence"],
            "camera_id": camera_id,
            "location": location,
            "timestamp": ts,
            "snapshot": snapshot_b64,
        })
        return {"status": "match", "person": result["person"]["name"], "confidence": result["confidence"]}
    else:
        # broadcast a full update (with image) so they see it in the log
        await broadcast_alert({
            "type": "new_sighting",
            "matched": False,
            "timestamp": ts,
            "camera_id": camera_id,
            "location": location,
            "snapshot": snapshot_b64
        })
        return {"status": "stored", "matched": False}

# ── Search by face (query) ──
@app.post("/api/search-face")
async def search_face(file: UploadFile = File(...), user=Depends(require_admin)):
    data = await file.read()
    img = bytes_to_cv2(data)
    embedding = get_embedding(img)
    if embedding is None:
        return {"results": [], "message": "No face detected"}

    found = match_wanted(embedding)
    person_display = "Unknown Person"
    if found:
        person_display = found["person"]["name"]

    last3 = []
    
    # 1. Faster/Universal Search via Qdrant
    if QDRANT_AVAILABLE and QDRANT_CLIENT:
        try:
            hits = QDRANT_CLIENT.search(
                collection_name="sightings",
                query_vector=embedding.tolist(),
                limit=3
            )
            for hit in hits:
                # Get full details from SQLite by hit.id
                with get_db() as conn:
                    cur = conn.cursor()
                    # Select only needed columns to avoid binary data leakage
                    cur.execute("""
                        SELECT id, camera_id, location, timestamp, snapshot_path, matched, person_id, person_name, confidence 
                        FROM sightings WHERE id = ?
                    """, (hit.id,))
                    r = cur.fetchone()
                    if r:
                        item = dict(r)
                        item["snapshot"] = f"/api/snapshots/{item['snapshot_path']}"
                        # If Qdrant hit has a high score, use it for confidence
                        item["confidence"] = round(hit.score * 100, 1)
                        last3.append(item)
        except Exception as e:
            print(f"Qdrant history search error: {e}")

    # 2. Fallback to SQL if Qdrant empty or unavailable (only if matched a person)
    if not last3 and found:
        pid = found["person"]["id"]
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, camera_id, location, timestamp, snapshot_path, matched, person_id, person_name, confidence 
                FROM sightings WHERE person_id = ? ORDER BY timestamp DESC LIMIT 3
            """, (pid,))
            rows = cur.fetchall()
            for r in rows:
                item = dict(r)
                item["snapshot"] = f"/api/snapshots/{item['snapshot_path']}"
                last3.append(item)

    if not last3:
        return {"found": False, "last_3_locations": []}

    return {"found": True, "person": person_display, "last_3_locations": last3}

# ── Wanted list ──
@app.get("/api/wanted")
async def get_wanted(user=Depends(require_admin)):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, added_by, added_at FROM wanted ORDER BY added_at DESC")
        return [dict(r) for r in cur.fetchall()]

@app.post("/api/wanted")
async def add_wanted(
    file: UploadFile = File(...),
    name: str = Form(...),
    user=Depends(require_admin)
):
    data = await file.read()
    img = bytes_to_cv2(data)
    embedding = get_embedding(img)
    if embedding is None:
        raise HTTPException(status_code=400, detail="No face detected in photo")

    pid = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    name_str = name.strip()

    # Store in SQLite (including embedding as BLOB)
    emb_blob = embedding.astype(np.float32).tobytes()
    with get_db() as conn:
        conn.execute("INSERT INTO wanted (id, name, embedding, added_by, added_at) VALUES (?, ?, ?, ?, ?)",
                     (pid, name_str, emb_blob, user["username"], now))
        conn.commit()

    # Store in Qdrant (fast lookup)
    if QDRANT_AVAILABLE and QDRANT_CLIENT:
        QDRANT_CLIENT.upsert(
            collection_name="wanted",
            points=[PointStruct(id=pid, vector=embedding.tolist(), payload={"name": name_str})]
        )

    return {"ok": True, "id": pid, "name": name_str}

@app.delete("/api/wanted/{person_id}")
async def remove_wanted(person_id: str, user=Depends(require_admin)):
    with get_db() as conn:
        conn.execute("DELETE FROM wanted WHERE id = ?", (person_id,))
        conn.commit()
    
    if QDRANT_AVAILABLE and QDRANT_CLIENT:
        QDRANT_CLIENT.delete(collection_name="wanted", points_selector=[person_id])
        
    return {"ok": True}

# ── Sightings ──
@app.get("/api/sightings")
async def get_sightings(limit: int = 50, user=Depends(require_admin)):
    with get_db() as conn:
        cur = conn.cursor()
        
        # 1. Get official global count
        cur.execute("SELECT COUNT(*) FROM sightings")
        total_count = cur.fetchone()[0]

        # 2. Get records (without binary embeddings)
        cur.execute("""
            SELECT id, camera_id, location, timestamp, uploaded_by, snapshot_path, matched, person_id, person_name, confidence 
            FROM sightings ORDER BY timestamp DESC LIMIT ?
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["snapshot"] = f"/api/snapshots/{r['snapshot_path']}"
        return {"sightings": rows, "total_count": total_count}
        
@app.get("/api/snapshots/{path:path}")
async def get_snapshot(path: str):
    full_path = SNAPSHOTS_DIR / path
    if not full_path.exists():
        raise HTTPException(status_code=404)
    return StreamingResponse(open(full_path, "rb"), media_type="image/jpeg")

# ── Users (admin) ──
@app.get("/api/users")
async def get_users(user=Depends(require_admin)):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT username, role FROM users")
        return [dict(r) for r in cur.fetchall()]

@app.post("/api/users")
async def create_user(request: Request, user=Depends(require_admin)):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    role = body.get("role", "worker")
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT username FROM users WHERE username = ?", (username,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="User already exists")
    if role not in ("admin", "worker"):
        raise HTTPException(status_code=400, detail="Role must be admin or worker")
    _add_user(username, password, role)
    return {"ok": True, "username": username, "role": role}

@app.delete("/api/users/{username}")
async def delete_user(username: str, user=Depends(require_admin)):
    if username == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete main admin")
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()
    return {"ok": True}
        
# ── Active users ──
@app.get("/api/active-users")
async def active_users(user=Depends(require_admin)):
    now = time.time()
    # 1. Sessions (People looking at dashboard)
    sessions = list(SSE_CONNECTIONS.keys())
    
    # 2. Nodes (Cameras sending frames)
    # Filter only those that checked in within the last 60 seconds
    live_nodes = []
    for cam_id, last_seen in list(ACTIVE_WORKERS.items()):
        if now - last_seen < 60:
            live_nodes.append(cam_id)
        else:
            ACTIVE_WORKERS.pop(cam_id, None)

    return {
        "sessions": sessions,
        "nodes": live_nodes,
        "count": len(live_nodes)
    }

# ── Worker Stats (Self-Monitor) ──
@app.get("/api/worker/stats")
async def worker_stats(user=Depends(get_current_user)):
    """Allows a worker to see their own node's activity for dashboard feedback."""
    with get_db() as conn:
        cur = conn.cursor()
        # Get count and last 5 images for THIS user
        cur.execute("""
            SELECT id, camera_id, location, timestamp, snapshot_path 
            FROM sightings WHERE uploaded_by = ? ORDER BY timestamp DESC LIMIT 5
        """, (user["username"],))
        history = [dict(r) for r in cur.fetchall()]
        for h in history:
            h["snapshot"] = f"/api/snapshots/{h['snapshot_path']}"
            
        cur.execute("SELECT COUNT(*) FROM sightings WHERE uploaded_by = ?", (user["username"],))
        total_count = cur.fetchone()[0]
        
        return {
            "total_detections": total_count,
            "recent_history": history,
            "is_active": any(k.startswith(f"{user['username']}:") for k in ACTIVE_WORKERS.keys())
        }
@app.post("/api/system/reset")
async def system_reset(user=Depends(require_admin)):
    """Wipe all history, wanted targets, and surveillance data for a fresh start."""
    try:
        # 1. Clear SQLite
        with get_db() as conn:
            conn.execute("DELETE FROM sightings")
            conn.execute("DELETE FROM wanted")
            # Clear all workers but keep admin
            conn.execute("DELETE FROM users WHERE username != 'admin'")
            # Re-seed default worker if needed
            conn.commit()
        
        _add_user("worker1", "worker123", "worker")

        # 2. Clear Qdrant
        if QDRANT_AVAILABLE and QDRANT_CLIENT:
            try:
                QDRANT_CLIENT.delete_collection("sightings")
                QDRANT_CLIENT.delete_collection("wanted")
                # Re-create
                QDRANT_CLIENT.create_collection("sightings", vectors_config=VectorParams(size=512, distance=Distance.COSINE))
                QDRANT_CLIENT.create_collection("wanted", vectors_config=VectorParams(size=512, distance=Distance.COSINE))
            except Exception as e:
                print(f"Qdrant reset error: {e}")

        # 3. Clear Snapshots (including all sub-folders)
        import shutil
        if SNAPSHOTS_DIR.exists():
            for item in SNAPSHOTS_DIR.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

        return {"ok": True, "message": "System reset successfully. All data cleared."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")

# ══════════════════════════════════════════════
#  SERVE FRONTEND (dashboard.html)
# ══════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    html_path = BASE_DIR / "dashboard.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse(f"<h2>dashboard.html not found at {html_path}</h2>")


if __name__ == "__main__":
    import uvicorn
    print("\n╔══════════════════════════════════════╗")
    print("║   CCTV Face Recognition System       ║")
    print("╠══════════════════════════════════════╣")
    print("║  Dashboard → http://localhost:8000   ║")
    print("║  Admin     → admin / admin123        ║")
    print("║  Worker    → worker1 / worker123     ║")
    print("╚══════════════════════════════════════╝\n")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
