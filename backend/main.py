import os
import sys
from pathlib import Path

# Add the current directory to path so 'app' can be imported
sys.path.append(str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    import uvicorn
    # Importing from app.main to reuse the FastAPI app and lifespan
    from app.main import app
    
    print("\n╔══════════════════════════════════════╗")
    print("║   Sentrix-AI Backend Shim Loader     ║")
    print("╠══════════════════════════════════════╣")
    print("║  Launching from: backend/main.py    ║")
    print("╚══════════════════════════════════════╝\n")
    
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
