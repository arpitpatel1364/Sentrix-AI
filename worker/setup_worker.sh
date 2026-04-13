#!/bin/bash
set -e

echo "[*] Sentrix-AI: Worker Setup Starting..."

echo "[*] Installing system dependencies..."
sudo apt-get update && sudo apt-get install -y \
    python3-pip \
    python3-venv \
    libgl1-mesa-glx \
    libglib2.0-0

echo "[*] Creating virtual environment..."
python3 -m venv venv_worker

echo "[*] Installing Python packages..."
source venv_worker/bin/activate
pip install --upgrade pip
if [ -f "requirements_worker.txt" ]; then
    pip install -r requirements_worker.txt
else
    echo "[!] requirements_worker.txt not found! Installing defaults..."
    pip install opencv-python requests ultralytics numpy onnxruntime
fi

echo "[*] Checking for models..."
mkdir -p models
if [ ! -f "models/best.onnx" ]; then
    echo "[!] models/best.onnx not found!"
else
    echo "[v] Model found: models/best.onnx"
fi

echo "[v] Setup Complete!"
echo "Usage:"
echo "  source venv_worker/bin/activate"
echo "  python3 worker_agent.py --server http://<server-ip>:8000 --user <user> --password <pass> --camera 0"
