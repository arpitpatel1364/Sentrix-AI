import argparse
import requests
import sys
import os
from pathlib import Path

# ==========================================
# SENTRIX WORKER MANAGEMENT TOOL
# ==========================================

BASE_DIR = Path(__file__).resolve().parent
NODES_CONF = BASE_DIR / "nodes.conf"
SERVER_URL = "http://localhost:8000"

def parse_args():
    p = argparse.ArgumentParser(description="Sentrix Worker Management")
    sub = p.add_subparsers(dest="command", required=True)

    # ADD
    add = sub.add_parser("add", help="Register a new worker and add to nodes.conf")
    add.add_argument("--id", required=True, help="Unique ID for this camera node (e.g. entrance-1)")
    add.add_argument("--location", required=True, help="Physical location (e.g. Front Gate)")
    add.add_argument("--camera", default="0", help="Camera index or RTSP URL")
    add.add_argument("--user", required=True, help="Username for this worker")
    add.add_argument("--password", required=True, help="Password for this worker")
    add.add_argument("--admin-user", default="admin", help="Admin username to register user")
    add.add_argument("--admin-pass", default="admin123", help="Admin password")

    # LIST
    sub.add_parser("list", help="List workers in nodes.conf")

    # DELETE
    rem = sub.add_parser("delete", help="Remove a worker from nodes.conf and server")
    rem.add_argument("--id", required=True, help="Node ID to remove")
    rem.add_argument("--admin-user", default="admin")
    rem.add_argument("--admin-pass", default="admin123")
    
    return p.parse_args()

def login(server: str, user: str, passw: str):
    r = requests.post(f"{server}/api/login", json={"username": user, "password": passw}, timeout=10)
    r.raise_for_status()
    return r.json()["token"]

def register_on_server(token: str, user: str, passw: str, role: str = "worker"):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.post(f"{SERVER_URL}/api/users", 
                     json={"username": user, "password": passw, "role": role},
                     headers=headers, timeout=10)
    if r.status_code == 409:
        print(f"ℹ  User '{user}' already exists on server.")
        return True
    r.raise_for_status()
    print(f"✅ Registered user '{user}' on server.")
    return True

def delete_from_server(token: str, username: str):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.delete(f"{SERVER_URL}/api/users/{username}", headers=headers, timeout=10)
    if r.status_code == 404:
        print(f"⚠  User '{username}' not found on server.")
        return False
    r.raise_for_status()
    print(f"✅ Deleted user '{username}' from server.")
    return True

def add_to_conf(node_id, location, camera, user, password):
    line = f"{node_id} | {location} | {camera} | {user} | {password}\n"
    
    # Check if ID already exists
    if os.path.exists(NODES_CONF):
        with open(NODES_CONF, "r") as f:
            for l in f:
                if l.strip().startswith(node_id + " |"):
                    print(f"❌ Error: Node ID '{node_id}' already exists in {NODES_CONF}.")
                    return False

    with open(NODES_CONF, "a") as f:
        f.write(line)
    print(f"✅ Added node '{node_id}' to {NODES_CONF}.")
    return True

def list_nodes():
    if not os.path.exists(NODES_CONF):
        print(f"ℹ  {NODES_CONF} not found.")
        return
    print("\n--- CURRENT NODES ---")
    with open(NODES_CONF, "r") as f:
        for line in f:
            if "|" in line and not line.strip().startswith("#"):
                print(f"  🛰️  {line.strip()}")
    print("---------------------\n")

def delete_node(node_id, admin_user, admin_pass):
    temp_file = str(NODES_CONF) + ".tmp"
    found = False
    username_to_del = None
    
    if not os.path.exists(NODES_CONF):
        print(f"❌ {NODES_CONF} not found.")
        return

    with open(NODES_CONF, "r") as f, open(temp_file, "w") as tf:
        for line in f:
            if line.strip().startswith(node_id + " |"):
                found = True
                # Extract username if we want to delete from server too
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 4:
                    username_to_del = parts[3]
                continue
            tf.write(line)
    
    if not found:
        print(f"❌ Node ID '{node_id}' not found in {NODES_CONF}.")
        os.remove(temp_file)
        return

    os.replace(temp_file, NODES_CONF)
    print(f"✅ Removed node '{node_id}' from {NODES_CONF}.")

    if username_to_del and username_to_del != "admin":
        try:
            token = login(SERVER_URL, admin_user, admin_pass)
            delete_from_server(token, username_to_del)
        except Exception as e:
            print(f"⚠  Could not delete user '{username_to_del}' from server: {e}")

def main():
    args = parse_args()
    
    try:
        if args.command == "add":
            token = login(SERVER_URL, args.admin_user, args.admin_pass)
            register_on_server(token, args.user, args.password)
            add_to_conf(args.id, args.location, args.camera, args.user, args.password)
        elif args.command == "list":
            list_nodes()
        elif args.command == "delete":
            delete_node(args.id, args.admin_user, args.admin_pass)
    except Exception as e:
        print(f"❌ ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
