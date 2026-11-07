import math
from functools import lru_cache

# Load PyTorch before Paddle to avoid the Windows DLL conflict.
import torch
import numpy as np
from paddleocr import PaddleOCR


MIN_CONFIDENCE = 0.80


@lru_cache(maxsize=1)
def get_reader():
    """Load the OCR models once and reuse them."""
    return PaddleOCR(
        device="cpu",
        text_detection_model_name="PP-OCRv6_medium_det",
        text_recognition_model_name="PP-OCRv6_medium_rec",
        enable_mkldnn=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def extract_text(
    frame: np.ndarray,
    min_confidence: float = MIN_CONFIDENCE,
) -> list[dict]:
    """Return OCR readings that pass the configured filters."""

    if not isinstance(frame, np.ndarray) or frame.size == 0:
        raise ValueError("Frame must be a non-empty NumPy array.")

    if frame.dtype != np.uint8:
        raise ValueError("Frame must contain 8-bit pixel values.")

    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("Frame must be a BGR image with 3 channels.")

    if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
        raise ValueError("Minimum confidence must be between 0 and 1.")

    results = get_reader().predict(input=frame)
    regions = []

    for result in results:
        for text, score, polygon in zip(
            result["rec_texts"],
            result["rec_scores"],
            result["rec_polys"],
            strict=True,
        ):
            text = str(text).strip()
            confidence = float(score)

            if (
                not math.isfinite(confidence)
                or not 0 <= confidence <= 1
                or confidence < min_confidence
            ):
                continue

            # Reject empty or punctuation-only readings.
            if not any(character.isalnum() for character in text):
                continue

            regions.append({
                "region_index": len(regions),
                "recognized_text": text,
                "confidence": confidence,
                "polygon": [
                    [float(x), float(y)]
                    for x, y in polygon
                ],
            })

    return regions