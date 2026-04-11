import os
import uuid
import json
import sqlite3
import numpy as np
import cv2
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime

from .config import MODELS_DIR, DATA_DIR, SIMILARITY_THRESHOLD, DB_PATH, DEVICE

# --- InsightFace & Qdrant Availability ---
try:
    import insightface
    from insightface.app import FaceAnalysis
    FACE_MODEL_AVAILABLE = True
except ImportError:
    FACE_MODEL_AVAILABLE = False
    print("[!] insightface not installed. Face recognition disabled.")


try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    print("[!] qdrant-client not installed. Using in-memory store.")


# Global state
FACE_APP = None
QDRANT_CLIENT = None

def _test_cuda_functional():
    """Try to create a tiny ONNX session to see if CUDA DLLs are actually working."""
    try:
        import onnxruntime as ort
        import numpy as np
        # Minimalist 1x1 model
        from onnx import helper, TensorProto
        node = helper.make_node("Relu", ["X"], ["Y"])
        graph = helper.make_graph([node], "test", [helper.make_tensor_value_info("X", TensorProto.FLOAT, [1, 1])], [helper.make_tensor_value_info("Y", TensorProto.FLOAT, [1, 1])])
        model = helper.make_model(graph)
        sess = ort.InferenceSession(model.SerializeToString(), providers=["CUDAExecutionProvider"])
        return "CUDAExecutionProvider" in sess.get_providers()
    except Exception:
        return False

def init_face_engines():
    global FACE_APP, QDRANT_CLIENT

    # 1. Load Face Model (InsightFace)
    if FACE_MODEL_AVAILABLE:
        try:
            providers = ["CPUExecutionProvider"]
            
            # Only attempt CUDA if config allows it AND hardware supports it
            if DEVICE.lower() == "cuda":
                try:
                    import onnxruntime as ort
                    if "CUDAExecutionProvider" in ort.get_available_providers():
                        # Pre-flight check to avoid noisy "Error 126" LoadLibrary failures
                        if _test_cuda_functional():
                            providers = ["CUDAExecutionProvider"]
                            print("[*] GPU Detected: Using CUDAExecutionProvider for face recognition")
                        else:
                            print("[i] CUDA found but libraries (DLLs) missing/invalid. Falling back to CPU.")
                    else:
                        print("[i] Using CPU for face recognition (CUDA provider not available)")
                except Exception as e:
                    print(f"[i] Provider check failed: {e}. Using CPU.")
            else:
                print("[i] Running Face Recognition on CPU (configured)")


            FACE_APP = FaceAnalysis(
                name="buffalo_s",
                root=str(MODELS_DIR / "insightface"),
                providers=providers
            )
            FACE_APP.prepare(ctx_id=0, det_size=(160, 160))
            
            # Get actual providers used by the underlying ONNX sessions
            actual_providers = []
            for model in FACE_APP.models.values():
                if hasattr(model, 'session'):
                    actual_providers.extend(model.session.get_providers())
            
            p_report = list(set(actual_providers)) if actual_providers else providers
            print(f"InsightFace model loaded (buffalo_s, providers: {p_report})")
        except Exception as e:
            print(f"Could not load InsightFace: {e}")

    # 2. Init Qdrant
    if QDRANT_AVAILABLE:
        try:
            target_path = str(DATA_DIR / "qdrant_storage")
            QDRANT_CLIENT = QdrantClient(path=target_path)
            
            cols = QDRANT_CLIENT.get_collections().collections
            col_names = [c.name for c in cols]
            
            if "sightings" not in col_names:
                QDRANT_CLIENT.create_collection("sightings", vectors_config=VectorParams(size=512, distance=Distance.COSINE))
            
            if "watchlist" not in col_names:
                QDRANT_CLIENT.create_collection("watchlist", vectors_config=VectorParams(size=512, distance=Distance.COSINE))
            
            # Migration logic here if needed, but for simplicity we assume the core logic is what's important
            # In a full refactor, we would run the migration task from lifespan.
            
            print(f"[v] Qdrant persistent storage started at {target_path}")
        except Exception as e:
            print(f"[!] Qdrant error: {e}")


def get_embedding(img_array: np.ndarray) -> Optional[np.ndarray]:
    if FACE_APP is None:
        return None
    faces = FACE_APP.get(img_array)
    if not faces:
        return None
    largest = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1]))
    emb = largest.embedding
    return emb / np.linalg.norm(emb)

def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))

def match_wanted(embedding: np.ndarray) -> Optional[dict]:
    # 1. Qdrant (Fast Vector Search)
    if QDRANT_AVAILABLE and QDRANT_CLIENT:
        try:
            hits = QDRANT_CLIENT.search("watchlist", query_vector=embedding.tolist(), limit=1)
            if hits and hits[0].score >= SIMILARITY_THRESHOLD:
                return {"person": {"id": hits[0].payload["person_id"], "name": hits[0].payload["person_name"]}, "confidence": round(hits[0].score * 100, 1)}
        except Exception as e:
            print(f"Qdrant search error: {e}")
            
    # 2. SQLite Fallback
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id, p.person_id, p.embedding, w.name 
            FROM person_photos p JOIN wanted w ON p.person_id = w.id
        """)
        rows = cur.fetchall()
        
    best_score, best_person = 0.0, None
    for r in rows:
        score = cosine_sim(embedding, np.frombuffer(r["embedding"], dtype=np.float32))
        if score > best_score:
            best_score, best_person = score, {"id": r["person_id"], "name": r["name"]}
                
    if best_score >= SIMILARITY_THRESHOLD and best_person:
        return {"person": best_person, "confidence": round(best_score * 100, 1)}
    return None

def bytes_to_cv2(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)

def cv2_to_b64(img: np.ndarray) -> str:
    import base64
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode()
