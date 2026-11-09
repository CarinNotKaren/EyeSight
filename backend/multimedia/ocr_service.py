# Load PyTorch before PaddleOCR to avoid the Windows DLL conflict.
import torch

import math
from functools import lru_cache

import cv2
import numpy as np
from paddleocr import PaddleOCR


MIN_CONFIDENCE = 0.80
MAX_OCR_IMAGE_DIMENSION = 1280

DETECTION_MODEL = "PP-OCRv6_medium_det"

RECOGNITION_MODELS = {
    "en": "PP-OCRv6_medium_rec",
    "fr": "latin_PP-OCRv5_mobile_rec",
    "ar": "arabic_PP-OCRv5_mobile_rec",
}


def normalize_language(language):
    """Validate and normalize a supported language code."""
    if not isinstance(language, str):
        raise ValueError("OCR language must be en, fr, or ar.")

    # Accept regional codes such as fr-FR or ar-LB.
    language = language.strip().lower().replace("_", "-").split("-")[0]

    if language not in RECOGNITION_MODELS:
        raise ValueError("OCR language must be en, fr, or ar.")

    return language


@lru_cache(maxsize=3)
def get_reader(language="en"):
    """Load each requested language reader once per process."""
    language = normalize_language(language)

    return PaddleOCR(
        device="cpu",
        text_detection_model_name=DETECTION_MODEL,
        text_recognition_model_name=RECOGNITION_MODELS[language],
        enable_mkldnn=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def extract_text(
    frame: np.ndarray,
    min_confidence: float = MIN_CONFIDENCE,
    *,
    language: str = "en",
) -> list[dict]:
    """Read text using the selected language and original-image coordinates."""
    language = normalize_language(language)

    if not isinstance(frame, np.ndarray) or frame.size == 0:
        raise ValueError("Frame must be a non-empty NumPy array.")

    if frame.dtype != np.uint8:
        raise ValueError("Frame must contain 8-bit pixel values.")

    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("Frame must be a BGR image with 3 channels.")

    if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
        raise ValueError("Minimum confidence must be between 0 and 1.")

    original_height, original_width = frame.shape[:2]

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

    ocr_height, ocr_width = ocr_frame.shape[:2]
    scale_x = original_width / ocr_width
    scale_y = original_height / ocr_height

    results = get_reader(language).predict(input=ocr_frame)
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

            if not any(character.isalnum() for character in text):
                continue

            coordinates = np.asarray(polygon, dtype=np.float64)

            if (
                coordinates.ndim != 2
                or coordinates.shape[1] != 2
                or coordinates.shape[0] < 3
                or not np.isfinite(coordinates).all()
            ):
                raise ValueError("OCR returned an invalid text polygon.")

            original_polygon = [
                [
                    float(x) * scale_x,
                    float(y) * scale_y,
                ]
                for x, y in coordinates
            ]

            regions.append({
                "region_index": len(regions),
                "recognized_text": text,
                "confidence": confidence,
                "polygon": original_polygon,
            })

    return regions