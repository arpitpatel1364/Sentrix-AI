import os
import sys
from pathlib import Path

# Add the current directory to path so 'app' can be imported
sys.path.append(str(Path(__file__).resolve().parent))

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
    from app.main import app
    
    print("\n╔══════════════════════════════════════╗")
    print("║   Sentrix-AI Backend Shim Loader     ║")
    print("╠══════════════════════════════════════╣")
    print("║  Launching from: backend/main.py    ║")
    print("╚══════════════════════════════════════╝\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
