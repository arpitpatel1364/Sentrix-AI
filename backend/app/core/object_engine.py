import os
import cv2
import numpy as np
import onnxruntime as ort
from pathlib import Path
from .config import BASE_DIR

# --- MODEL PATH ---
# BASE_DIR = backend/, yolov4.onnx is at project root (backend/../yolov4.onnx)
MODEL_PATH = BASE_DIR.parent / "yolov4.onnx"

COCO_CLASSES = [
    "person", "bicycle", "car", "motorbike", "aeroplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "sofa", "pottedplant", "bed",
    "diningtable", "toilet", "tvmonitor", "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave", "oven",
    "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"
]

# Global Engine
OBJECT_SESSION = None

def init_object_engine():
    global OBJECT_SESSION
    if not MODEL_PATH.exists():
        print(f"⚠  Object Engine model NOT FOUND at {MODEL_PATH}")
        return

    try:
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        OBJECT_SESSION = ort.InferenceSession(str(MODEL_PATH), providers=providers)
        print(f"✓ Object Engine loaded (yolov4.onnx, {OBJECT_SESSION.get_providers()[0]})")
    except Exception as e:
        print(f"⚠  Object Engine load failure: {e}")

def detect_objects(image: np.ndarray, threshold: float = 0.5):
    if OBJECT_SESSION is None:
        return []
    
    h_img, w_img = image.shape[:2]
    input_name = OBJECT_SESSION.get_inputs()[0].name
    
    # Preprocess (keep BHWC as the onnx model seems to expect it based on worker)
    resized = cv2.resize(image, (416, 416))
    image_data = resized.astype(np.float32) / 255.0
    image_data = np.expand_dims(image_data, axis=0) # HWC to BHWC
    
    try:
        outs = OBJECT_SESSION.run(None, {input_name: image_data})
    except Exception as e:
        # Fallback to NCHW if the engine unexpectedly requires it
        image_data = np.transpose(image_data[0], (2, 0, 1))
        image_data = np.expand_dims(image_data, axis=0)
        outs = OBJECT_SESSION.run(None, {input_name: image_data})
    
    results = []
    for out in outs:
        out = out.reshape(-1, out.shape[-1])
        for detection in out:
            scores = detection[5:]
            class_id = np.argmax(scores)
            confidence = scores[class_id]
            if confidence > threshold:
                center_x = int(detection[0] * w_img)
                center_y = int(detection[1] * h_img)
                w = int(detection[2] * w_img)
                h = int(detection[3] * h_img)
                x = int(center_x - w / 2)
                y = int(center_y - h / 2)
                
                label = COCO_CLASSES[class_id] if class_id < len(COCO_CLASSES) else "unknown"
                results.append({
                    "label": label,
                    "confidence": float(confidence),
                    "bbox": [max(0, x), max(0, y), w, h] # [x, y, w, h]
                })

    # Optional NMS could go here, but for simple analysis we can return raw detections or filtered ones.
    # To keep it consistent with the worker, we should use NMSBoxes.
    if not results:
        return []

    boxes = [[r['bbox'][0], r['bbox'][1], r['bbox'][2], r['bbox'][3]] for r in results]
    confs = [r['confidence'] for r in results]
    indices = cv2.dnn.NMSBoxes(boxes, confs, threshold, 0.4)
    
    final_results = []
    if len(indices) > 0:
        for i in indices.flatten():
            final_results.append(results[i])
            
    return final_results
