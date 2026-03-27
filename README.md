# Sentrix AI | Distributed Intelligence Mesh

**Sentrix AI** is a professional-grade, distributed AI surveillance system designed to transform standard CCTV networks into an active security shield. By combining edge-side face detection with a centralized neural recognition engine, it identifies targets in real-time and provides actionable travel intelligence.

---

##  Key Functionality

### 📡 Distributed Surveillance Mesh
*   **Worker Agents**: Light-weight clients (Python) that run on any local machine with a camera. They perform edge-side face detection (YOLOv8/Haar) and stream high-quality crops to the server.
*   **Central Brain**: A FastAPI-based server that processes visual data, generates neural embeddings, and handles identification across thousands of records.

### Neural Intelligence Hub
*   **Face Recognition**: Powered by **InsightFace (Buffalo_S/L)** for near-instant identity verification with high cosine similarity precision.
*   **Vector Search**: Integrated with **Qdrant** for lightning-fast history lookups and identity cross-referencing across millions of captured sightings.
*   **Intelligence Tooling**: A "Neural Search" feature allowing operators to upload any face image to find a person's **Last 3 Locations** and travel history.

### Admin Surveillance Dashboard
*   **Live Intercept Feed**: Real-time activity timeline with glassmorphism-inspired UI and instant "WANTED" alerts.
*   **Personnel Management**: Full CRUD interface for managing Field Operatives (Workers) and Site Admins.
*   **Watchlist Registry**: Neural templates for target individuals, synchronized across the entire network.
*   **System Controls**: One-click "System Reset" for rapid data sanitization and fresh operational starts.

---

## Tech Stack

*   **Backend**: Python, FastAPI, Uvicorn, SSE (Server-Sent Events)
*   **Database**: SQLite (Metadata), Qdrant (Vector Embeddings)
*   **AI Models**: InsightFace (Recognition), YOLOv8 (Face Detection fallback to Haar)
*   **Frontend**: HTML5, Vanilla CSS3 (Glassmorphism), JavaScript (Modern ES6+)
*   **Security**: JWT (JSON Web Tokens), Bcrypt Hashing, HTTP Bearer Auth

---

## 📦 Installation & Setup

### 1. Server Setup (Manager)
```bash
# Clone the repository
git clone https://github.com/your-repo/sentrix-ai.git
cd sentrix-ai

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the Intelligence Server
python3 server.py
```
*The server will be accessible at http://localhost:8000.*

### 2. Worker Setup (Field Node)
Run this on any machine with a local webcam or IP camera access.
```bash
# Start the monitoring agent
python3 worker_agent.py --server http://your-server-ip:8000 --user worker1 --password worker123 --camera 0
```

---

##  Project Structure

*   `server.py`: The central Intelligence Hub (API, Auth, Vector Engine).
*   `worker_agent.py`: Field Node agent for local detection and frame streaming.
*   `dashboard.html`: The premium administrative interface.
*   `data/`: Persistent storage for SQLite, Qdrant vectors, and face snapshots.
*   `models/`: Repository for YOLOv8 `best.pt` and InsightFace neural models.

---

##  Default Credentials | changeable from code 

| Identity | Username | Password |
| :--- | :--- | :--- |
| **Site Admin** | `admin` | `admin123` |
| **Field Operative** | `worker1` | `worker123` |

---

##  Model Configuration
*   **Detection**: Place your YOLOv8 face detection model at `models/best.pt`.
*   **Recognition**: InsightFace models are auto-downloaded to `models/insightface/` on first launch.

---

##  License
*Proprietary Security Intelligence Software. Licensed for specialized facility use.*
