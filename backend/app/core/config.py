import os
from pathlib import Path

# --- Auth Configuration ---
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production-please-123")
MEDIA_SECRET_KEY = os.getenv("MEDIA_SECRET_KEY", "sentrix-media-secret-999")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 12

# --- Face Recognition Configuration ---
SIMILARITY_THRESHOLD = 0.75  # cosine similarity — lower = stricter
DEVICE = os.getenv("DEVICE", "cpu")  # "cpu" or "cuda"

# --- Directory Paths ---
BASE_DIR = Path(__file__).resolve().parent.parent.parent
APP_DIR = BASE_DIR / "app"
MODELS_DIR = BASE_DIR / "models"
DATA_DIR = BASE_DIR / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
INTEL_DIR = DATA_DIR / "intel_photos"
DB_PATH = DATA_DIR / "cctv.db"
# DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DB_PATH}")
# Use this format for PostgreSQL
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql+asyncpg://postgres:arpit123@localhost:8080/sentrix_admin_db"
)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


# Ensure directories exist
MODELS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
SNAPSHOTS_DIR.mkdir(exist_ok=True)
INTEL_DIR.mkdir(exist_ok=True)
