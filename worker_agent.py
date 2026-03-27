"""
CCTV Worker Agent
==================
Run this on the machine that has the camera connected.
It captures frames, detects faces locally (using your best.pt YOLOv8 model),
and sends cropped face images to the server.

SETUP:
  pip install opencv-python requests ultralytics numpy

USAGE:
  python worker_agent.py --server http://your-server:8000 --user worker1 --password worker123 --camera 0

ARGS:
  --server      Server URL (default: http://localhost:8000)
  --user        Your worker username
  --password    Your worker password
  --camera      Camera index (0 = default webcam) or RTSP URL
  --camera-id   Name/ID shown on dashboard (e.g. "entrance-cam")
  --location    Physical location label (e.g. "Main Gate")
  --interval    Seconds between frame captures (default: 3)
  --model       Path to your YOLOv8 face model (default: models/best.pt)
  --no-model    Skip local face detection, send full frames to server
"""

import argparse, time, sys, os, threading
from concurrent.futures import ThreadPoolExecutor
import cv2
import numpy as np
import requests

def parse_args():
    p = argparse.ArgumentParser(description="CCTV Worker Agent")
    p.add_argument("--server", default="http://localhost:8000")
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--camera", default="0")
    p.add_argument("--camera-id", default="cam-1")
    p.add_argument("--location", default="Unknown Location")
    p.add_argument("--interval", type=float, default=3.0)
    p.add_argument("--model", default="models/best.pt")
    p.add_argument("--no-model", action="store_true")
    return p.parse_args()

def login(server: str, username: str, password: str) -> str:
    r = requests.post(f"{server}/api/login", json={"username": username, "password": password}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("role") not in ("admin", "worker"):
        print("ERROR: Only admin or worker can run agent.")
        sys.exit(1)
    print(f"✓ Logged in as {username} ({data['role']})")
    return data["token"]

def open_camera(source: str):
    src = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        print(f"ERROR: Cannot open camera: {source}")
        sys.exit(1)
    print(f"✓ Camera opened: {source}")
    return cap

def load_yolo(model_path: str):
    if not os.path.exists(model_path):
        print(f"⚠  Model not found at {model_path}. Running without local detection.")
        return None
    try:
        import torch
        # PyTorch 2.6+ security fix: allow YOLOv8 model classes
        try:
            from ultralytics.nn.tasks import DetectionModel
            from ultralytics.utils.ops import IterableSimpleNamespace
            if hasattr(torch.serialization, 'add_safe_globals'):
                torch.serialization.add_safe_globals([DetectionModel, IterableSimpleNamespace, dict])
        except Exception:
            # Fallback for older ultralytics/torch
            pass
            
        from ultralytics import YOLO
        # Performance tip: use Nano model for speed!
        model = YOLO(model_path)
        
        # Check for CUDA
        if torch.cuda.is_available():
            model.to('cuda')
            print(f"🚀 GPU Detected: Using CUDA for YOLOv8")
            # Speed tip: use Half Precision on GPU
            try: model.model.half() 
            except: pass
        else:
            print("ℹ  Using CPU for YOLOv8 (CUDA not available or torch-cpu installed)")
            
        print(f"✓ YOLOv8 model loaded: {model_path}")
        return model
    except ImportError:
        print("⚠  ultralytics not installed. pip install ultralytics")
        return None
    except Exception as e:
        print(f"⚠  Could not load model: {e}")
        # Final attempt: try loading with weights_only=False if it's a torch version issue
        try:
            import torch
            from ultralytics import YOLO
            # This is a bit of a hack but can solve the weights_only issue if the above failed
            import functools
            old_load = torch.load
            torch.load = functools.partial(old_load, weights_only=False)
            model = YOLO(model_path)
            torch.load = old_load # restore
            print(f"✓ YOLOv8 model loaded (compat mode): {model_path}")
            return model
        except Exception as e2:
            print(f"⚠  Still could not load model: {e2}")
            return None

def detect_faces_yolo(model, frame: np.ndarray) -> list[np.ndarray]:
    """Run YOLOv8 face detection, return list of face crop arrays."""
    results = model(frame, verbose=False)
    crops = []
    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            # add 10% padding
            pad_x = int((x2 - x1) * 0.1)
            pad_y = int((y2 - y1) * 0.1)
            x1 = max(0, x1 - pad_x)
            y1 = max(0, y1 - pad_y)
            x2 = min(frame.shape[1], x2 + pad_x)
            y2 = min(frame.shape[0], y2 + pad_y)
            crops.append(frame[y1:y2, x1:x2])
    return crops

def detect_faces_opencv(frame: np.ndarray) -> list[np.ndarray]:
    """Fallback: OpenCV Haar cascade face detection."""
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
    crops = []
    for (x, y, w, h) in faces:
        crops.append(frame[y:y+h, x:x+w])
    return crops

def motion_detected(prev_frame, curr_frame, threshold=1500) -> bool:
    """Simple frame-diff motion detection."""
    if prev_frame is None:
        return True
    diff = cv2.absdiff(prev_frame, curr_frame)
    # Only convert to gray if it has more than 1 channel
    gray = diff
    if len(diff.shape) == 3:
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 25, 255, cv2.THRESH_BINARY)
    return int(thresh.sum() / 255) > threshold

def send_frame(server: str, token: str, img: np.ndarray, camera_id: str, location: str) -> dict:
    # 70 quality is ~40% smaller than 85, much faster to upload with zero impact on detection
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    files = {"file": ("frame.jpg", buf.tobytes(), "image/jpeg")}
    data = {"camera_id": camera_id, "location": location}
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.post(f"{server}/api/upload-frame", files=files, data=data,
                          headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def main():
    args = parse_args()
    print("\n┌─────────────────────────────────┐")
    print("│  CCTV Worker Agent Starting...  │")
    print("└─────────────────────────────────┘")

    token = login(args.server, args.user, args.password)
    cap = open_camera(args.camera)
    model = None if args.no_model else load_yolo(args.model)
    use_yolo = model is not None

    prev_gray = None
    consecutive_errors = 0
    frames_sent = 0
    matches_found = 0

    print(f"\n● Monitoring started | camera: {args.camera_id} | location: {args.location}")
    print(f"● Interval: {args.interval}s | Detection: {'YOLOv8' if use_yolo else 'OpenCV Haar'}")
    print("● Press Ctrl+C to stop\n")

    executor = ThreadPoolExecutor(max_workers=4)
    
    def handle_upload(face_crop):
        nonlocal frames_sent, matches_found, consecutive_errors
        result = send_frame(args.server, token, face_crop, args.camera_id, args.location)
        status = result.get("status", "?")
        
        if status == "match":
            matches_found += 1
            print(f"\n🔴 MATCH: {result.get('person')} | conf: {result.get('confidence')}% | cam: {args.camera_id}")
        elif status == "error":
            consecutive_errors += 1
        else:
            consecutive_errors = 0
            frames_sent += 1
        
        # Compact status update
        sys.stdout.write(f"\r● Processing | Sent: {frames_sent} | Matches: {matches_found} | Camera: {args.camera_id}   ")
        sys.stdout.flush()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(1)
                continue

            # motion check (faster resize)
            curr_gray_small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 120))
            if not motion_detected(prev_gray, curr_gray_small):
                prev_gray = curr_gray_small
                time.sleep(args.interval)
                continue
            prev_gray = curr_gray_small

            # face detection
            if args.no_model:
                faces = [frame]
            elif use_yolo:
                faces = detect_faces_yolo(model, frame)
            else:
                faces = detect_faces_opencv(frame)

            if not faces:
                # Still show status even if no face
                sys.stdout.write(f"\r● Monitoring | Sent: {frames_sent} | Matches: {matches_found} | Camera: {args.camera_id}   ")
                sys.stdout.flush()
                time.sleep(args.interval)
                continue

            # send detected faces in parallel
            for face_crop in faces:
                if face_crop.size > 0:
                    executor.submit(handle_upload, face_crop.copy())

            time.sleep(args.interval)

    except KeyboardInterrupt:
        executor.shutdown(wait=False)
        print(f"\n\n● Stopped. Total frames sent: {frames_sent} | Matches found: {matches_found}")

    except KeyboardInterrupt:
        print(f"\n\n● Stopped. Total frames sent: {frames_sent} | Matches found: {matches_found}")
    finally:
        cap.release()

if __name__ == "__main__":
    main()
