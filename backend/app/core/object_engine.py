import cv2
import numpy as np
import torch
from pathlib import Path
from .config import BASE_DIR

MODEL_PATH = BASE_DIR.parent / "yolov8s-worldv2.pt"

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

OBJECT_MODEL = None

def init_object_engine():
    global OBJECT_MODEL
    try:
        from ultralytics import YOLOWorld
        from ultralytics.nn.tasks import WorldModel
        
        # Override torch.load globally to avoid weights_only=True errors
        if not hasattr(torch, '_original_load'):
            torch._original_load = torch.load
            def _safe_load(*args, **kwargs):
                kwargs['weights_only'] = False
                return torch._original_load(*args, **kwargs)
            torch.load = _safe_load

        try:
            OBJECT_MODEL = YOLOWorld(str(MODEL_PATH))
            OBJECT_MODEL.to('cpu') 
        except Exception as e:
            print(f"Object Engine load failed: {e}")
            return
        
        OBJECT_MODEL.set_classes(DAILY_USAGE_CLASSES)
        print(f"Object Engine ready (vocabulary: {len(DAILY_USAGE_CLASSES)} classes)")
    except Exception as e:
        print(f"Object Engine init failed: {e}")

def detect_objects(image: np.ndarray, threshold: float = 0.4):
    if OBJECT_MODEL is None:
        return []

    try:
        results = OBJECT_MODEL.predict(image, conf=threshold, verbose=False)
        if not results or len(results) == 0:
            return []

        res = results[0]
        if res.boxes is None or len(res.boxes) == 0:
            return []

        boxes = res.boxes.xywh.cpu().numpy()
        confs = res.boxes.conf.cpu().numpy()
        cls_ids = res.boxes.cls.cpu().numpy().astype(int)
        names = res.names

        detections = []
        for i in range(len(boxes)):
            cx, cy, w, h = boxes[i]
            detections.append({
                "label":      names[cls_ids[i]],
                "confidence": round(float(confs[i]), 4),
                "bbox":       [int(cx - w / 2), int(cy - h / 2), int(w), int(h)]
            })
        return detections
    except Exception as e:
        print(f"Object detection error: {e}")
        return []