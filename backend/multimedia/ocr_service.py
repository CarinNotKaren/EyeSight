# Load PyTorch before PaddleOCR to avoid the Windows DLL conflict.
import torch

import math
from functools import lru_cache

import cv2
import numpy as np
from paddleocr import PaddleOCR


MIN_CONFIDENCE = 0.80

# Limit the largest image dimension to reduce OCR inference memory usage.
MAX_OCR_IMAGE_DIMENSION = 1280


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
    """Return filtered OCR readings with coordinates mapped to the original frame."""

    # Validate the original image before preprocessing.
    if not isinstance(frame, np.ndarray) or frame.size == 0:
        raise ValueError("Frame must be a non-empty NumPy array.")

    if frame.dtype != np.uint8:
        raise ValueError("Frame must contain 8-bit pixel values.")

    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("Frame must be a BGR image with 3 channels.")

    if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
        raise ValueError("Minimum confidence must be between 0 and 1.")

    # Remember the original dimensions so detected coordinates can be restored.
    original_height, original_width = frame.shape[:2]

    # Resize only when the image exceeds the configured maximum dimension.
    scale = min(
        1.0,
        MAX_OCR_IMAGE_DIMENSION / max(original_width, original_height),
    )

    if scale < 1.0:
        resized_width = max(1, round(original_width * scale))
        resized_height = max(1, round(original_height * scale))

        ocr_frame = cv2.resize(
            frame,
            (resized_width, resized_height),
            interpolation=cv2.INTER_AREA,
        )
    else:
        ocr_frame = frame

    # Calculate separate scale factors to account for resizing-rounding differences.
    ocr_height, ocr_width = ocr_frame.shape[:2]
    scale_x = original_width / ocr_width
    scale_y = original_height / ocr_height

    # Run OCR on the resized image instead of the full-resolution original.
    results = get_reader().predict(input=ocr_frame)
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

            # Reject invalid or low-confidence recognition results.
            if (
                not math.isfinite(confidence)
                or not 0 <= confidence <= 1
                or confidence < min_confidence
            ):
                continue

            # Reject empty or punctuation-only readings.
            if not any(character.isalnum() for character in text):
                continue

            # Convert polygon coordinates back to the original image dimensions.
            original_polygon = [
                [
                    float(x) * scale_x,
                    float(y) * scale_y,
                ]
                for x, y in polygon
            ]

            regions.append({
                "region_index": len(regions),
                "recognized_text": text,
                "confidence": confidence,
                "polygon": original_polygon,
            })

    return regions