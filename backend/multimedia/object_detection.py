import math
from functools import lru_cache
from pathlib import Path

import torch
import numpy as np
from ultralytics import YOLO


@lru_cache(maxsize=1)
def get_detector():
    """Download the pretrained model if needed, then reuse it."""

    # Keep downloaded weights outside the Git repository.
    model_folder = Path.home() / ".cache" / "eyesight" / "models"
    model_folder.mkdir(parents=True, exist_ok=True)

    return YOLO(str(model_folder / "yolo26n.pt"))


def detect_objects(
    frame: np.ndarray,
    confidence_threshold: float = 0.35,
) -> list[dict]:
    """Detect objects and return normalized bounding boxes."""

    if not isinstance(frame, np.ndarray) or frame.size == 0:
        raise ValueError("Frame must be a non-empty NumPy array.")

    if frame.dtype != np.uint8:
        raise ValueError("Frame must contain 8-bit pixel values.")

    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("Frame must be a BGR image with 3 channels.")

    if (
        not math.isfinite(confidence_threshold)
        or not 0 <= confidence_threshold <= 1
    ):
        raise ValueError("Confidence threshold must be between 0 and 1.")

    result = get_detector().predict(
        source=frame,
        device="cpu",
        conf=confidence_threshold,
        imgsz=640,
        save=False,
        verbose=False,
    )[0]

    detections = []

    if result.boxes is None:
        return detections

    for box in result.boxes:
        class_id = int(box.cls.item())
        coordinates = box.xyxyn[0].cpu().tolist()

        x_min, y_min, x_max, y_max = [
            max(0.0, min(1.0, float(value)))
            for value in coordinates
        ]

        if x_min >= x_max or y_min >= y_max:
            continue

        detections.append({
            "detection_index": len(detections),
            "class_id": class_id,
            "label": result.names[class_id],
            "confidence": float(box.conf.item()),
            "x_min": x_min,
            "y_min": y_min,
            "x_max": x_max,
            "y_max": y_max,
        })

    return detections