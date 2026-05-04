import argparse, time, sys, os, multiprocessing as mp, subprocess, threading

# Dependencies check
if not hasattr(sys, 'real_prefix') and sys.base_prefix == sys.prefix:
    try:
        import onnxruntime, cv2, requests, numpy
    except ImportError:
        print("\nERR: Required dependencies missing. Run using venv.")
        sys.exit(1)

from pathlib import Path
import cv2
import numpy as np
import requests

# --- CONFIG ---
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


def parse_args():
    worker_dir = Path(__file__).resolve().parent
    default_face_model = worker_dir / "models" / "best.onnx"
    default_obj_model  = worker_dir / "models" / "yolov8s-worldv2.pt"

    p = argparse.ArgumentParser(description="Sentrix-AI Multi-Process CCTV Worker (Two-Core)")
    p.add_argument("--server",    default="http://[IP_ADDRESS]")
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
    p.add_argument("--cpu",       action="store_true", help="Force CPU inference for all engines")
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

    # Preference:
    # Linux   -> CAP_V4L2 (The standard)
    # Windows -> CAP_DSHOW (More stable for many USB cams) -> CAP_MSMF (Modern, often default)
    if sys.platform.startswith('linux'):
        backends = [cv2.CAP_V4L2, cv2.CAP_ANY]
    else:
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]

    def try_open(s):
        for b in backends:
            try:
                cap = cv2.VideoCapture(s, b)
                if cap.isOpened():
                    # SMOKE TEST: Some backends (MSMF) "open" but fail the first grab
                    ret, test_frame = cap.read()
                    if ret and test_frame is not None:
                        print(f"[*] Camera {s} opened with backend {b}")
                        return cap
                    else:
                        print(f"[!] Backend {b} opened for camera {s} but failed test read. Skipping.")
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


def is_in_roi(bbox, roi, im_w, im_h):
    """
    Check if the center of a bounding box [x, y, w, h] 
    is within the normalized ROI [x1, y1, x2, y2].
    Defaults to full-frame (0.0 to 1.0) if no ROI is specified.
    """
    if not roi: 
        # Default to full frame
        roi = [0.0, 0.0, 1.0, 1.0]
    
    bx, by, bw, bh = bbox
    cx, cy = (bx + bw/2) / im_w, (by + bh/2) / im_h
    
    x1, y1, x2, y2 = roi
    mx1, mx2 = min(x1, x2), max(x1, x2)
    my1, my2 = min(y1, y2), max(y1, y2)
    
    inside = (mx1 <= cx <= mx2) and (my1 <= cy <= my2)
    
    # print(f"[DEBUG] ROI Check: Center({cx:.3f}, {cy:.3f}) inside [{mx1:.3f}, {my1:.3f}, {mx2:.3f}, {my2:.3f}] -> {inside}")
    return inside


def capture_worker(cam_src, cam_id, location, interval, face_queue, obj_queue, live_queue, cam_configs):
    print(f"[*] Capture Node started: {cam_id} ({cam_src})")
    cap = open_camera(cam_src)
    if not cap or not cap.isOpened():
        print(f"[ERR] Failed to open camera {cam_id}")
        return

    prev_gray = None
    
    while True:
        try:
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
            
            # Detection queues now get FULL frame
            try:
                if obj_queue and not obj_queue.full():
                    obj_queue.put_nowait((frame_copy.copy(), cam_id, location))
            except Exception:
                pass

            try:
                if face_queue and not face_queue.full():
                    face_queue.put_nowait((frame_copy.copy(), cam_id, location))
            except Exception:
                pass

            try:
                if live_queue and not live_queue.full():
                    live_queue.put_nowait((frame_copy, cam_id, location))
            except Exception:
                pass

            time.sleep(0.03)  # High-frequency capture for live stream (~30 FPS)
        except KeyboardInterrupt:
            break


def face_detector_worker(face_model, face_queue, upload_queue, server, token, cam_configs, force_cpu=False):
    print(f"[*] Core 1 — Face Engine starting")

    last_face_times = {}
    import onnxruntime as ort

    face_session = None
    if os.path.exists(face_model):
        try:
            providers = ['CPUExecutionProvider']
            if not force_cpu:
                try:
                    if 'CUDAExecutionProvider' in ort.get_available_providers():
                        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
                except Exception:
                    pass
            
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

            config = cam_configs.get(cam_id, {})
            if not config.get("face_enabled", True):
                time.sleep(1) # Feature disabled
                continue

            if time.time() - last_face_times.get(cam_id, 0) < 0.4:
                continue

            h_orig, w_orig = frame.shape[:2]
            const_roi = config.get("roi")
            
            # ROI Optimized Crop
            crop_frame = frame
            off_x, off_y = 0, 0
            if const_roi and len(const_roi) == 4:
                x1_n, y1_n, x2_n, y2_n = const_roi
                if x1_n > 0.001 or y1_n > 0.001 or x2_n < 0.999 or y2_n < 0.999:
                    off_x = int(min(x1_n, x2_n) * w_orig)
                    off_y = int(min(y1_n, y2_n) * h_orig)
                    ex = int(max(x1_n, x2_n) * w_orig)
                    ey = int(max(y1_n, y2_n) * h_orig)
                    
                    crop_frame = frame[off_y:ey, off_x:ex]
                    if crop_frame.size == 0:
                        crop_frame = frame
                        off_x, off_y = 0, 0

            img, scale, (pad_left, pad_top) = _letterbox_square(crop_frame, 640)
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            blob = rgb.astype(np.float32) / 255.0
            blob = np.transpose(blob, (2, 0, 1))   # HWC → CHW
            blob = np.expand_dims(blob, axis=0)     # → BCHW

            input_name = face_session.get_inputs()[0].name
            outputs = face_session.run(None, {input_name: blob})
            raw_out = outputs[0]

            if raw_out.shape[1] < raw_out.shape[2]:
                out = raw_out[0].T
            else:
                out = raw_out[0]

            boxes, confs = [], []
            for row in out:
                conf = float(row[4]) if len(row) > 4 else 0
                if conf < 0.4: continue
                cx, cy, fw, fh = row[0:4]
                
                # Undo letterbox (local to crop)
                lx = int((cx - fw / 2 - pad_left) / scale)
                ly = int((cy - fh / 2 - pad_top)  / scale)
                lw = int(fw / scale)
                lh = int(fh / scale)
                
                # Translate back to Full Frame
                fx, fy = max(0, off_x + lx), max(0, off_y + ly)
                fw_full, fh_full = int(fw / scale), int(fh / scale)
                
                # Mandatory ROI Filter
                if not is_in_roi([fx, fy, fw_full, fh_full], const_roi, w_orig, h_orig):
                    continue

                face_found = True
                boxes.append([fx, fy, fw_full, fh_full])
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
                        # --- SIGHTING CONTEXT PADDING ---
                        # Increased to 40% for backend InsightFace compatibility
                        pad = int(max(w, h) * 0.40)
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

        except KeyboardInterrupt:
            break
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


def object_detector_worker(obj_model, obj_queue, annotation_queue, target_objects, cam_configs, force_cpu=False):
    print(f"[*] Core 2 — Object Engine starting (YOLO World)")
    tracker = DetectionTracker(cooldown=15)

    obj_model_instance = None
    try:
        import torch
        from ultralytics import YOLOWorld
        from ultralytics.nn.tasks import WorldModel
        
        # --- PYTORCH 2.6+ SECURITY FIX ---
        if not hasattr(torch, '_original_load'):
            torch._original_load = torch.load
            def _safe_load(*args, **kwargs):
                kwargs['weights_only'] = False
                return torch._original_load(*args, **kwargs)
            torch.load = _safe_load
        # ---------------------------------

        
        # Clear VRAM first
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        # Use FP16 for ~50% VRAM savings
        device = 'cpu' if force_cpu else ('cuda' if torch.cuda.is_available() else 'cpu')
        
        try:
            print(f"[*] Core 2: Loading {obj_model} on {device}...")
            obj_model_instance = YOLOWorld(obj_model)
            obj_model_instance.to(device)
            # Note: ultralytics will auto-manage fp16 if supported/requested during predict
        except Exception as e:
            if not force_cpu and "out of memory" in str(e).lower():
                print(f"[WARN] Core 2: GPU OOM. Falling back to CPU...")
                obj_model_instance = YOLOWorld(obj_model)
                obj_model_instance.to('cpu')
            else:
                raise e
        
        # Set default vocabulary
        classes = target_objects if target_objects else TARGET_CLASSES
        obj_model_instance.set_classes(classes)
        
        print(f"[+] Core 2: Object Engine ready | device: {obj_model_instance.device}")
    except Exception as e:
        print(f"[ERR] Core 2: Could not load YOLO World model: {e}")

    while True:
        try:
            if obj_queue is None: break
            try:
                frame, cam_id, location = obj_queue.get(timeout=5)
            except mp.queues.Empty:
                continue

            if obj_model_instance is None:
                continue

            config = cam_configs.get(cam_id, {})
            if not config.get("obj_enabled", True):
                time.sleep(1) # Feature disabled
                continue

            h_orig, w_orig = frame.shape[:2]
            const_roi = config.get("roi")

            # ROI Optimized Crop
            crop_frame = frame
            off_x, off_y = 0, 0
            if const_roi and len(const_roi) == 4:
                x1_n, y1_n, x2_n, y2_n = const_roi
                if x1_n > 0.001 or y1_n > 0.001 or x2_n < 0.999 or y2_n < 0.999:
                    off_x = int(min(x1_n, x2_n) * w_orig)
                    off_y = int(min(y1_n, y2_n) * h_orig)
                    ex = int(max(x1_n, x2_n) * w_orig)
                    ey = int(max(y1_n, y2_n) * h_orig)
                    
                    crop_frame = frame[off_y:ey, off_x:ex]
                    if crop_frame.size == 0:
                        crop_frame = frame
                        off_x, off_y = 0, 0

            # Inference on Crop
            results = obj_model_instance.predict(crop_frame, conf=0.4, verbose=False)
            
            if not results: continue

            res = results[0]
            boxes = res.boxes.xywh.cpu().numpy()  # [cx, cy, w, h] (relative to crop)
            confs = res.boxes.conf.cpu().numpy()
            cls_ids = res.boxes.cls.cpu().numpy().astype(int)
            names = res.names

            label_groups = {}
            for i in range(len(boxes)):
                label = names[cls_ids[i]]
                if label == "person": continue
                conf = float(confs[i])
                cx, cy, w, h = boxes[i]
                
                # Convert to full-frame pixels
                fx = int(off_x + (cx - w/2))
                fy = int(off_y + (cy - h/2))
                fw, fh = int(w), int(h)
                
                # Mandatory ROI Filter
                if not is_in_roi([fx, fy, fw, fh], const_roi, w_orig, h_orig):
                    continue
                
                # Clamp to full frame
                fx = max(0, min(fx, w_orig - 1))
                fy = max(0, min(fy, h_orig - 1))
                fw = int(min(fw, w_orig - fx))
                fh = int(min(fh, h_orig - fy))

                if fw < 5 or fh < 5: continue

                if label not in label_groups or conf > label_groups[label]["conf"]:
                    label_groups[label] = {
                        "bbox": [fx, fy, fw, fh],
                        "label": label,
                        "conf": conf
                    }

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

        except KeyboardInterrupt:
            break
        except Exception as e:
            import traceback
            print(f"[!] Core 2 error: {e}")
            traceback.print_exc()


def _annotation_worker(annotation_queue, upload_queue):
    """Receives raw detection data, draws clean bounding boxes on the
    full frame, then crops the annotated region for upload."""

    while True:
        try:
            data = annotation_queue.get(timeout=10)
        except (mp.queues.Empty, KeyboardInterrupt):
            if isinstance(sys.exc_info()[0], KeyboardInterrupt): break
            continue

        try:
            frame, cam_id, location, bbox, label, conf, h_orig, w_orig = data
            x, y, w, h = bbox

            # ── Draw on full frame first ──────────────────────────────────
            annotated = frame.copy()

            # Box coordinates (already clamped in detector)
            x1, y1 = x, y
            x2, y2 = min(x + w, w_orig), min(y + h, h_orig)

            # --- STYLING: Thin Green Box ---
            color = (0, 255, 0)  # Pure Green (BGR)
            thickness = 1         # "Thin"
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness)

            # Draw label tag
            tag = f"{label.upper()} {int(conf * 100)}%"
            font = cv2.FONT_HERSHEY_DUPLEX
            font_scale = 0.45
            (tw, th), baseline = cv2.getTextSize(tag, font, font_scale, 1)
            
            # Label background (filled rectangle)
            cv2.rectangle(annotated, (x1, y1 - th - 10), (x1 + tw + 10, y1), color, -1)
            # Label text
            cv2.putText(annotated, tag, (x1 + 5, y1 - 5), font, font_scale, (0, 0, 0), 1, cv2.LINE_AA)

            # --- NO CROP: Upload full annotated frame ---
            try:
                if not upload_queue.full():
                    upload_queue.put_nowait(("object", annotated.copy(), cam_id, location, label, conf))
            except Exception:
                pass

        except Exception as e:
            print(f"[!] Annotation error: {e}")


def upload_worker(server, token, upload_queue, cam_configs):
    print("[*] Uploader started")
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    while True:
        try:
            try:
                dtype, img, cam_id, location, label, conf = upload_queue.get(timeout=10)
            except (mp.queues.Empty, KeyboardInterrupt):
                if isinstance(sys.exc_info()[0], KeyboardInterrupt): break
                continue
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

            print(f"[DEBUG] Uploader: Processing {dtype} from {cam_id}...")
            try:
                r = session.post(url, files=files, data=data, timeout=15)
                if r.status_code == 200:
                    print(f"[DEBUG] Uploader: POST {dtype} success (200)")
                    res = r.json()
                    # Live update config
                    if "config" in res and res["config"] != cam_configs.get(cam_id):
                        cam_configs[cam_id] = res["config"]
                        print(f"[*] CONFIG SYNC: {cam_id} settings updated")
                        
                    if dtype == "face":
                        status = res.get("status", "stored")
                        if status == "match":
                            print(f"[!!!] FACE MATCH: {res.get('person')} | cam: {cam_id}")
                    else:
                        print(f"[+] OBJECT LOGGED: {label} | cam: {cam_id}")
                else:
                    print(f"[WARN] Upload {dtype} returned HTTP {r.status_code}: {r.text[:120]}")
            except Exception as net_err:
                print(f"[ERR] Uploader network failure: {net_err}")

        except Exception as e:
            if "timeout" not in str(e).lower() and "empty" not in str(e).lower():
                print(f"[!] Upload error: {e}")


# ============================================================
# PROCESS: LIVE STREAMER — sends raw frames for dashboard
# ============================================================
def live_stream_worker(server, token, live_queue, cam_configs):
    print("[*] H.264 Live Streamer starting (FFmpeg-powered)")
    headers = {"Authorization": f"Bearer {token}"}
    session = requests.Session()
    session.headers.update(headers)
    
    # Pre-calculated MJPEG intervals to avoid dashboard "Black Screen"
    # We push 1 JPEG every 5 frames for the preview <img> tags
    mjpeg_counter = 0
    mjpeg_interval = 5 
    
    # Per-camera FFmpeg processes
    # { cam_id: { "proc": subprocess, "last_active": time } }
    ffmpeg_nodes = {}

    ffmpeg_exe = "ffmpeg"
    try:
        from static_ffmpeg import run
        ffmpeg_exe, _ = run.get_or_fetch_platform_executables_else_raise()
        print(f"[*] H.264: Using static-ffmpeg binary at {ffmpeg_exe}")
    except (ImportError, Exception) as e:
        print(f"[!] H.264: static-ffmpeg dependency not ready ({e}). Falling back to system 'ffmpeg'.")

    while True:
        try:
            try:
                frame, cam_id, _ = live_queue.get(timeout=2)
            except (mp.queues.Empty, KeyboardInterrupt):
                if isinstance(sys.exc_info()[0], KeyboardInterrupt): break
                continue
            
            config = cam_configs.get(cam_id, {})
            if not config.get("stream_enabled", True):
                if cam_id in ffmpeg_nodes:
                    ffmpeg_nodes[cam_id]["proc"].terminate()
                    del ffmpeg_nodes[cam_id]
                continue

            h, w = frame.shape[:2]
            
            # 1. Ensure FFmpeg process exists for this camera
            if cam_id not in ffmpeg_nodes:
                print(f"[*] Initializing H.264 pipeline for {cam_id} ({w}x{h})")
                cmd = [
                    ffmpeg_exe,
                    '-f', 'rawvideo',
                    '-pixel_format', 'bgr24',
                    '-video_size', f'{w}x{h}',
                    '-i', '-',
                    '-c:v', 'libx264',
                    '-preset', 'ultrafast',
                    '-tune', 'zerolatency',
                    '-pix_fmt', 'yuv420p',
                    '-g', '30',
                    '-f', 'mpegts',
                    '-'
                ]
                try:
                    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                    ffmpeg_nodes[cam_id] = {"proc": proc, "last_active": time.time(), "url": f"{server}/api/upload-live-h264"}
                    
                    # Task to read ffmpeg stdout and POST to server
                    def _stream_reader(c_id, node_proc, upload_url):
                        while True:
                            try:
                                chunk = node_proc.stdout.read(4096)
                                if not chunk: break
                                requests.post(
                                    upload_url,
                                    data=chunk,
                                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
                                    params={"camera_id": c_id},
                                    timeout=1.5
                                )
                            except Exception:
                                break
                        print(f"[-] H.264 Reader closed for {c_id}")

                    threading.Thread(target=_stream_reader, args=(cam_id, proc, ffmpeg_nodes[cam_id]["url"]), daemon=True).start()
                except FileNotFoundError:
                    print(f"[ERR] FFmpeg binary '{ffmpeg_exe}' not found. Live stream will be disabled.")
                    time.sleep(10) # Wait longer before retrying to avoid spam
                    continue
                except Exception as e:
                    print(f"[ERR] Failed to spawn FFmpeg process: {e}")
                    time.sleep(5)
                    continue

            # 2. Pipe the frame to ffmpeg
            node = ffmpeg_nodes[cam_id]
            try:
                node["proc"].stdin.write(frame.tobytes())
                node["proc"].stdin.flush()
                node["last_active"] = time.time()
                
                # ── NEW: MJPEG Preview Upload (Fix for Black Screen) ──
                mjpeg_counter += 1
                if mjpeg_counter % mjpeg_interval == 0:
                    def _push_mjpeg(img_data, c_id):
                        try:
                            _, buf = cv2.imencode(".jpg", img_data, [cv2.IMWRITE_JPEG_QUALITY, 50])
                            requests.post(
                                f"{server}/api/upload-live",
                                files={"file": ("live.jpg", buf.tobytes(), "image/jpeg")},
                                data={"camera_id": c_id},
                                headers=headers,
                                timeout=1.0
                            )
                        except Exception:
                            pass
                    
                    # Offload to thread to prevent lagging the H.264 stream
                    threading.Thread(target=_push_mjpeg, args=(frame.copy(), cam_id), daemon=True).start()
            except Exception:
                print(f"[!] FFmpeg pipe failed for {cam_id}, resetting.")
                del ffmpeg_nodes[cam_id]

            # 3. Cleanup stale nodes (inactive > 10s)
            now = time.time()
            stale = [cid for cid, n in ffmpeg_nodes.items() if now - n["last_active"] > 10]
            for cid in stale:
                ffmpeg_nodes[cid]["proc"].terminate()
                del ffmpeg_nodes[cid]

        except Exception as e:
            print(f"[!] H.264 Streamer logic error: {e}")
            time.sleep(2)


def config_sync_worker(server, token, cam_configs):
    """Periodically fetches all assigned configs for this worker's nodes."""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{server}/api/roi/worker/rois"
    
    while True:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                configs = data.get("configs", {})
                for cam_id, config in configs.items():
                    if config != cam_configs.get(cam_id):
                        cam_configs[cam_id] = config
                        print(f"[*] CONFIG SYNC: {cam_id} settings updated")
            time.sleep(15) # Sync every 15 seconds
        except Exception as e:
            print(f"[WARN] Config Sync failure (will retry): {e}")
            time.sleep(10)


# ============================================================
# MAIN
# ============================================================
def main():
    args = parse_args()
    
    if args.cpu:
        import os
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        print("[*] Forced CPU Mode: Hiding GPU from all engines")
        
    print(f"[*] Sentrix-AI Worker v2.0 | Server: {args.server}")
    print(f"  Server  : {args.server}")
    print(f"  Cameras : {args.camera}")
    print(f"  Cam IDs : {args.camera_id}")
    print(f"  Face    : {'OFF' if args.no_face else 'ON'}")
    print(f"  Objects : {'OFF' if args.no_obj else 'ON'}")
    print("")

    num_cams = len(args.camera)


    token = login(args.server, args.user, args.password)
    print(f"[+] Authenticated as {args.user}")

    processes = []

    manager = mp.Manager()
    cam_configs = manager.dict() # Shared across processes

    face_queue   = mp.Queue(maxsize=8)  if not args.no_face else None
    obj_queue    = mp.Queue(maxsize=4)  if not args.no_obj  else None
    live_queue   = mp.Queue(maxsize=num_cams)
    upload_queue = mp.Queue(maxsize=40)
    annotation_queue = mp.Queue(maxsize=20) if not args.no_obj else None


    if not args.no_face:
        p = mp.Process(target=face_detector_worker,
                        args=(args.face_model, face_queue, upload_queue, args.server, token, cam_configs, args.cpu),
                       daemon=True)
        p.start(); processes.append(p)
        print("[+] Core 1 (Face) started")

    if not args.no_obj:
        target_objs = [o.lower() for o in args.objects]
        p = mp.Process(target=object_detector_worker,
                        args=(args.obj_model, obj_queue, annotation_queue, target_objs, cam_configs, args.cpu),
                       daemon=True)
        p.start(); processes.append(p)
        print("[+] Core 2 (Object) started")

        p_ann = mp.Process(target=_annotation_worker,
                           args=(annotation_queue, upload_queue),
                           daemon=True)
        p_ann.start(); processes.append(p_ann)
        print("[+] Annotator started")

    p = mp.Process(target=upload_worker,
                   args=(args.server, token, upload_queue, cam_configs),
                   daemon=True)
    p.start(); processes.append(p)
    print("[+] Uploader started")

    p_live = mp.Process(target=live_stream_worker,
                         args=(args.server, token, live_queue, cam_configs),
                         daemon=True)
    p_live.start(); processes.append(p_live)
    print("[+] Live Streamer started")

    p_sync = mp.Process(target=config_sync_worker,
                         args=(args.server, token, cam_configs),
                         daemon=True)
    p_sync.start(); processes.append(p_sync)
    print("[+] Config Syncer started")

    num_cams = len(args.camera)
    for i in range(num_cams):
        cam_src = args.camera[i]
        cam_id  = args.camera_id[i] if i < len(args.camera_id) else f"cam-{i+1}"
        loc     = args.location[i]  if i < len(args.location)  else "Global Perimeter"
        p = mp.Process(target=capture_worker,
                       args=(cam_src, cam_id, loc, args.interval, face_queue, obj_queue, live_queue, cam_configs),
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
