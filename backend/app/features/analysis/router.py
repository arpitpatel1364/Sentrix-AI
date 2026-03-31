from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from typing import List, Dict
import numpy as np
import cv2
from ...core.security import get_current_user
from ...core.face_engine import get_embedding, bytes_to_cv2, match_wanted, cv2_to_b64
from ...core.object_engine import detect_objects, init_object_engine

router = APIRouter(prefix="/api")

# Ensure engine is loaded (In a production app, this would be in lifespan)
init_object_engine()

@router.post("/analyze-snapshot")
async def analyze_snapshot(file: UploadFile = File(...), user=Depends(get_current_user)):
    data = await file.read()
    img = bytes_to_cv2(data)
    if img is None:
        raise HTTPException(status_code=400, detail="Invalid image format")

    # 1. Detect Objects
    objects = detect_objects(img)
    
    # 2. Detect Faces
    # The current face_engine.get_embedding only gets the LARGEST face.
    # For a forensic tool, we might want ALL faces, but for now we'll stick to the core logic.
    embedding = get_embedding(img)
    face_match = None
    if embedding is not None:
        face_match = match_wanted(embedding)

    # 3. Prepare Visuals (Draw boxes for the preview)
    preview_img = img.copy()
    for obj in objects:
        x, y, w, h = obj["bbox"]
        cv2.rectangle(preview_img, (x, y), (x + w, y + h), (0, 255, 255), 2)
        cv2.putText(preview_img, f"{obj['label']} {int(obj['confidence']*100)}%", (x, y - 10), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

    return {
        "status": "ok",
        "objects": objects,
        "face": face_match,
        "preview": cv2_to_b64(preview_img)
    }
