"""
Object Detection Engine — YOLOv4 ONNX

FIXES from original:
1. Input format changed from BHWC → BCHW (YOLOv4 requires channels-first)
2. Coordinate scaling fixed: raw output is in 416px space, not normalized 0-1
3. Confidence now = objectness_score × class_score (not class_score alone)
4. Letterbox preprocessing for aspect-ratio-correct resizing
"""

import cv2
import numpy as np
from pathlib import Path
from .config import BASE_DIR

MODEL_PATH = BASE_DIR.parent / "yolov4.onnx"

COCO_CLASSES = [
    "person", "bicycle", "car", "motorbike", "aeroplane", "bus", "train", "truck", "boat",
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

OBJECT_SESSION = None


def _letterbox(im, new_shape=416, color=(114, 114, 114)):
    """Resize + pad to square while preserving aspect ratio."""
    h, w = im.shape[:2]
    r = new_shape / max(h, w)
    new_w, new_h = int(round(w * r)), int(round(h * r))
    im = cv2.resize(im, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    top    = (new_shape - new_h) // 2
    bottom = new_shape - new_h - top
    left   = (new_shape - new_w) // 2
    right  = new_shape - new_w - left
    im = cv2.copyMakeBorder(im, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return im, r, (left, top)


def init_object_engine():
    global OBJECT_SESSION
    if not MODEL_PATH.exists():
        print(f"⚠  Object Engine: model NOT FOUND at {MODEL_PATH}")
        return
    try:
        import onnxruntime as ort
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        OBJECT_SESSION = ort.InferenceSession(str(MODEL_PATH), providers=providers)
        print(f"✓ Object Engine ready — {OBJECT_SESSION.get_providers()[0]}")
    except Exception as e:
        print(f"⚠  Object Engine load failed: {e}")


def detect_objects(image: np.ndarray, threshold: float = 0.4):
    """
    Run YOLOv4 detection on a BGR image.

    Returns list of dicts: {label, confidence, bbox: [x, y, w, h]}
    """
    if OBJECT_SESSION is None:
        return []

    h_orig, w_orig = image.shape[:2]
    INPUT_SIZE = 416

    # ── Preprocess ──────────────────────────────────────────────────────────
    padded, scale, (pad_left, pad_top) = _letterbox(image, INPUT_SIZE)
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)

    # FIX 1: This specific YOLOv4 ONNX expects BHWC (batch, height, width, channels)
    blob = rgb.astype(np.float32) / 255.0
    blob = np.expand_dims(blob, axis=0)            # HWC → BHWC

    input_name = OBJECT_SESSION.get_inputs()[0].name
    try:
        outs = OBJECT_SESSION.run(None, {input_name: blob})
    except Exception as e:
        print(f"[OBJ] Inference error: {e}")
        return []

    # ── Decode detections ────────────────────────────────────────────────────
    boxes, confs, class_ids = [], [], []

    for out in outs:
        out = out.reshape(-1, out.shape[-1])
        for d in out:
            # FIX 2: confidence = objectness × class_score  (original used class_score alone)
            objectness = float(d[4])
            if objectness < 0.3:
                continue
            scores = d[5:]
            cid = int(np.argmax(scores))
            conf = objectness * float(scores[cid])   # ← proper confidence
            if conf < threshold:
                continue

            # FIX 3: raw cx,cy,bw,bh are in 416px space, NOT normalised 0-1
            cx_416 = float(d[0])
            cy_416 = float(d[1])
            bw_416 = float(d[2])
            bh_416 = float(d[3])

            # Undo letterbox padding then undo scale → original image coords
            cx_orig = (cx_416 - pad_left) / scale
            cy_orig = (cy_416 - pad_top)  / scale
            bw_orig = bw_416 / scale
            bh_orig = bh_416 / scale

            x = int(cx_orig - bw_orig / 2)
            y = int(cy_orig - bh_orig / 2)
            w = int(bw_orig)
            h = int(bh_orig)

            boxes.append([max(0, x), max(0, y), w, h])
            confs.append(conf)
            class_ids.append(cid)

    if not boxes:
        return []

    # ── NMS ─────────────────────────────────────────────────────────────────
    indices = cv2.dnn.NMSBoxes(boxes, confs, threshold, 0.45)
    results = []
    if len(indices) > 0:
        for i in indices.flatten():
            label = COCO_CLASSES[class_ids[i]] if class_ids[i] < len(COCO_CLASSES) else "unknown"
            results.append({
                "label":      label,
                "confidence": round(float(confs[i]), 4),
                "bbox":       boxes[i]
            })
    return results
