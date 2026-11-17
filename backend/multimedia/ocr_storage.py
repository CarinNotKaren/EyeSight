import argparse
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

# Import this before OpenCV to preserve the Torch-before-Paddle load order.
from multimedia.ocr_service import (
    DETECTION_MODEL,
    MAX_OCR_IMAGE_DIMENSION,
    MIN_CONFIDENCE,
    RECOGNITION_MODELS,
    extract_text,
    normalize_language,
)

import cv2
from sqlalchemy import delete, select

from database.connection import SessionLocal
from database.models import AIModel, Frame, OCRResult, Session


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def check_available(db, frame):
    if frame is None:
        raise ValueError("Frame does not exist.")

    session = db.get(Session, frame.session_id)

    if session is None:
        raise ValueError("Frame session does not exist.")

    now = utc_now()

    if frame.expires_at <= now or session.history_expires_at <= now:
        raise ValueError("Frame or session has expired.")

    return session


def process_frame_ocr(frame_id: int, *, language=None):
    storage = (
        Path(__file__).resolve().parents[1] / "storage"
    ).resolve()
    frames_root = (storage / "frames").resolve()

    # Close the read transaction before running the OCR model.
    with SessionLocal() as db:
        frame = db.get(Frame, frame_id)
        session = check_available(db, frame)

        storage_key = frame.image_storage_key
        expected_size = (frame.width_px, frame.height_px)

        # An explicit argument overrides the session language.
        uses_session_language = language is None
        selected_language = normalize_language(
            session.language_code
            if uses_session_language
            else language
        )

    image_path = (storage / storage_key).resolve()

    if (
        not image_path.is_relative_to(frames_root)
        or image_path == frames_root
    ):
        raise ValueError("Image must be inside storage/frames.")

    image = cv2.imread(str(image_path))

    if image is None:
        raise ValueError(f"Could not read image: {image_path}")

    if (image.shape[1], image.shape[0]) != expected_size:
        raise ValueError(
            "Image dimensions differ from its database record."
        )

    started = perf_counter()

    regions = extract_text(
        image,
        min_confidence=MIN_CONFIDENCE,
        language=selected_language,
    )

    latency_ms = round((perf_counter() - started) * 1000)
    recognition_model = RECOGNITION_MODELS[selected_language]

    configuration = {
        "detection_model": DETECTION_MODEL,
        "recognition_model": recognition_model,
        "recognition_language_setting": selected_language,
        "device": "cpu",
        "enable_mkldnn": False,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "min_confidence": MIN_CONFIDENCE,
        "require_alphanumeric": True,
        "max_ocr_image_dimension": MAX_OCR_IMAGE_DIMENSION,
        "resize_interpolation": "INTER_AREA",
        "polygon_coordinates": "original_image_pixels",
        "paddlepaddle_version": version("paddlepaddle"),
        "paddlex_version": version("paddlex"),
    }

    revision = f"paddleocr-{version('paddleocr')}"
    model_name = f"{DETECTION_MODEL}+{recognition_model}"

    with SessionLocal() as db:
        with db.begin():
            frame = db.scalar(
                select(Frame)
                .where(Frame.frame_id == frame_id)
                .with_for_update()
            )
            session = check_available(db, frame)

            if frame.image_storage_key != storage_key:
                raise ValueError(
                    "Image location changed during processing."
                )

            if (frame.width_px, frame.height_px) != expected_size:
                raise ValueError(
                    "Image dimensions changed during processing."
                )

            if uses_session_language:
                current_language = normalize_language(
                    session.language_code
                )

                if current_language != selected_language:
                    raise ValueError(
                        "Session language changed during processing."
                    )

            candidates = db.scalars(
                select(AIModel).where(
                    AIModel.task == "ocr",
                    AIModel.provider == "PaddleOCR",
                    AIModel.model_name == model_name,
                    AIModel.model_revision == revision,
                )
            ).all()

            model = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.configuration == configuration
                ),
                None,
            )

            if model is None:
                model = AIModel(
                    task="ocr",
                    provider="PaddleOCR",
                    model_name=model_name,
                    model_revision=revision,
                    configuration=configuration,
                )
                db.add(model)
                db.flush()

            # Replace results only for this exact model/configuration.
            db.execute(
                delete(OCRResult).where(
                    OCRResult.frame_id == frame_id,
                    OCRResult.model_id == model.model_id,
                )
            )

            for region in regions:
                db.add(
                    OCRResult(
                        frame_id=frame_id,
                        model_id=model.model_id,
                        region_index=region["region_index"],
                        recognized_text=region["recognized_text"],
                        confidence=region["confidence"],
                        polygon=region["polygon"],
                        # The selected reader does not identify the
                        # actual language of each individual region.
                        language_code=None,
                        reading_order=None,
                    )
                )

            details = dict(frame.processing_details or {})

            details["ocr"] = {
                "status": "completed",
                "model_id": model.model_id,
                "recognition_language_setting": selected_language,
                "region_count": len(regions),
                "min_confidence": MIN_CONFIDENCE,
                "latency_ms": latency_ms,
                "completed_at_utc": utc_now().isoformat(),
            }

            frame.processing_details = details

    return regions


def main():
    parser = argparse.ArgumentParser(
        description="Read and store OCR results for existing frames."
    )
    parser.add_argument("frame_ids", type=int, nargs="+")
    parser.add_argument(
        "--language",
        choices=sorted(RECOGNITION_MODELS),
        default=None,
        help="Override the session language: en, fr, or ar.",
    )
    arguments = parser.parse_args()

    for frame_id in arguments.frame_ids:
        results = process_frame_ocr(
            frame_id,
            language=arguments.language,
        )

        print(
            f"Frame {frame_id}: "
            f"saved {len(results)} accepted text regions",
            flush=True,
        )

        for region in results:
            print(
                "  Text:",
                region["recognized_text"],
                "| confidence:",
                round(region["confidence"], 3),
            )


if __name__ == "__main__":
    main()