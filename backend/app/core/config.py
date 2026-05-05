import os
from pathlib import Path

# Load .env from the backend directory (one level up from this file's core/ dir).
# Variables already set in the environment (e.g. Docker) always take precedence.
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=False)
except ImportError:
    pass  # python-dotenv not installed; rely on environment variables only

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
