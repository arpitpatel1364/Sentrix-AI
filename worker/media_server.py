import os
import time
import cv2
import numpy as np
from fastapi import FastAPI, Query, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path
from dotenv import load_dotenv
from insightface.app import FaceAnalysis
from jose import jwt

load_dotenv()

app = FastAPI(title="Sentrix Worker Media Server")

SNAPSHOT_DIR = os.getenv("SNAPSHOT_DIR", "/app/snapshots")
WORKER_LABEL = os.getenv("WORKER_LABEL", "Worker")
SECRET_KEY = os.getenv("MEDIA_SECRET_KEY", os.getenv("CLIENT_API_KEY", "sentrix-media-secret-999")) 

# Load Face Model for embedding computing
# This is heavy, but needed for Enrollment via Dashboard
print("[*] Loading Face Analysis model for remote embedding computation...")
try:
    # We use a try-except because on some environments the models might not be there
    face_app = FaceAnalysis(name='buffalo_l', root='/app/models')
    face_app.prepare(ctx_id=-1, det_size=(640, 640)) # Use CPU by default for media server
except Exception as e:
    print(f"[ERR] Failed to load FaceAnalysis: {e}")
    face_app = None

def validate_token(token: str):
    """Validate short-lived signed token from Hub."""
    if not token:
        raise HTTPException(status_code=401, detail="Token required")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload
    except Exception:
        # Fallback to direct comparison if it matches the API Key (useful for debugging)
        if token == SECRET_KEY:
            return {"sub": "root"}
        raise HTTPException(status_code=403, detail="Invalid or expired media token")

@app.post("/compute-embedding")
async def compute_embedding(
    file: UploadFile = File(...),
    token: str = Query(...)
):
    """
    Called by client dashboard when adding a person to watchlist.
    Accepts a face photo, returns 512-dim embedding.
    """
    validate_token(token)
    
    if not face_app:
        raise HTTPException(status_code=503, detail="Face detection model not available on this worker")

    try:
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            raise HTTPException(status_code=422, detail="Invalid image format")

        faces = face_app.get(img)
        
        if len(faces) == 0:
            raise HTTPException(status_code=422, detail="No face detected in image")
        if len(faces) > 1:
            raise HTTPException(status_code=422, detail="Multiple faces detected. Upload a single face photo.")

        embedding = faces[0].embedding.tolist()
        return {"embedding": embedding}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/snapshots/{snapshot_path:path}")
async def serve_snapshot(snapshot_path: str, token: str = Query(...)):
    """
    Serve a snapshot image file from local storage.
    """
    validate_token(token)

    full_path = Path(SNAPSHOT_DIR) / snapshot_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Snapshot not found")
    
    return FileResponse(str(full_path))

@app.get("/stream/{camera_index}")
async def mjpeg_stream(camera_index: int, token: str = Query(...)):
    """
    Stream live MJPEG from camera (index based).
    Note: Real implementation requires hook into worker_agent's frame buffer.
    """
    validate_token(token)
    raise HTTPException(status_code=501, detail="Live stream via Media Server pending integration with worker_agent")

@app.get("/health")
async def health():
    return {
        "status": "online",
        "worker_label": WORKER_LABEL,
        "uptime_seconds": int(time.time()),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("MEDIA_SERVER_PORT", 8765))
    uvicorn.run(app, host="0.0.0.0", port=port)
