import cv2
import numpy as np
from typing import Optional

def extract_reid_embedding(image: np.ndarray) -> Optional[np.ndarray]:
    """
    Extracts a global appearance embedding (ReID) from a person image.
    Uses a spatial color histogram approach as a robust, lightweight baseline.
    """
    if image is None or image.size == 0:
        return None

    try:
        # Resize to a standard size for ReID (e.g., 256x128)
        img = cv2.resize(image, (128, 256))
        
        # Convert to HSV for better color robustness
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # Divide image into 4 horizontal strips to capture spatial structure (Head, Torso, Legs, Feet)
        h, w, _ = hsv.shape
        strips = 4
        strip_h = h // strips
        
        embeddings = []
        for i in range(strips):
            strip = hsv[i*strip_h : (i+1)*strip_h, :, :]
            
            # Calculate histogram for each channel
            # H: 16 bins, S: 8 bins, V: 8 bins
            hist_h = cv2.calcHist([strip], [0], None, [16], [0, 180])
            hist_s = cv2.calcHist([strip], [1], None, [8], [0, 256])
            hist_v = cv2.calcHist([strip], [2], None, [8], [0, 256])
            
            # Normalize and concatenate
            hist = np.concatenate([hist_h, hist_s, hist_v]).flatten()
            hist /= (np.sum(hist) + 1e-7)
            embeddings.append(hist)
            
        # Global embedding
        full_emb = np.concatenate(embeddings)
        
        # Normalize the final vector
        norm = np.linalg.norm(full_emb)
        if norm > 0:
            full_emb /= norm
            
        return full_emb.astype(np.float32)
        
    except Exception as e:
        print(f"ReID extraction error: {e}")
        return None

def compare_reid(emb1: np.ndarray, emb2: np.ndarray) -> float:
    """Calculates cosine similarity between two ReID embeddings."""
    if emb1 is None or emb2 is None:
        return 0.0
    return float(np.dot(emb1, emb2))
