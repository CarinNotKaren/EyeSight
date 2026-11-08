import cv2
import numpy as np


def analyze_frame_quality(frame: np.ndarray) -> dict:
    """Measure sharpness and brightness of an OpenCV BGR frame."""

    if not isinstance(frame, np.ndarray) or frame.size == 0:
        raise ValueError("Frame must be a non-empty NumPy array.")

    if frame.dtype != np.uint8:
        raise ValueError("Frame must contain 8-bit pixel values.")

    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("Frame must be a BGR image with 3 channels.")

    height, width = frame.shape[:2]

    # Standardize large images before comparing their quality scores.
    scale = min(1.0, 640 / max(height, width))

    resized = cv2.resize(
        frame,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )

    # Convert the image to grayscale for quality calculations.
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

    # Strong edges usually produce a higher sharpness score.
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    # Mean pixel intensity: 0 is black and 255 is white.
    brightness = float(np.mean(gray))

    return {
        "width_px": width,
        "height_px": height,
        "sharpness_score": sharpness,
        "brightness_score": brightness,
    }
def evaluate_frame_quality(
    frame: np.ndarray,
    min_sharpness: float = 50.0,
    min_brightness: float = 25.0,
) -> dict:
    """Evaluate a frame using adjustable quality thresholds."""

    scores = analyze_frame_quality(frame)

    reasons = []

    if scores["sharpness_score"] < min_sharpness:
        reasons.append("possibly_blurry")

    if scores["brightness_score"] < min_brightness:
        reasons.append("too_dark")

    return {
        **scores,
        "passes_quality_check": len(reasons) == 0,
        "rejection_reasons": reasons,
    }