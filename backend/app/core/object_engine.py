"""
Object Detection Engine — YOLO World (Ultralytics)

Modernised to use YOLOv8s-Worldv2, providing:
1. Open-vocabulary detection capabilities.
2. Superior accuracy and speed over YOLOv4.
3. Simplified pipeline with Ultralytics framework.
"""
import cv2
import numpy as np
import torch
from pathlib import Path
from .config import BASE_DIR

# Using yolov8s-worldv2.pt as requested
MODEL_PATH = BASE_DIR.parent / "yolov8s-worldv2.pt"

# Trimmed: Core Important Daily Items (All others dumped)
DAILY_USAGE_CLASSES = [
    "phone", "water bottle", "laptop", "backpack", 
    "remote", "keyboard", "cell phone", "book", "bicycle", "car", "motorbike", "aeroplane", "bus", "train", "truck", "boat",
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

# Object detection model instance (singleton)
OBJECT_MODEL = None

def init_object_engine():
    """
    Initializes the YOLO World model, handles PyTorch 2.6+ security globals,
    and sets the offline vocabulary.
    """
    global OBJECT_MODEL
    try:
        from ultralytics import YOLOWorld
        from ultralytics.nn.tasks import WorldModel
        
        # --- PYTORCH 2.6+ SECURITY FIX ---
        # We must explicitly allowlist WorldModel because PyTorch 2.6+ 
        # defaults to weights_only=True for security.
        torch.serialization.add_safe_globals([WorldModel])
        # ---------------------------------

        try:
            print(f"[*] Backend: Loading Object Engine model on CPU...")
            # Initialize YOLOWorld; this call triggers the torch.load internally
            OBJECT_MODEL = YOLOWorld(str(MODEL_PATH))
            
            # Ensure model stays on CPU to save VRAM for other workers
            OBJECT_MODEL.to('cpu') 
        except Exception as e:
            print(f"⚠  Backend Object Engine OOM or Error: {e}")
            return
        
        # Set the custom vocabulary for the model
        OBJECT_MODEL.set_classes(DAILY_USAGE_CLASSES)
        
        print(f"✓ Object Engine ready (YOLO World v2) defaults: {DAILY_USAGE_CLASSES[:5]}...")
    except Exception as e:
        print(f"⚠  Object Engine load failed: {e}")


def detect_objects(image: np.ndarray, threshold: float = 0.4):
    """
    Run YOLO World detection on a BGR image.
    Returns list of dicts: {label, confidence, bbox: [x, y, w, h]}
    """
    if OBJECT_MODEL is None:
        return []

    try:
        # Standard predict call
        results = OBJECT_MODEL.predict(image, conf=threshold, verbose=False)
        
        if not results or len(results) == 0:
            return []

        res = results[0]
        # Check if boxes exist to avoid attribute errors on empty frames
        if res.boxes is None or len(res.boxes) == 0:
            return []

        boxes = res.boxes.xywh.cpu().numpy()  # [cx, cy, w, h]
        confs = res.boxes.conf.cpu().numpy()
        cls_ids = res.boxes.cls.cpu().numpy().astype(int)
        names = res.names

        detections = []
        for i in range(len(boxes)):
            cx, cy, w, h = boxes[i]
            label = names[cls_ids[i]]
            
            # Convert [cx, cy, w, h] (center-based) -> [x, y, w, h] (top-left)
            x = int(cx - w / 2)
            y = int(cy - h / 2)
            
            detections.append({
                "label":      label,
                "confidence": round(float(confs[i]), 4),
                "bbox":       [x, y, int(w), int(h)]
            })
            
        return detections
    except Exception as e:
        print(f"[OBJ] YOLO World error: {e}")
        return []