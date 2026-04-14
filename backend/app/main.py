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
from app.features.clients.router import router as clients_router
from app.features.inference.router import router as inference_router

async def lifespan(app: FastAPI):
    # Initialize Core
    await init_db()
    await seed_default_users()
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

# --- API Route Grouping (All under /api) ---
api_app = FastAPI(title="Sentrix-AI API")

api_app.include_router(auth_router)
api_app.include_router(watchlist_router)
api_app.include_router(sightings_router)
api_app.include_router(workers_router)
api_app.include_router(system_router, prefix="") # system_router already has /api internally, but we mount it in api_app
api_app.include_router(sse_router)
api_app.include_router(objects_router, prefix="") 
api_app.include_router(analysis_router)
api_app.include_router(cameras_router)
api_app.include_router(analytics_router, prefix="")
api_app.include_router(roi_router, prefix="")
api_app.include_router(alert_rules_router, prefix="")
api_app.include_router(notifications_router, prefix="")
api_app.include_router(cleanup_router, prefix="")
api_app.include_router(audit_router, prefix="")
api_app.include_router(stop_router)
api_app.include_router(clients_router, prefix="")
api_app.include_router(inference_router, prefix="")

app.mount("/api", api_app)

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
async def root():
    # Primary entry point — will redirect via JS auth guard if needed
    static_file = Path(__file__).resolve().parent / "static" / "dashboard.html"
    return HTMLResponse(static_file.read_text(encoding="utf-8"))

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    static_file = Path(__file__).resolve().parent / "static" / "login.html"
    return HTMLResponse(static_file.read_text(encoding="utf-8"))

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    static_file = Path(__file__).resolve().parent / "static" / "dashboard.html"
    return HTMLResponse(static_file.read_text(encoding="utf-8"))

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    static_file = Path(__file__).resolve().parent / "static" / "admin.html"
    return HTMLResponse(static_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn
    # Important: 0.0.0.0 allows access from other devices on the LAN
    print("[*] Sentrix-AI Backend running on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
