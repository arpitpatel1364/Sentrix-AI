import os
import sys
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional
from .config import BASE_DIR

class WorkerOrchestrator:
    _instance = None
    
    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}
        self.python_exe = self._find_python_exe()
        self.agent_path = BASE_DIR.parent / "worker" / "worker_agent.py"

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _find_python_exe(self) -> str:
        base = BASE_DIR.parent
        paths_to_check = [
            base / "worker" / "venv_worker" / "Scripts" / "python.exe",
            base / "worker" / "venv_worker" / "bin" / "python",
            base / "venv" / "Scripts" / "python.exe",
            base / "venv" / "bin" / "python",
        ]
        for p in paths_to_check:
            if p.exists():
                return str(p)
        return sys.executable

    def load_nodes_from_db(self) -> List[Dict]:
        """
        Legacy SQLite node loading. 
        In SaaS mode, workers are external and self-registered. 
        Local orchestration is currently disabled or pending migration to Postgres.
        """
        return []

    def start_node(self, node_id: str) -> bool:
        # Check if already running and healthy
        if node_id in self.processes:
            if self.processes[node_id].poll() is None:
                return True
            else:
                del self.processes[node_id]
            
        nodes = self.load_nodes_from_db()
        target_node = next((n for n in nodes if n["id"] == node_id), None)
        
        if not target_node:
            print(f"[ORCH] Node {node_id} not found in database")
            return False

        if not self.agent_path.exists():
            print(f"[ORCH] worker_agent.py not found at {self.agent_path}")
            return False

        # Build command. Use environment variable for server if available, else default.
        server_url = os.environ.get("SERVER_URL", "http://localhost:8000")
        
        cmd = [
            self.python_exe, str(self.agent_path),
            "--server", server_url,
            "--user", target_node["user"],
            "--password", target_node["pass"],
            "--camera", target_node["camera"],
            "--camera-id", target_node["id"],
            "--location", target_node["location"]
        ]
        
        try:
            # Creation flags to prevent parent from waiting or inheriting console on Windows
            p = subprocess.Popen(
                cmd, 
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.processes[node_id] = p
            print(f"[ORCH] Started node {node_id} (PID: {p.pid})")
            return True
        except Exception as e:
            print(f"[ORCH] Failed to start node {node_id}: {e}")
            return False

    def stop_node(self, node_id: str) -> bool:
        if node_id not in self.processes:
            return True
            
        p = self.processes[node_id]
        if p.poll() is None:
            if os.name == 'nt':
                # On Windows, terminate() doesn't always work well for process groups
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(p.pid)], capture_output=True)
            else:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
            print(f"[ORCH] Stopped node {node_id}")
            
        if node_id in self.processes:
            del self.processes[node_id]
        return True

    def start_mesh(self):
        nodes = self.load_nodes_from_db()
        print(f"[ORCH] Starting mesh for {len(nodes)} nodes...")
        for node in nodes:
            self.start_node(node["id"])
            time.sleep(0.5) # Slight stagger

    def stop_mesh(self):
        node_ids = list(self.processes.keys())
        print(f"[ORCH] Stopping mesh ({len(node_ids)} active nodes)...")
        for nid in node_ids:
            self.stop_node(nid)

    def get_status(self) -> Dict[str, bool]:
        status = {}
        nodes = self.load_nodes_from_db()
        for node in nodes:
            nid = node["id"]
            is_running = nid in self.processes and self.processes[nid].poll() is None
            status[nid] = is_running
        return status

# Create global instance
orchestrator = WorkerOrchestrator.get_instance()
