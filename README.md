# Sentrix AI | Distributed Intelligence Mesh

**Sentrix AI** is a professional-grade, distributed AI surveillance system designed to transform standard CCTV networks into an active security shield. By combining edge-side face detection with a centralized neural recognition engine, it identifies targets in real-time and provides actionable travel intelligence.

---

## 🏗️ Project Architecture

Sentrix-AI has been restructured into a modular, feature-based architecture to ensure scalability and professional-grade code readability.

```text
Sentrix-AI/
├── backend/                  # Central Intelligence Hub
│   ├── app/                  # Application Source Code
│   │   ├── core/             # Shared Infrastructure (DB, Auth, AI Engines)
│   │   ├── features/         # Modular Feature Routers
│   │   │   ├── auth/         # User Access & Session Management
│   │   │   ├── watchlist/    # WANTED Registry & Target Templates
│   │   │   ├── sightings/    # Detection History & Neural Search
│   │   │   ├── workers/      # Field Node Orchestration
│   │   │   └── system/       # Global Stats & System Controls
│   │   ├── static/           # Premium Administrative Dashboard
│   │   └── main.py           # Application Entry Point
│   ├── data/                 # Persistent Intelligence Data (SQLite, Snapshots)
│   ├── models/                # Neural Model Repository (YOLOv8, InsightFace)
│   └── main.py                # Launch Shim for the Backend
├── worker/                    # Field Intelligence Node (Camera Client)
│   ├── worker_agent.py        # Edge-side detection & streaming logic
│   └── setup_worker.sh        # Automated node deployment script
├── venv/                      # Unified Python Environment
├── sentrix_orchestrator.py    # Multi-node Mesh Manager
└── docker-compose.yml         # Containerized Orchestration
```

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.10+
- NVIDIA GPU (Optional, for 10x faster recognition)
- Qdrant (Self-managed or Cloud)

### 2. Standard Launch (Manual)
```bash
# Register dependencies and setup environment
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

# Start the Intelligence Hub (Backend)
python3 backend/main.py
```

### 3. Launching the Surveillance Mesh (Local)
To launch multiple camera nodes on the same machine:
```bash
python3 sentrix_orchestrator.py
```

---

## 📡 Deployment & Orchestration

### 🛰️ Worker Node Setup (Remote Machine)
To deploy a camera node on a remote PC, copy only the `worker/` directory and run:
```bash
chmod +x setup_worker.sh
./setup_worker.sh
```

### 🐳 Docker Deployment (Professional)
From the root directory:
```bash
docker-compose up -d --build
```
- **Dashboard**: `http://localhost:8000`
- **Default Admin**: `admin` / `admin123`
- **Default Worker**: `worker1` / `worker123`

---

## 🧠 Intelligence Features

- **Neural Watchlist Registry**: Professional target enrollment with up to 15 neural face templates per individual for ultra-reliable cross-camera identification.
- **Global Forensic Search**: Upload any face image to the "Neural Search" interface to instantly cross-reference history and find the **Last 3 Locations** and full travel path across the entire network.
- **Distributed Edge Intelligence**: Face detection is handled at the source (Worker Node) using YOLOv8 or Haar Cascades, reducing server load and optimizing bandwidth for high-definition streaming.
- **Real-Time Intercept Alerts**: Instant, low-latency "WANTED" match alerts delivered to the Command Dashboard via Server-Sent Events (SSE).
- **Security & Persistence**: Secure JWT-based authentication for all nodes and centralized vector storage using Qdrant for million-record scale operations.

## 🔑 Default Credentials

| Identity | Username | Password |
| :--- | :--- | :--- |
| **Site Admin** | `admin` | `admin123` |
| **Field Operative** | `worker1` | `worker123` |

---

## ⚙️ Main System Data

- **Database**: Metadata is stored in `backend/data/cctv.db` (SQLite).
- **Vectors**: Persistent vector storage initialized in `backend/data/qdrant_storage/`.
- **Detection**: Place your YOLOv8 face detection model at `backend/models/best.pt`.
- **Recognition**: InsightFace models are auto-downloaded to `backend/models/insightface/` on first launch.
- **Static Assets**: The dashboard is served from `backend/app/static/dashboard.html`.

---

## ⚖️ License
*Proprietary Security Intelligence Software. Licensed for specialized facility use.*
