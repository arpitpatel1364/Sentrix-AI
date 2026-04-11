import os
import sys
from pathlib import Path

# Backend initialization setup

# --- CUDA SELF-HEALING ENVIRONMENT (Mirroring Worker Logic) ---
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
LIBS_PATH = str(PROJECT_ROOT / "libs")

if LIBS_PATH not in os.environ.get("LD_LIBRARY_PATH", ""):
    os.environ["LD_LIBRARY_PATH"] = LIBS_PATH + ":" + os.environ.get("LD_LIBRARY_PATH", "")
    try:
        if sys.platform.startswith('linux'):
            # Optimization for low-VRAM systems
            if "PYTORCH_CUDA_ALLOC_CONF" not in os.environ:
                os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
            # Re-exec to apply LD_LIBRARY_PATH
            os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception:
        pass

# Add the current directory to path so 'app' can be imported
sys.path.append(str(BASE_DIR))

# Import the FastAPI app at module level so 'uvicorn backend.main:app' works
try:
    from app.main import app
except ImportError:
    # If we are just running for the first time or path is wrong, 
    # we don't want to crash immediately if dependencies are missing
    app = None

# Check for virtual environment
if not hasattr(sys, 'real_prefix') and sys.base_prefix == sys.prefix:
    # We are likely NOT in a virtual environment
    try:
        import uvicorn
    except ImportError:
        print("\n\033[91mERR: Required dependencies (uvicorn) not found in system python.\033[0m")
        print("\033[93mTIP: Please run the server using your virtual environment:\033[0m")
        print("\n    \033[1m./venv/bin/python3 backend/main.py\033[0m\n")
        sys.exit(1)

if __name__ == "__main__":
    import uvicorn
    if app is None:
        print("\n\033[91mERR: Could not import FastAPI app. Check your installation.\033[0m")
        sys.exit(1)
    
    print("\n╔══════════════════════════════════════╗")
    print("║   Sentrix-AI Backend Shim Loader     ║")
    print("╠══════════════════════════════════════╣")
    print("║  Launching from: backend/main.py    ║")
    print("╚══════════════════════════════════════╝\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
