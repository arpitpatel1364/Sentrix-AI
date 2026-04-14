import os
import time
import sys
import multiprocessing as mp
import httpx
import cv2
import numpy as np
import asyncio
import threading
import subprocess
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import torch

# Fix for PyTorch 2.6+ weights_only security change
try:
    import ultralytics.nn.tasks
    if hasattr(torch.serialization, 'add_safe_globals'):
        torch.serialization.add_safe_globals([ultralytics.nn.tasks.WorldModel])
except ImportError:
    pass

load_dotenv()

# --- CONFIG FROM ENV ---
HUB_URL = os.getenv("HUB_URL")
CLIENT_API_KEY = os.getenv("CLIENT_API_KEY")
HUB_WORKER_ID = os.getenv("HUB_WORKER_ID")
SNAPSHOT_DIR = os.getenv("SNAPSHOT_DIR", "/app/snapshots")
CAMERA_URLS = os.getenv("CAMERA_URLS", "0").split(",")
CAMERA_NAMES = os.getenv("CAMERA_NAMES", "Camera 1").split(",")

# Paths relative to this script
BASE_DIR = Path(__file__).resolve().parent
FACE_MODEL_PATH = str(BASE_DIR / "models" / "best.onnx")
OBJ_MODEL_PATH = str(BASE_DIR / "models" / "yolov8s-worldv2.pt")

import json
HUB_CAMERA_MAPPING = json.loads(os.getenv("HUB_CAMERA_MAPPING", "{}"))

TARGET_CLASSES = [
    "phone","water bottle", "laptop", "backpack", 
    "remote", "keyboard", "cell phone", "book","bicycle", "car", "motorbike", "aeroplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake",
    "chair", "sofa", "pottedplant", "bed", "diningtable", "toilet", "tvmonitor", "laptop",
    "mouse", "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush"
]

def save_snapshot(frame, camera_name: str) -> str:
    """Save frame as JPEG to local SNAPSHOT_DIR and return relative path."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime('%H%M%S_%f')
    filename = f"{camera_name.replace(' ', '_')}_{timestamp}.jpg"
    dir_path = Path(SNAPSHOT_DIR) / date_str
    dir_path.mkdir(parents=True, exist_ok=True)
    full_path = dir_path / filename
    cv2.imwrite(str(full_path), frame)
    return f"{date_str}/{filename}"

async def match_face(embedding: list[float]) -> dict:
    """Query Hub Qdrant for face match."""
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(
                f"{HUB_URL}/api/qdrant/search",
                headers={"Authorization": f"Bearer {CLIENT_API_KEY}"},
                json={"embedding": embedding, "threshold": 0.6},
                timeout=10
            )
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f"[WARN] Face match request failed: {e}")
    return {"matched": False}

async def send_detection_result(
    camera_id: str,
    detection_type: str,
    label: str,
    confidence: float,
    bbox: list,
    snapshot_path: str
):
    """Send detection metadata to Hub."""
    payload = {
        "worker_id": HUB_WORKER_ID,
        "camera_id": camera_id,
        "type": detection_type,
        "label": label,
        "confidence": float(confidence),
        "bbox": bbox,
        "snapshot_path": snapshot_path,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(
                f"{HUB_URL}/api/inference/result",
                headers={"Authorization": f"Bearer {CLIENT_API_KEY}"},
                json=payload,
                timeout=10
            )
            return r.status_code == 200
        except Exception as e:
            print(f"[WARN] Failed to send inference result: {e}")
            return False

def open_camera(source):
    try:
        src = int(source)
    except Exception:
        src = source
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        return None
    return cap

def capture_worker(cam_src, cam_id, face_queue, obj_queue, live_queue):
    print(f"[*] Capture Node started: {cam_id} ({cam_src})")
    cap = open_camera(cam_src)
    if not cap:
        print(f"[ERR] Failed to open camera {cam_id}")
        return

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(1)
            continue

        frame_copy = frame.copy()
        for q in [face_queue, obj_queue, live_queue]:
            if q and not q.full():
                try:
                    q.put_nowait((frame_copy, cam_id))
                except mp.queues.Full:
                    pass
        time.sleep(0.01)

def face_detector_worker(face_queue, upload_queue):
    print("[*] Face Engine starting (InsightFace)...")
    from insightface.app import FaceAnalysis
    app = FaceAnalysis(name='buffalo_l', root='/app/models')
    app.prepare(ctx_id=0, det_size=(640, 640))
    
    while True:
        try:
            frame, cam_id = face_queue.get()
            faces = app.get(frame)
            for face in faces:
                if face.det_score < 0.6: continue
                bbox = face.bbox.astype(int).tolist()
                embedding = face.embedding.tolist()
                
                # We offload the Hub communication to upload_queue/worker to keep detector fast
                upload_queue.put(("face", frame.copy(), cam_id, "person", face.det_score, bbox, embedding))
        except Exception as e:
            print(f"[ERR] Face detector error: {e}")

def object_detector_worker(obj_queue, upload_queue):
    print("[*] Object Engine starting (YOLO World)...")
    from ultralytics import YOLOWorld
    model = YOLOWorld(OBJ_MODEL_PATH)
    model.set_classes(TARGET_CLASSES)
    
    while True:
        try:
            frame, cam_id = obj_queue.get()
            results = model.predict(frame, conf=0.4, verbose=False)
            if results:
                res = results[0]
                boxes = res.boxes.xyxy.cpu().numpy()
                confs = res.boxes.conf.cpu().numpy()
                cls_ids = res.boxes.cls.cpu().numpy().astype(int)
                names = res.names
                
                for i in range(len(boxes)):
                    label = names[cls_ids[i]]
                    if label == "person": continue # Handled by face detector or we can include it
                    bbox = boxes[i].astype(int).tolist()
                    upload_queue.put(("object", frame.copy(), cam_id, label, confs[i], bbox, None))
        except Exception as e:
            print(f"[ERR] Object detector error: {e}")

def upload_worker(upload_queue):
    print("[*] Hub Communicator started")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def process():
        while True:
            try:
                # get() is blocking, but we are in a thread? 
                # Actually mp.Queue.get() is fine here.
                item = upload_queue.get()
                dtype, frame, cam_id, label, conf, bbox, embedding = item
                
                # 1. Save snapshot locally
                snap_path = save_snapshot(frame, cam_id)
                
                hub_label = label
                if dtype == "face" and embedding:
                    # 2. Match face via Hub
                    match = await match_face(embedding)
                    if match.get("matched"):
                        hub_label = match.get("person_name", "Unknown Person")
                        print(f"[!!!] FACE MATCH: {hub_label} on {cam_id}")
                
                # 3. Send metadata to Hub
                success = await send_detection_result(cam_id, dtype, hub_label, conf, bbox, snap_path)
                if success:
                    print(f"[+] Result sent to Hub: {hub_label} on {cam_id}")
            except Exception as e:
                print(f"[ERR] Upload worker error: {e}")

    loop.run_until_complete(process())

def main():
    print(f"[*] Sentrix-AI Worker Agent starting | Worker ID: {HUB_WORKER_ID}")
    
    face_queue = mp.Queue(maxsize=10)
    obj_queue = mp.Queue(maxsize=10)
    live_queue = mp.Queue(maxsize=10)
    upload_queue = mp.Queue(maxsize=50)
    
    processes = []
    
    # Detector Processes
    p_face = mp.Process(target=face_detector_worker, args=(face_queue, upload_queue), daemon=True)
    p_face.start(); processes.append(p_face)
    
    p_obj = mp.Process(target=object_detector_worker, args=(obj_queue, upload_queue), daemon=True)
    p_obj.start(); processes.append(p_obj)
    
    # Hub Communicator (runs in a separate process too)
    p_hub = mp.Process(target=upload_worker, args=(upload_queue,), daemon=True)
    p_hub.start(); processes.append(p_hub)
    
    # Capture Processes (one per camera)
    num_cams = len(CAMERA_URLS)
    for i in range(num_cams):
        url = CAMERA_URLS[i].strip()
        name = CAMERA_NAMES[i].strip() if i < len(CAMERA_NAMES) else f"cam-{i+1}"
        
        # Resolve to Hub ID if available
        cam_id = HUB_CAMERA_MAPPING.get(name, name)
        
        p = mp.Process(target=capture_worker, args=(url, cam_id, face_queue, obj_queue, live_queue), daemon=True)
        p.start(); processes.append(p)

    print(f"[*] Started {num_cams} capture nodes.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[!] Stopping...")

if __name__ == "__main__":
    mp.set_start_method('spawn', force=True)
    main()
