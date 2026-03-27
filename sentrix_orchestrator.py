import subprocess
import time
import sys
import os
import signal
import json
from pathlib import Path

# ==========================================
# SENTRIX MULTI-NODE ORCHESTRATOR
# ==========================================
# This script manages multiple camera workers 
# for both Admin and Worker accounts.
# ==========================================

# CONFIGURATION: Load from nodes.conf
def load_nodes():
    nodes = []
    conf_path = Path("nodes.conf")
    if not conf_path.exists():
        print(f"❌ ERROR: {conf_path} not found!")
        return []
    
    with open(conf_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 5:
                nodes.append({
                    "id": parts[0],
                    "location": parts[1],
                    "camera_index": parts[2],
                    "username": parts[3],
                    "password": parts[4]
                })
    return nodes

CAMERA_NODES = load_nodes()

SERVER_URL = "http://localhost:8000"
VENV_PYTHON = "./venv/bin/python3"  # Adjust if your venv is named differently

# ==========================================

processes = {}

def signal_handler(sig, frame):
    print("\n\n🛑 SHUTDOWN SIGNAL RECEIVED")
    print("Stopping all camera nodes...")
    for node_id, p in processes.items():
        print(f"  - Terminating {node_id}...")
        p.terminate()
    print("👋 All nodes offline. System safe.")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def main():
    print("╔════════════════════════════════════════════╗")
    print("║      SENTRIX ORCHESTRATOR v1.0             ║")
    print("╠════════════════════════════════════════════╣")
    print(f"║ Nodes to start: {len(CAMERA_NODES):<26} ║")
    print("╚════════════════════════════════════════════╝\n")

    # Check if worker_agent.py exists
    if not Path("worker_agent.py").exists():
        print("❌ ERROR: worker_agent.py not found in this directory!")
        return

    # Use system python if venv not found
    python_exe = VENV_PYTHON if Path(VENV_PYTHON).exists() else sys.executable
    if python_exe == sys.executable:
        print(f"⚠️  Virtual environment not found at {VENV_PYTHON}. Using system python.")

    for node in CAMERA_NODES:
        node_id = node["id"]
        print(f"🛰️  Deploying Node: {node_id:<15} | Location: {node['location']}")
        
        cmd = [
            python_exe, "worker_agent.py",
            "--server", SERVER_URL,
            "--user", node["username"],
            "--password", node["password"],
            "--camera", node["camera_index"],
            "--camera-id", node_id,
            "--location", node["location"]
        ]

        # Use subprocess.DEVNULL for stdin to prevent issues, but keep stdout/err for logs
        try:
            p = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            processes[node_id] = p
            print(f"   ✅ Node active (PID: {p.pid})\n")
            time.sleep(2)  # Space out logins to prevent server spikes
        except Exception as e:
            print(f"   ❌ Failed to start {node_id}: {e}")

    print("📡 ALL NODES OPERATIONAL | Press Ctrl+C to stop all cameras at once.\n")

    # Monitor processes and print interleaved logs
    import threading

    def monitor_node(node_id, process):
        for line in iter(process.stdout.readline, ""):
            if line.strip():
                print(f"[{node_id}] {line.strip()}")
        process.stdout.close()

    threads = []
    for node_id, p in processes.items():
        t = threading.Thread(target=monitor_node, args=(node_id, p), daemon=True)
        t.start()
        threads.append(t)

    # Keep main thread alive
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
