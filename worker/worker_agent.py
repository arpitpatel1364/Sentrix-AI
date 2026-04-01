import argparse, time, sys, os, multiprocessing as mp

# Check for virtual environment
if not hasattr(sys, 'real_prefix') and sys.base_prefix == sys.prefix:
    try:
        import onnxruntime, cv2, requests, numpy
    except ImportError:
        print("\nERR: Required dependencies not found. Run using venv:")
        print("    ./venv/bin/python3 worker/worker_agent.py --user worker1 --password worker123 --camera 1\n")
        sys.exit(1)

from pathlib import Path
import cv2
import numpy as np
import requests

# --- CUDA SELF-HEALING ENVIRONMENT ---
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
LIBS_PATH = str(PROJECT_ROOT / "libs")

if LIBS_PATH not in os.environ.get("LD_LIBRARY_PATH", ""):
    os.environ["LD_LIBRARY_PATH"] = LIBS_PATH + ":" + os.environ.get("LD_LIBRARY_PATH", "")
    try:
        if sys.platform.startswith('linux'):
            os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception:
        pass

# ==========================================
# CCTV MULTI-PROCESS WORKER AGENT v2
# Two-Core Architecture:
#   Core 1 — Face Engine: continuous crop + upload
#   Core 2 — Object Engine: full frame + bbox draw + 30s cooldown
#
# FIXES in v2:
#   - Object detector now correctly uses BCHW input (not BHWC)
#   - Confidence = objectness × class_score (not class_score alone)
#   - Letterbox coordinate rescaling properly accounts for padding
# ==========================================

COCO_CLASSES = [
    "person", "bicycle", "car", "motorbike", "aeroplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "sofa",
    "pottedplant", "bed", "diningtable", "toilet", "tvmonitor", "laptop", "mouse", "remote", "keyboard",
    "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush"
]


def parse_args():
    base_dir = Path(__file__).resolve().parent
    default_face_model = base_dir / "models" / "best.onnx"
    default_obj_model  = PROJECT_ROOT / "yolov4.onnx"

    p = argparse.ArgumentParser(description="Sentrix-AI Multi-Process CCTV Worker (Two-Core)")
    p.add_argument("--server",    default="http://localhost:8000")
    p.add_argument("--user",      required=True)
    p.add_argument("--password",  required=True)
    p.add_argument("--camera",    nargs='+', default=["0"],            help="Camera indices or RTSP URLs")
    p.add_argument("--camera-id", nargs='+', default=["cam-1"],        help="Camera IDs")
    p.add_argument("--location",  nargs='+', default=["Unknown Location"], help="Locations")
    p.add_argument("--interval",  type=float, default=0.5,             help="Frame capture interval (s)")
    p.add_argument("--face-model", default=str(default_face_model))
    p.add_argument("--obj-model",  default=str(default_obj_model))
    p.add_argument("--no-face",   action="store_true")
    p.add_argument("--no-obj",    action="store_true")
    p.add_argument("--objects",   nargs='+', default=[], help="Specific objects to detect, e.g., 'car person'. If empty, detects all.")
    return p.parse_args()


def login(server, username, password):
    try:
        r = requests.post(f"{server}/api/login", json={"username": username, "password": password}, timeout=10)
        r.raise_for_status()
        return r.json()["token"]
    except Exception as e:
        print(f"[ERR] Login failed: {e}")
        sys.exit(1)


def open_camera(source):
    try:
        src = int(source)
    except Exception:
        src = source

    backends = [cv2.CAP_ANY, cv2.CAP_V4L2] if sys.platform.startswith('linux') else [cv2.CAP_ANY, cv2.CAP_DSHOW]

    def try_open(s):
        for b in backends:
            try:
                cap = cv2.VideoCapture(s, b)
                if cap.isOpened():
                    print(f"[*] Camera {s} opened with backend {b}")
                    return cap
                cap.release()
            except Exception:
                continue
        return None

    cap = try_open(src)
    if cap:
        return cap

    if isinstance(src, int):
        print(f"[!] Camera {src} unavailable — scanning alternatives...")
        for i in range(10):
            if i == src:
                continue
            cap = try_open(i)
            if cap:
                print(f"[!] Redirected to camera index {i}")
                return cap

    cap = cv2.VideoCapture(src)
    if cap.isOpened():
        return cap

    return None


def _letterbox_square(im, size=640, color=(114, 114, 114)):
    """Resize to square with letterboxing. Returns (padded_img, scale, (pad_left, pad_top))."""
    h, w = im.shape[:2]
    scale = size / max(h, w)
    nw, nh = int(round(w * scale)), int(round(h * scale))
    im = cv2.resize(im, (nw, nh), interpolation=cv2.INTER_LINEAR)
    pl = (size - nw) // 2
    pt = (size - nh) // 2
    pr = size - nw - pl
    pb = size - nh - pt
    im = cv2.copyMakeBorder(im, pt, pb, pl, pr, cv2.BORDER_CONSTANT, value=color)
    return im, scale, (pl, pt)


# ============================================================
# PROCESS: CAMERA CAPTURE — feeds both face and object queues
# ============================================================
def capture_worker(cam_src, cam_id, location, interval, face_queue, obj_queue):
    print(f"[*] Capture Node started: {cam_id} ({cam_src})")
    cap = open_camera(cam_src)
    if not cap or not cap.isOpened():
        print(f"[ERR] Failed to open camera {cam_id}")
        return

    prev_gray = None
    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(1)
            continue

        # Motion gate — skip static scenes
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (160, 120))
        if prev_gray is not None:
            diff = cv2.absdiff(prev_gray, gray)
            if np.mean(diff) < 2.0:
                time.sleep(0.1)
                continue
        prev_gray = gray

        frame_copy = frame.copy()

        try:
            if face_queue and not face_queue.full():
                face_queue.put_nowait((frame_copy, cam_id, location))
        except Exception:
            pass

        try:
            if obj_queue and not obj_queue.full():
                obj_queue.put_nowait((frame_copy, cam_id, location))
        except Exception:
            pass

        time.sleep(interval)


# ============================================================
# PROCESS: CORE 1 — FACE DETECTOR (YOLOv8/v10 compatible)
# ============================================================
def face_detector_worker(face_model, face_queue, upload_queue, server, token):
    print(f"[*] Core 1 — Face Engine starting")

    last_face_times = {}
    import onnxruntime as ort

    face_session = None
    if os.path.exists(face_model):
        try:
            providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
            face_session = ort.InferenceSession(face_model, providers=providers)
            print(f"[+] Core 1: Face Engine ready | providers: {face_session.get_providers()}")
        except Exception as e:
            print(f"[ERR] Core 1: Could not load face model: {e}")
    else:
        print(f"[WARN] Core 1: Face model not found at {face_model}")

    while True:
        try:
            if face_queue is None: break
            try:
                frame, cam_id, location = face_queue.get(timeout=5)
            except mp.queues.Empty:
                continue

            if face_session is None:
                continue

            if time.time() - last_face_times.get(cam_id, 0) < 0.4:
                continue

            h_orig, w_orig = frame.shape[:2]

            img, scale, (pad_left, pad_top) = _letterbox_square(frame, 640)
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            blob = rgb.astype(np.float32) / 255.0
            blob = np.transpose(blob, (2, 0, 1))   # HWC → CHW
            blob = np.expand_dims(blob, axis=0)     # → BCHW

            input_name = face_session.get_inputs()[0].name
            outputs = face_session.run(None, {input_name: blob})
            raw_out = outputs[0]   # (1, 5, 8400) or (1, 84, 8400)

            # Transpose if needed: (1, 5, 8400) → (8400, 5)
            if raw_out.shape[1] < raw_out.shape[2]:
                out = raw_out[0].T
            else:
                out = raw_out[0]

            boxes, confs = [], []
            for row in out:
                conf = float(row[4]) if len(row) > 4 else 0
                if conf < 0.4:
                    continue
                cx, cy, fw, fh = row[0:4]
                # Undo letterbox
                x1 = int((cx - fw / 2 - pad_left) / scale)
                y1 = int((cy - fh / 2 - pad_top)  / scale)
                w  = int(fw / scale)
                h  = int(fh / scale)
                x1, y1 = max(0, x1), max(0, y1)
                boxes.append([x1, y1, w, h])
                confs.append(conf)

            faces_found = 0
            if boxes:
                indices = cv2.dnn.NMSBoxes(boxes, confs, 0.4, 0.45)
                if len(indices) > 0:
                    for i in indices.flatten():
                        x, y, w, h = boxes[i]
                        x2, y2 = min(w_orig, x + w), min(h_orig, y + h)
                        if x2 <= x or y2 <= y or w < 20 or h < 20:
                            continue
                        pad = int(w * 0.15)
                        crop = frame[
                            max(0, y - pad): min(h_orig, y2 + pad),
                            max(0, x - pad): min(w_orig, x2 + pad)
                        ]
                        if crop.size == 0:
                            continue
                        try:
                            if not upload_queue.full():
                                upload_queue.put_nowait(("face", crop.copy(), cam_id, location, "person", confs[i]))
                                faces_found += 1
                        except Exception:
                            pass

            if faces_found > 0:
                last_face_times[cam_id] = time.time()
                print(f"[FACE] {faces_found} face(s) queued | cam: {cam_id}")

        except Exception as e:
            import traceback
            print(f"[!] Core 1 error: {e}")
            traceback.print_exc()


# ============================================================
# CLASS: DETECTION TRACKER — per-label cooldown
# ============================================================
class DetectionTracker:
    def __init__(self, cooldown=30):
        self.cooldown  = cooldown
        self.last_seen = {}   # {cam_id: {label: timestamp}}

    def should_upload(self, cam_id, label):
        now = time.time()
        if cam_id not in self.last_seen:
            self.last_seen[cam_id] = {}
        if now - self.last_seen[cam_id].get(label, 0) > self.cooldown:
            self.last_seen[cam_id][label] = now
            return True
        return False


# ============================================================
# PROCESS: CORE 2 — OBJECT DETECTOR (v3 — Fixed)
#
# Architecture: Detection → annotation_queue → Annotator Process → upload_queue
# This ensures heavy drawing/encoding never blocks the detector loop.
#
# Coordinate math: unscale center first, then convert to corners
# (matching the backend object_engine.py approach)
# ============================================================
def object_detector_worker(obj_model, obj_queue, annotation_queue, target_objects):
    print(f"[*] Core 2 — Object Engine starting")
    tracker = DetectionTracker(cooldown=15)
    INPUT_SIZE = 416

    obj_session = None
    if os.path.exists(obj_model):
        try:
            import onnxruntime as ort
            providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
            try:
                obj_session = ort.InferenceSession(obj_model, providers=providers)
                print(f"[+] Core 2: Object Engine ready | providers: {obj_session.get_providers()}")
            except Exception:
                obj_session = ort.InferenceSession(obj_model, providers=['CPUExecutionProvider'])
                print("[-] Core 2: Object Engine (CPU fallback)")
        except Exception as e:
            print(f"[ERR] Core 2: Could not load object model: {e}")
    else:
        print(f"[WARN] Core 2: Object model not found at {obj_model} — object detection disabled")

    while True:
        try:
            if obj_queue is None: break
            try:
                frame, cam_id, location = obj_queue.get(timeout=5)
            except mp.queues.Empty:
                continue

            if obj_session is None:
                continue

            h_orig, w_orig = frame.shape[:2]
            input_name = obj_session.get_inputs()[0].name

            # ── Preprocess ── letterbox → RGB → BHWC ───────────────────────
            padded, scale, (pad_left, pad_top) = _letterbox_square(frame, INPUT_SIZE)
            rgb  = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
            blob = rgb.astype(np.float32) / 255.0
            blob = np.expand_dims(blob, axis=0)     # HWC → BHWC

            outs = obj_session.run(None, {input_name: blob})

            boxes, confs, class_ids = [], [], []
            for out in outs:
                out = out.reshape(-1, out.shape[-1])
                for d in out:
                    objectness = float(d[4])
                    if objectness < 0.3:
                        continue
                    scores = d[5:]
                    cid = int(np.argmax(scores))
                    conf = objectness * float(scores[cid])
                    if conf < 0.4:
                        continue

                    # Coords are in 416px letterboxed space
                    cx_416 = float(d[0])
                    cy_416 = float(d[1])
                    bw_416 = float(d[2])
                    bh_416 = float(d[3])

                    # Unscale center first, then convert to top-left corner
                    cx_orig = (cx_416 - pad_left) / scale
                    cy_orig = (cy_416 - pad_top)  / scale
                    bw_orig = bw_416 / scale
                    bh_orig = bh_416 / scale

                    x = int(cx_orig - bw_orig / 2)
                    y = int(cy_orig - bh_orig / 2)
                    w = int(bw_orig)
                    h = int(bh_orig)

                    # Clamp to frame boundaries
                    x = max(0, min(x, w_orig - 1))
                    y = max(0, min(y, h_orig - 1))
                    w = min(w, w_orig - x)
                    h = min(h, h_orig - y)

                    if w > 5 and h > 5:
                        boxes.append([x, y, w, h])
                        confs.append(conf)
                        class_ids.append(cid)

            if not boxes:
                continue

            indices = cv2.dnn.NMSBoxes(boxes, confs, 0.4, 0.45)
            if len(indices) == 0:
                continue

            detected = []
            for i in indices.flatten():
                label = COCO_CLASSES[class_ids[i]] if class_ids[i] < len(COCO_CLASSES) else "unknown"
                if target_objects and label not in target_objects:
                    continue
                detected.append({"bbox": boxes[i], "label": label, "conf": confs[i]})

            # Best detection per label
            label_groups = {}
            for obj in detected:
                lbl = obj["label"]
                if lbl not in label_groups or obj["conf"] > label_groups[lbl]["conf"]:
                    label_groups[lbl] = obj

            for label, best_obj in label_groups.items():
                if not tracker.should_upload(cam_id, label):
                    continue

                print(f"[OBJ] DETECTED: {label} ({int(best_obj['conf']*100)}%) | cam: {cam_id}")

                # Offload drawing + crop + upload to annotation subprocess
                try:
                    if not annotation_queue.full():
                        annotation_queue.put_nowait((
                            frame.copy(), cam_id, location,
                            best_obj["bbox"], best_obj["label"], best_obj["conf"],
                            h_orig, w_orig
                        ))
                except Exception:
                    pass

        except Exception as e:
            import traceback
            print(f"[!] Core 2 error: {e}")
            traceback.print_exc()


# ============================================================
# PROCESS: ANNOTATION WORKER — draws bbox + crops + queues upload
# Runs in its own process so drawing never blocks detection
# ============================================================
def _annotation_worker(annotation_queue, upload_queue):
    """Receives raw detection data, draws clean bounding boxes on the
    full frame, then crops the annotated region for upload."""

    while True:
        try:
            data = annotation_queue.get(timeout=10)
        except Exception:
            continue

        try:
            frame, cam_id, location, bbox, label, conf, h_orig, w_orig = data
            x, y, w, h = bbox

            # ── Draw on full frame first ──────────────────────────────────
            annotated = frame.copy()

            # Box coordinates (already clamped in detector)
            x1, y1 = x, y
            x2, y2 = min(x + w, w_orig), min(y + h, h_orig)

            # Draw clean rectangle
            color = (0, 200, 255)  # orange-ish
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            # Draw label background + text
            tag = f"{label.upper()} {int(conf * 100)}%"
            (tw, th), baseline = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
            tag_y = max(y1 - 6, th + 4)
            cv2.rectangle(annotated, (x1, tag_y - th - 4), (x1 + tw + 6, tag_y + 2), color, -1)
            cv2.putText(annotated, tag, (x1 + 3, tag_y - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)

            # ── Crop annotated region with padding ────────────────────────
            pad_x = int(w * 0.25)
            pad_y = int(h * 0.25)
            crop_x1 = max(0, x1 - pad_x)
            crop_y1 = max(0, y1 - pad_y)
            crop_x2 = min(w_orig, x2 + pad_x)
            crop_y2 = min(h_orig, y2 + pad_y)

            crop = annotated[crop_y1:crop_y2, crop_x1:crop_x2]

            if crop.size == 0:
                continue

            try:
                if not upload_queue.full():
                    upload_queue.put_nowait(("object", crop.copy(), cam_id, location, label, conf))
            except Exception:
                pass

        except Exception as e:
            print(f"[!] Annotation error: {e}")


# ============================================================
# PROCESS: UPLOADER — sends to backend
# ============================================================
def upload_worker(server, token, upload_queue):
    print("[*] Uploader started")
    headers = {"Authorization": f"Bearer {token}"}

    while True:
        try:
            dtype, img, cam_id, location, label, conf = upload_queue.get(timeout=10)
            _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
            img_bytes = buf.tobytes()

            if dtype == "face":
                url   = f"{server}/api/upload-frame"
                files = {"file": ("face.jpg", img_bytes, "image/jpeg")}
                data  = {"camera_id": cam_id, "location": location}
            else:
                url   = f"{server}/api/upload-object"
                files = {"file": ("object.jpg", img_bytes, "image/jpeg")}
                data  = {
                    "camera_id":    cam_id,
                    "location":     location,
                    "object_label": label,
                    "confidence":   str(conf)
                }

            r = requests.post(url, files=files, data=data, headers=headers, timeout=15)
            if r.status_code == 200:
                res = r.json()
                if dtype == "face":
                    status = res.get("status", "stored")
                    if status == "match":
                        print(f"[!!!] FACE MATCH: {res.get('person')} | cam: {cam_id}")
                else:
                    print(f"[+] OBJECT LOGGED: {label} | cam: {cam_id}")
            else:
                print(f"[WARN] Upload {dtype} returned HTTP {r.status_code}: {r.text[:120]}")

        except Exception as e:
            if "timeout" not in str(e).lower() and "empty" not in str(e).lower():
                print(f"[!] Upload error: {e}")


# ============================================================
# MAIN
# ============================================================
def main():
    args = parse_args()
    print("╔═══════════════════════════════════════╗")
    print("║  Sentrix-AI Two-Core Worker  v2.0     ║")
    print("╚═══════════════════════════════════════╝")
    print(f"  Server  : {args.server}")
    print(f"  Cameras : {args.camera}")
    print(f"  Cam IDs : {args.camera_id}")
    print(f"  Face    : {'OFF' if args.no_face else 'ON'}")
    print(f"  Objects : {'OFF' if args.no_obj else 'ON'}")
    print("")

    token = login(args.server, args.user, args.password)
    print(f"[+] Authenticated as {args.user}")

    processes = []

    face_queue   = mp.Queue(maxsize=8)  if not args.no_face else None
    obj_queue    = mp.Queue(maxsize=4)  if not args.no_obj  else None
    upload_queue = mp.Queue(maxsize=40)
    annotation_queue = mp.Queue(maxsize=20) if not args.no_obj else None

    if not args.no_face:
        p = mp.Process(target=face_detector_worker,
                       args=(args.face_model, face_queue, upload_queue, args.server, token),
                       daemon=True)
        p.start(); processes.append(p)
        print("[+] Core 1 (Face) started")

    if not args.no_obj:
        target_objs = [o.lower() for o in args.objects]
        p = mp.Process(target=object_detector_worker,
                       args=(args.obj_model, obj_queue, annotation_queue, target_objs),
                       daemon=True)
        p.start(); processes.append(p)
        print("[+] Core 2 (Object) started")

        p_ann = mp.Process(target=_annotation_worker,
                           args=(annotation_queue, upload_queue),
                           daemon=True)
        p_ann.start(); processes.append(p_ann)
        print("[+] Annotator started")

    p = mp.Process(target=upload_worker,
                   args=(args.server, token, upload_queue),
                   daemon=True)
    p.start(); processes.append(p)
    print("[+] Uploader started")

    num_cams = len(args.camera)
    for i in range(num_cams):
        cam_src = args.camera[i]
        cam_id  = args.camera_id[i] if i < len(args.camera_id) else f"cam-{i+1}"
        loc     = args.location[i]  if i < len(args.location)  else "Global Perimeter"
        p = mp.Process(target=capture_worker,
                       args=(cam_src, cam_id, loc, args.interval, face_queue, obj_queue),
                       daemon=True)
        p.start(); processes.append(p)
        print(f"[+] Capture node {cam_id} started")

    print(f"\n[RUNNING] {num_cams} camera(s) | Face: {'OFF' if args.no_face else 'ON'} | Objects: {'OFF' if args.no_obj else 'ON'}")
    print("[RUNNING] Press Ctrl+C to stop all\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Shutting down...")
        headers = {"Authorization": f"Bearer {token}"}
        for i in range(num_cams):
            cam_id = args.camera_id[i] if i < len(args.camera_id) else f"cam-{i+1}"
            try:
                requests.post(
                    f"{args.server}/api/worker/offline",
                    data={"camera_id": cam_id},
                    headers=headers,
                    timeout=5
                )
                print(f"[-] Node {cam_id} marked offline")
            except Exception:
                pass
        for p in processes:
            p.terminate()
        print("[!] All processes stopped")


if __name__ == "__main__":
    mp.set_start_method('spawn', force=True)
    main()
