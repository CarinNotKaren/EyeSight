from functools import lru_cache

# Load PyTorch before Paddle to avoid the observed Windows DLL conflict.
import torch
import numpy as np
from paddleocr import PaddleOCR


@lru_cache(maxsize=1)
def get_reader():
    """Load the OCR models once and reuse them."""
    return PaddleOCR(
        lang="en",
        device="cpu",
        text_detection_model_name="PP-OCRv6_medium_det",
        text_recognition_model_name="PP-OCRv6_medium_rec",
        enable_mkldnn=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def extract_text(frame: np.ndarray) -> list[dict]:
    """Read text with positions in the original image."""

    if not isinstance(frame, np.ndarray) or frame.size == 0:
        raise ValueError("Frame must be a non-empty NumPy array.")

    if frame.dtype != np.uint8:
        raise ValueError("Frame must contain 8-bit pixel values.")

    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("Frame must be a BGR image with 3 channels.")

    results = get_reader().predict(input=frame)
    regions = []

    for result in results:
        for text, score, polygon in zip(
            result["rec_texts"],
            result["rec_scores"],
            result["rec_polys"],
            strict=True,
        ):
            regions.append({
                "region_index": len(regions),
                "recognized_text": text,
                "confidence": float(score),
                "polygon": [
                    [float(x), float(y)]
                    for x, y in polygon
                ],
            })

    return regions