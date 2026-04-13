import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
LIBS_PATH = str(PROJECT_ROOT / "libs")

if LIBS_PATH not in os.environ.get("LD_LIBRARY_PATH", ""):
    os.environ["LD_LIBRARY_PATH"] = LIBS_PATH + ":" + os.environ.get("LD_LIBRARY_PATH", "")
    try:
        if sys.platform.startswith('linux'):
            if "PYTORCH_CUDA_ALLOC_CONF" not in os.environ:
                os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
            os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception:
        pass

sys.path.append(str(BASE_DIR))

try:
    from app.main import app
except ImportError:
    app = None

if __name__ == "__main__":
    import uvicorn
    if app is None:
        print("ERR: Could not import FastAPI app. Check dependencies.")
        sys.exit(1)
    
    print("[*] Sentrix-AI Backend starting on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)


