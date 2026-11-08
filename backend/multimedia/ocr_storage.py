import argparse
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

from multimedia.ocr_service import MIN_CONFIDENCE, extract_text

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


def process_frame_ocr(frame_id: int):
    storage = (
        Path(__file__).resolve().parents[1] / "storage"
    ).resolve()
    frames_root = (storage / "frames").resolve()

    # Close the read transaction before running the OCR model.
    with SessionLocal() as db:
        frame = db.get(Frame, frame_id)
        check_available(db, frame)

        storage_key = frame.image_storage_key
        expected_size = (frame.width_px, frame.height_px)

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
    )
    latency_ms = round((perf_counter() - started) * 1000)

    configuration = {
        "detection_model": "PP-OCRv6_medium_det",
        "recognition_model": "PP-OCRv6_medium_rec",
        "device": "cpu",
        "enable_mkldnn": False,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "min_confidence": MIN_CONFIDENCE,
        "require_alphanumeric": True,
        "paddlepaddle_version": version("paddlepaddle"),
        "paddlex_version": version("paddlex"),
    }

    revision = f"paddleocr-{version('paddleocr')}"

    with SessionLocal() as db:
        with db.begin():
            frame = db.scalar(
                select(Frame)
                .where(Frame.frame_id == frame_id)
                .with_for_update()
            )
            check_available(db, frame)

            if frame.image_storage_key != storage_key:
                raise ValueError(
                    "Image location changed during processing."
                )

            candidates = db.scalars(
                select(AIModel).where(
                    AIModel.task == "ocr",
                    AIModel.provider == "PaddleOCR",
                    AIModel.model_name
                    == "PP-OCRv6_medium_det+medium_rec",
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
                    model_name="PP-OCRv6_medium_det+medium_rec",
                    model_revision=revision,
                    configuration=configuration,
                )
                db.add(model)
                db.flush()

            # Replace previous results for this exact configuration.
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
                        language_code=None,
                        reading_order=None,
                    )
                )

            details = dict(frame.processing_details or {})
            details["ocr"] = {
                "status": "completed",
                "model_id": model.model_id,
                "region_count": len(regions),
                "min_confidence": MIN_CONFIDENCE,
                "latency_ms": latency_ms,
                "completed_at_utc": utc_now().isoformat(),
            }
            frame.processing_details = details

    return regions


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("frame_ids", type=int, nargs="+")
    arguments = parser.parse_args()

    for frame_id in arguments.frame_ids:
        results = process_frame_ocr(frame_id)

        print(
            f"Frame {frame_id}: "
            f"saved {len(results)} accepted text regions"
        )

        for region in results:
            print(
                "  Text:",
                region["recognized_text"],
                "| confidence:",
                round(region["confidence"], 3),
            )