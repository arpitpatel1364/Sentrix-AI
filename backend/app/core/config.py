import os
from pathlib import Path

# --- Auth Configuration ---
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production-please-123")
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

# Ensure directories exist
MODELS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
SNAPSHOTS_DIR.mkdir(exist_ok=True)
INTEL_DIR.mkdir(exist_ok=True)
