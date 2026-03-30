import os
import sys
import subprocess
import time
import signal
from pathlib import Path

# ==========================================
# SENTRIX SYSTEM ORCHESTRATOR
# ==========================================
# This script reads nodes.conf and launches 
# many local worker_agent.py processes at once.
# ==========================================

SERVER_URL = "http://localhost:8000"
BASE_DIR = Path(__file__).resolve().parent

# CONFIGURATION: Load from nodes.conf inside admin/
def load_nodes():
    nodes = []
    conf_path = BASE_DIR / "admin" / "nodes.conf"
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
                    "camera": parts[2],
                    "user": parts[3],
                    "pass": parts[4]
                })
    return nodes

def launch_workers(nodes):
    processes = []
    
    # Check if worker_agent.py exists inside worker/
    agent_path = BASE_DIR / "worker" / "worker_agent.py"
    if not agent_path.exists():
        print(f"❌ ERROR: {agent_path} not found!")
        return []

    # Detect virtual environment (Try venv_worker first, then venv)
    paths_to_check = [
        BASE_DIR / "worker" / "venv_worker", # Standard Linux
        BASE_DIR / "worker" / "venv_worker" / "Scripts" / "python.exe", # Windows
        BASE_DIR / "venv" / "bin" / "python", 
        BASE_DIR / "venv" / "Scripts" / "python.exe"
    ]
    
    python_exe = sys.executable
    for p in paths_to_check:
        executable = p if p.name.endswith(".exe") or p.name == "python" else p / "bin" / "python"
        if executable.exists():
            python_exe = str(executable)
            break
    
    print(f"🚀 Launching {len(nodes)} camera nodes...")

    for node in nodes:
        cmd = [
            python_exe, str(agent_path),
            "--server", SERVER_URL,
            "--user", node["user"],
            "--password", node["pass"],
            "--camera", node["camera"],
            "--camera-id", node["id"],
            "--location", node["location"]
        ]
        
        print(f"  🛰️  Starting Node: {node['id']} ({node['location']})")
        p = subprocess.Popen(cmd)
        processes.append(p)
    
    return processes

def main():
    nodes = load_nodes()
    if not nodes:
        print("ℹ  No nodes found in admin/nodes.conf. Use admin/manage_workers.py to add some!")
        return

    processes = launch_workers(nodes)
    
    def signal_handler(sig, frame):
        print("\n🛑 Shutting down all nodes...")
        for p in processes:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    
    print("\n✅ All nodes are running. Press Ctrl+C to stop the entire mesh.\n")
    
    # Monitor processes
    while True:
        try:
            time.sleep(5)
            # Check if any process died
            for p in processes:
                if p.poll() is not None:
                    print(f"⚠  Process {p.pid} has exited.")
        except KeyboardInterrupt:
            break

if __name__ == "__main__":
    main()
