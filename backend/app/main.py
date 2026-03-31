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

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    # Use absolute path relative to this file
    static_file = Path(__file__).resolve().parent / "static" / "dashboard.html"
    if static_file.exists():
        return HTMLResponse(static_file.read_text())
    return HTMLResponse(f"<h2>dashboard.html not found!</h2>")

if __name__ == "__main__":
    import uvicorn
    print("\n╔══════════════════════════════════════╗")
    print("║   Sentrix-AI Restructured Backend    ║")
    print("╠══════════════════════════════════════╣")
    print("║  Dashboard → http://localhost:8000   ║")
    print("╚══════════════════════════════════════╝\n")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
