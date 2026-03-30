# 🛰️ Sentrix-AI: Worker Node (Field Intelligence)

The **Sentrix Worker** is a high-performance, edge-intelligence agent designed to run on any machine with camera access. It performs real-time face detection locally and streams optimized metadata to the **Sentrix Central Hub**.

---

## ⚡ Core Features

- **Edge Detection**: Uses YOLOv8 or OpenCV Haar Cascades for low-latency face detection.
- **MJPG Bandwidth Optimization**: Automatically enables MJPG mode for USB cameras to allow multiple high-res feeds on a single hub.
- **Multi-Camera Engine**: Native support for monitoring multiple physical cameras or RTSP streams from a single worker node.
- **Motion-Triggered Intelligence**: Only processes and uploads frames when motion is detected, significantly reducing bandwidth and server load.
- **CUDA Self-Healing**: Automatically detects NVIDIA GPUs and activates CUDA acceleration for 10x faster detection.

---

## 🛠️ Installation & Setup

### 🐧 Linux (Ubuntu/Debian)
```bash
# Navigate to the worker directory
cd worker/

# Run the automated setup script
chmod +x setup_worker.sh
./setup_worker.sh
```

### 🪟 Windows
1. Open **PowerShell** as Administrator.
2. Navigate to the `worker/` folder.
3. Run the automated setup:
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
   .\setup_worker.ps1
   ```

---

## 🚀 Running the Agent

### 1. Register the Worker
Before running the agent, ensure the worker identity is registered on the server (Run this on the **Server** machine):
```bash
python manage_workers.py add --id "cam-01" --location "Reception" --camera 0 --user "worker1" --password "pass123"
```

### 2. Launching the Agent
Run the agent on the machine connected to the camera:

#### **Single Camera Mode**
```bash
python worker_agent.py --server http://<SERVER-IP>:8000 --user "worker1" --password "pass123" --camera 0
```

#### **Multi-Camera Mode** (Advanced)
Monitor multiple feeds simultaneously using the multi-threaded engine:
```bash
python worker_agent.py --server http://<SERVER-IP>:8000 --user "worker1" --password "pass123" \
  --camera 0 1 \
  --camera-id "lobby" "gate" \
  --location "Main Lobby" "Central Gate"
```

---

## 🐳 Docker Deployment

For enterprise environments, the worker can be deployed as a container:

```bash
# Build the worker image
docker build -t sentrix-worker -f Dockerfile.worker .

# Run with camera access (Linux)
docker run -d --name worker-1 --device=/dev/video0:/dev/video0 sentrix-worker
```

---

## 🔍 Troubleshooting

| Issue | Solution |
| :--- | :--- |
| **Camera Not Found** | Ensure no other app (Zoom, Teams) is using the camera. Check index (0, 1, 2). |
| **Connection Refused** | Verify the Server URL and ensure port 8000 is open in the firewall. |
| **Permission Denied (Linux)** | Run `sudo usermod -a -G video $USER` and log out/in. |
| **Low Performance** | Ensure `onnxruntime-gpu` is installed if you have an NVIDIA card. |

---

## 🔑 Command Line Arguments

- `--server`: URL of the Sentrix Hub (Default: `http://localhost:8000`).
- `--camera`: List of camera indices or RTSP URLs.
- `--interval`: Seconds to wait between detections (Default: `3.0`).
- `--no-model`: Disable YOLO detection (uses raw frames).
- `--model`: Path to a custom YOLOv8 `.onnx` or `.pt` model.

---

> [!TIP]
> **Performance Optimization**: For the best results, use a dedicated USB 3.0 port for each high-resolution camera. If running multiple cameras on a single hub, the agent automatically switches to MJPG mode to conserve bandwidth.
