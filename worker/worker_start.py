#!/usr/bin/env python3
"""
worker_start.py
===============
Interactive startup script for a Sentrix-AI worker node.

Run this on the machine that has the camera connected:

    python worker_start.py

The script will:
  1. Ask the worker for all required information step by step
  2. Try to connect to the server and authenticate
  3. Open the dashboard in the browser so the admin can register the camera
  4. Wait until the admin has registered the camera in the dashboard
  5. Start the worker_agent.py with all the correct arguments
  6. While running, poll the server every 10 seconds for stop requests
     — if admin approves a stop request, this script shuts down cleanly

Press Ctrl+C at any time to exit.
"""

import argparse
import getpass
import os
import sys
import time
import threading
import subprocess
import webbrowser
from pathlib import Path

try:
    import requests
except ImportError:
    print("\n[ERR] 'requests' library not found. Run: pip install requests")
    sys.exit(1)


# ── ANSI colours ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}[OK]{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}[!]{RESET}   {msg}")
def err(msg):  print(f"  {RED}[ERR]{RESET} {msg}")
def info(msg): print(f"  {CYAN}[>]{RESET}   {msg}")

def ask(prompt, default=None, secret=False):
    display_default = f" [{default}]" if default is not None else ""
    full_prompt = f"  {BOLD}{prompt}{display_default}: {RESET}"
    if secret:
        val = getpass.getpass(full_prompt)
    else:
        val = input(full_prompt)
    val = val.strip()
    if not val and default is not None:
        return str(default)
    return val


def banner():
    print(f"""
{CYAN}{BOLD}
  ╔══════════════════════════════════════════╗
  ║     Sentrix-AI  Worker Setup Script     ║
  ╚══════════════════════════════════════════╝
{RESET}
  This script guides you through starting a
  camera worker node — step by step.
""")


# ── Step 1: gather info ─────────────────────────────────────────────────────
def gather_config():
    print(f"\n{BOLD}STEP 1 — Server Connection{RESET}")
    server = ask("Server URL (e.g. http://192.168.1.10:8000)", "http://localhost:8000")
    server = server.rstrip("/")

    print(f"\n{BOLD}STEP 2 — Your Worker Credentials{RESET}")
    info("Ask your admin for a worker username and password.")
    username = ask("Username")
    while not username:
        warn("Username cannot be empty.")
        username = ask("Username")
    password = ask("Password", secret=True)
    while not password:
        warn("Password cannot be empty.")
        password = ask("Password", secret=True)

    print(f"\n{BOLD}STEP 3 — Camera Setup{RESET}")
    info("You can connect multiple cameras.")
    info("Use 0, 1, 2 for USB cameras — or a full RTSP URL for IP cameras.")
    print()

    cameras = []
    cam_index = 1
    while True:
        cam_src  = ask(f"Camera {cam_index} source (index or RTSP URL)", str(cam_index - 1))
        cam_id   = ask(f"Camera {cam_index} ID (unique short name)", f"cam-{cam_index}")
        location = ask(f"Camera {cam_index} location", f"Location {cam_index}")
        cameras.append({"src": cam_src, "id": cam_id, "location": location})
        ok(f"Camera '{cam_id}' added ({location})")
        cam_index += 1
        more = ask("Add another camera? (y/n)", "n")
        if more.lower() != "y":
            break

    print(f"\n{BOLD}STEP 4 — Detection Options{RESET}")
    enable_face = ask("Enable face detection? (y/n)", "y").lower() == "y"
    enable_obj  = ask("Enable object detection? (y/n)", "y").lower() == "y"
    force_cpu   = ask("Force CPU mode — no GPU? (y/n)", "n").lower() == "y"

    return {
        "server":      server,
        "username":    username,
        "password":    password,
        "cameras":     cameras,
        "enable_face": enable_face,
        "enable_obj":  enable_obj,
        "force_cpu":   force_cpu,
    }


# ── Step 2: authenticate ────────────────────────────────────────────────────
def authenticate(server, username, password):
    print(f"\n{BOLD}Connecting to server…{RESET}")
    try:
        r = requests.post(
            f"{server}/api/login",
            json={"username": username, "password": password},
            timeout=10,
        )
        if r.status_code == 200:
            token = r.json().get("token")
            ok(f"Authenticated as '{username}'")
            return token
        detail = r.json().get("detail", r.text)
        err(f"Login failed: {detail}")
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        err(f"Cannot reach server at {server}")
        err("Check the URL and make sure the Sentrix backend is running.")
        sys.exit(1)
    except Exception as exc:
        err(f"Unexpected error: {exc}")
        sys.exit(1)


# ── Step 3: open browser for admin to register cameras ──────────────────────
def open_dashboard(server, cameras):
    print(f"\n{BOLD}STEP 5 — Register Cameras in Dashboard{RESET}")
    info("Opening the Sentrix dashboard in your browser.")
    info("Ask your admin to:")
    info("  1. Log in to the dashboard")
    info("  2. Go to  Camera Management")
    info("  3. Click  Register Camera  and add each of these:\n")
    for cam in cameras:
        print(f"       Camera ID  : {BOLD}{cam['id']}{RESET}")
        print(f"       Location   : {cam['location']}\n")

    dashboard_url = f"{server}/dashboard"
    try:
        webbrowser.open(dashboard_url)
        ok(f"Opened: {dashboard_url}")
    except Exception:
        warn(f"Could not auto-open browser. Visit manually: {dashboard_url}")

    print()
    input(f"  {BOLD}Press Enter once the admin has registered the cameras…{RESET} ")


# ── Step 4: verify cameras are on server ─────────────────────────────────────
def verify_cameras(server, token, cameras):
    headers = {"Authorization": f"Bearer {token}"}
    print(f"\n{BOLD}Verifying camera registration…{RESET}")
    try:
        r = requests.get(f"{server}/api/cameras", headers=headers, timeout=10)
        r.raise_for_status()
        registered = {c["camera_id"] for c in r.json()}
        for cam in cameras:
            if cam["id"] in registered:
                ok(f"'{cam['id']}' found on server")
            else:
                warn(f"'{cam['id']}' NOT registered on server yet")
        missing = [c for c in cameras if c["id"] not in registered]
        if missing:
            cont = ask("Some cameras are missing. Continue anyway? (y/n)", "y")
            if cont.lower() != "y":
                sys.exit(0)
    except Exception as exc:
        warn(f"Could not verify cameras: {exc}")


# ── Step 5: launch worker_agent.py ───────────────────────────────────────────
def launch_worker(config):
    base_dir   = Path(__file__).resolve().parent
    agent_path = base_dir / "worker_agent.py"

    if not agent_path.exists():
        err(f"worker_agent.py not found at {agent_path}")
        sys.exit(1)

    # Prefer venv python if available
    python_exe = sys.executable
    for candidate in [
        base_dir / "venv_worker" / "bin" / "python",
        base_dir / "venv_worker" / "Scripts" / "python.exe",
        base_dir / "venv" / "bin" / "python",
        base_dir / "venv" / "Scripts" / "python.exe",
    ]:
        if candidate.exists():
            python_exe = str(candidate)
            break

    cameras = config["cameras"]
    cmd = [
        python_exe, str(agent_path),
        "--server",    config["server"],
        "--user",      config["username"],
        "--password",  config["password"],
        "--camera",    *[c["src"]      for c in cameras],
        "--camera-id", *[c["id"]       for c in cameras],
        "--location",  *[c["location"] for c in cameras],
    ]
    if not config["enable_face"]:
        cmd.append("--no-face")
    if not config["enable_obj"]:
        cmd.append("--no-obj")
    if config["force_cpu"]:
        cmd.append("--cpu")

    print(f"\n{BOLD}Launching worker agent…{RESET}")
    info("Command: " + " ".join(cmd))
    print()
    return subprocess.Popen(cmd)


# ── Step 6: poll stop-requests in background ─────────────────────────────────
def poll_stop_requests(server, token, cameras, proc):
    """
    Background thread — polls /api/stop-requests/my-status every 10 seconds.
    If admin approves a stop request, kills the subprocess gracefully.
    """
    headers    = {"Authorization": f"Bearer {token}"}
    camera_ids = [c["id"] for c in cameras]

    while proc.poll() is None:
        time.sleep(10)
        for cam_id in camera_ids:
            try:
                r = requests.get(
                    f"{server}/api/stop-requests/my-status",
                    params={"camera_id": cam_id},
                    headers=headers,
                    timeout=8,
                )
                if r.status_code != 200:
                    continue
                data   = r.json()
                status = data.get("status")

                if status == "approved":
                    print(f"\n{YELLOW}{BOLD}[STOP APPROVED]{RESET} Admin approved stop for '{cam_id}'.")
                    print("  Shutting down worker agent…\n")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    # Tell server we are offline
                    try:
                        requests.post(
                            f"{server}/api/worker/offline",
                            data={"camera_id": cam_id},
                            headers=headers,
                            timeout=5,
                        )
                    except Exception:
                        pass
                    return

                elif status == "denied":
                    print(f"\n{RED}[STOP DENIED]{RESET} Admin denied stop request for '{cam_id}'. Continuing.\n")

            except Exception:
                pass  # Transient network issue — try again next cycle


# ── Main entry point ─────────────────────────────────────────────────────────
def main():
    banner()

    parser = argparse.ArgumentParser(
        description="Sentrix Worker Interactive Startup"
    )
    # These flags let you skip the interactive prompts when scripting
    parser.add_argument("--server",     help="Server URL")
    parser.add_argument("--user",       help="Worker username")
    parser.add_argument("--password",   help="Worker password")
    parser.add_argument("--camera",     nargs="+", help="Camera sources")
    parser.add_argument("--camera-id",  nargs="+", help="Camera IDs", dest="camera_id")
    parser.add_argument("--location",   nargs="+", help="Camera locations")
    parser.add_argument("--no-face",    action="store_true")
    parser.add_argument("--no-obj",     action="store_true")
    parser.add_argument("--cpu",        action="store_true")
    parser.add_argument("--no-browser", action="store_true",
                        help="Skip opening the browser (useful for headless servers)")
    args = parser.parse_args()

    # If all required flags given, skip interactive prompts
    if args.server and args.user and args.password and args.camera:
        cameras = []
        for i, src in enumerate(args.camera):
            cids = args.camera_id or []
            locs = args.location  or []
            cameras.append({
                "src":      src,
                "id":       cids[i] if i < len(cids) else f"cam-{i+1}",
                "location": locs[i] if i < len(locs) else f"Location {i+1}",
            })
        config = {
            "server":      args.server.rstrip("/"),
            "username":    args.user,
            "password":    args.password,
            "cameras":     cameras,
            "enable_face": not args.no_face,
            "enable_obj":  not args.no_obj,
            "force_cpu":   args.cpu,
        }
    else:
        config = gather_config()

    # Authenticate with server
    token = authenticate(config["server"], config["username"], config["password"])

    # Open dashboard in browser unless headless
    if not getattr(args, "no_browser", False):
        open_dashboard(config["server"], config["cameras"])

    # Double-check cameras are registered
    verify_cameras(config["server"], token, config["cameras"])

    # Launch worker_agent subprocess
    proc = launch_worker(config)

    # Start background stop-request polling
    poll_thread = threading.Thread(
        target=poll_stop_requests,
        args=(config["server"], token, config["cameras"], proc),
        daemon=True,
    )
    poll_thread.start()

    print(f"{GREEN}{BOLD}[RUNNING]{RESET} Worker is live. Press Ctrl+C to stop.\n")

    try:
        proc.wait()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}[STOPPING]{RESET} Ctrl+C received. Shutting down worker…")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

        # Notify server we went offline
        headers = {"Authorization": f"Bearer {token}"}
        for cam in config["cameras"]:
            try:
                requests.post(
                    f"{config['server']}/api/worker/offline",
                    data={"camera_id": cam["id"]},
                    headers=headers,
                    timeout=5,
                )
                ok(f"Camera '{cam['id']}' marked offline")
            except Exception:
                pass

    print(f"\n{GREEN}Goodbye.{RESET}\n")


if __name__ == "__main__":
    main()
