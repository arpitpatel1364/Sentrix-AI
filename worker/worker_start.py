import os
import sys
import time
import httpx
import asyncio
import threading
import subprocess
from dotenv import load_dotenv
from pathlib import Path

import argparse

# Load environment variables
load_dotenv()

# Setup Argument Parser
parser = argparse.ArgumentParser(description="Sentrix-AI Worker Node Startup")
parser.add_argument("--hub-url", default=os.getenv("HUB_URL"), help="Hub URL (e.g. http://localhost:8000)")
parser.add_argument("--api-key", default=os.getenv("CLIENT_API_KEY"), help="Worker API Key")
parser.add_argument("--label", default=os.getenv("WORKER_LABEL"), help="Human-readable label for this node")
parser.add_argument("--media-port", default=os.getenv("MEDIA_SERVER_PORT", "8765"), help="Local port for media server")
args = parser.parse_args()

HUB_URL = args.hub_url
CLIENT_API_KEY = args.api_key
WORKER_LABEL = args.label
MEDIA_SERVER_PORT = args.media_port
CAMERA_URLS = os.getenv("CAMERA_URLS", "")
CAMERA_NAMES = os.getenv("CAMERA_NAMES", "")
SNAPSHOT_DIR = os.getenv("SNAPSHOT_DIR")
if not SNAPSHOT_DIR:
    SNAPSHOT_DIR = str(Path(__file__).resolve().parent.parent / "data" / "snapshots")
 
# Default to local data dir instead of /app in non-docker env
if not Path(SNAPSHOT_DIR).is_absolute():
    SNAPSHOT_DIR = str(Path(__file__).resolve().parent.parent / "data" / "snapshots")

# Global state
worker_data = {
    "worker_id": None,
    "qdrant_collection": None,
    "camera_statuses": {}
}

def check_env():
    missing = []
    if not HUB_URL: missing.append("HUB_URL")
    if not CLIENT_API_KEY: missing.append("CLIENT_API_KEY")
    if not WORKER_LABEL: missing.append("WORKER_LABEL")
    
    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

async def register_with_hub():
    """
    POST {HUB_URL}/workers/register
    Headers: Authorization: Bearer {CLIENT_API_KEY}
    """
    print(f"[*] Registering worker '{WORKER_LABEL}' with Hub at {HUB_URL}...")
    
    # Get local IP (simplified for docker)
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "localhost"

    cameras = []
    urls = [u.strip() for u in CAMERA_URLS.split(",") if u.strip()]
    names = [n.strip() for n in CAMERA_NAMES.split(",") if n.strip()]
    
    for i in range(max(len(urls), len(names))):
        name = names[i] if i < len(names) else f"Camera {i+1}"
        url = urls[i] if i < len(urls) else "0"
        cameras.append({"name": name, "rtsp_url": url})
        worker_data["camera_statuses"][name] = "offline"

    payload = {
        "label": WORKER_LABEL,
        "media_base_url": f"http://{local_ip}:{MEDIA_SERVER_PORT}",
        "cameras": cameras
    }

    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(
                f"{HUB_URL}/api/workers/register",
                headers={"Authorization": f"Bearer {CLIENT_API_KEY}"},
                json=payload,
                timeout=20
            )
            r.raise_for_status()
            data = r.json()
            worker_data["worker_id"] = data["worker_id"]
            worker_data["qdrant_collection"] = data["qdrant_collection"]
            worker_data["camera_mapping"] = data.get("camera_mapping", {})
            print(f"[+] Registered successfully. Worker ID: {worker_data['worker_id']}")
        except Exception as e:
            print(f"[ERR] Registration failed: {e}")
            sys.exit(1)

async def heartbeat_loop():
    """
    Every 30 seconds:
    POST {HUB_URL}/workers/{worker_id}/heartbeat
    """
    print("[*] Heartbeat loop started.")
    while True:
        if worker_data["worker_id"]:
            async with httpx.AsyncClient() as client:
                try:
                    await client.post(
                        f"{HUB_URL}/api/workers/{worker_data['worker_id']}/heartbeat",
                        headers={"Authorization": f"Bearer {CLIENT_API_KEY}"},
                        json={"camera_statuses": worker_data["camera_statuses"]},
                        timeout=10
                    )
                except Exception as e:
                    print(f"[WARN] Heartbeat failed: {e}")
        await asyncio.sleep(30)

def start_media_server():
    print("[*] Starting Media Server...")
    subprocess.Popen([sys.executable, "worker/media_server.py"])

def start_worker_agent():
    print("[*] Starting Worker Agent...")
    # These will be passed as env vars or args to worker_agent.py
    os.environ["HUB_WORKER_ID"] = worker_data["worker_id"]
    os.environ["HUB_QDRANT_COLLECTION"] = worker_data["qdrant_collection"]
    
    import json
    os.environ["HUB_CAMERA_MAPPING"] = json.dumps(worker_data.get("camera_mapping", {}))
    
    os.environ["SNAPSHOT_DIR"] = str(SNAPSHOT_DIR)
    
    subprocess.Popen([sys.executable, "worker/worker_agent.py"])

async def main():
    check_env()
    await register_with_hub()
    
    start_media_server()
    
    # Start heartbeat in background
    asyncio.create_task(heartbeat_loop())
    
    start_worker_agent()
    
    # Keep main alive
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Worker stopping...")
        sys.exit(0)
