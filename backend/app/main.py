import os
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

# Add parent directory to path to allow absolute imports
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.core.config import BASE_DIR, DATA_DIR, SNAPSHOTS_DIR
from app.core.database import init_db, seed_default_users
from app.core.face_engine import init_face_engines
from app.features.auth.router import router as auth_router
from app.features.watchlist.router import router as watchlist_router
from app.features.sightings.router import router as sightings_router
from app.features.workers.router import router as workers_router
from app.features.system.router import router as system_router
from app.features.sse.router import router as sse_router
from app.features.objects.router import router as objects_router
from app.features.analysis.router import router as analysis_router
from app.features.cameras.router import router as cameras_router
from app.features.analytics.router import router as analytics_router
from app.features.alert_rules.router import router as alert_rules_router
from app.features.notifications.router import router as notifications_router
from app.features.roi.router import router as roi_router
from app.features.system.cleanup import router as cleanup_router
from app.features.audit_log.router import router as audit_router
from app.features.stop_requests.router import router as stop_router

async def lifespan(app: FastAPI):
    # Initialize Core
    init_db()
    seed_default_users()
    init_face_engines()
    
    # Init Object Engine for manual analysis
    from app.core.object_engine import init_object_engine
    init_object_engine()
    
    yield
    print("Sentrix-AI Server shutting down.")

app = FastAPI(title="Sentrix-AI CCTV System", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Route Mounting
app.include_router(auth_router)
app.include_router(watchlist_router)
app.include_router(sightings_router)
app.include_router(workers_router)
app.include_router(system_router)
app.include_router(sse_router)
app.include_router(objects_router)
app.include_router(analysis_router)
app.include_router(cameras_router)
app.include_router(analytics_router)
app.include_router(roi_router)
app.include_router(alert_rules_router)
app.include_router(notifications_router)
app.include_router(cleanup_router)
app.include_router(audit_router)
app.include_router(stop_router)

# --- STATIC & SNAPSHOT SERVING ---
# Ensure these exist before mounting
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)

# Mount /api/snapshots to SNAPSHOTS_DIR
app.mount("/api/snapshots", StaticFiles(directory=str(SNAPSHOTS_DIR)), name="snapshots")
# Mount /static to the static folder for CSS/JS/Assets
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    # Use absolute path relative to this file
    static_file = Path(__file__).resolve().parent / "static" / "index.html"
    if static_file.exists():
        return HTMLResponse(static_file.read_text(encoding="utf-8"))
    return HTMLResponse(f"<h2>index.html not found!</h2>")

if __name__ == "__main__":
    import uvicorn
    # Important: 0.0.0.0 allows access from other devices on the LAN
    print("[*] Sentrix-AI Backend running on http://[IP_ADDRESS]")
    uvicorn.run(app, host="[IP_ADDRESS]", port=8000)
