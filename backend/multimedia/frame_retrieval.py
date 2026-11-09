import argparse
from datetime import datetime, timezone
from importlib.metadata import version

import numpy as np
from sqlalchemy import select

from database.connection import SessionLocal
from database.models import (
    AIModel,
    Frame,
    FrameEmbedding,
    ObjectDetection,
    OCRResult,
)
from database.models import Session as CaptureSession


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_time(value):
    """Convert a datetime to the database's naive UTC convention."""
    if value is None:
        return None

    if not isinstance(value, datetime):
        raise ValueError("Time filters must be datetime values.")

    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    return value


def current_model_id(frame, stage_name):
    """Use only the latest successfully completed stage."""
    details = frame.processing_details or {}
    stage = details.get(stage_name) or {}

    if stage.get("status") != "completed":
        return None

    return stage.get("model_id")


def search_frames(
    session_id,
    query=None,
    top_k=3,
    *,
    frame_id=None,  # Retrieve one exact frame when supplied.
    object_label=None,
    ocr_text=None,
    captured_from=None,
    captured_to=None,
):
    if type(top_k) is not int or not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20.")

        # A specific frame ID must be a positive integer.
    if frame_id is not None and (
        type(frame_id) is not int or frame_id <= 0
    ):
        raise ValueError("frame_id must be a positive integer.")

    for name, value in (
        ("query", query),
        ("object_label", object_label),
        ("ocr_text", ocr_text),
    ):
        if value is not None and (
            not isinstance(value, str) or not value.strip()
        ):
            raise ValueError(f"{name} must be non-empty text.")

    captured_from = normalize_time(captured_from)
    captured_to = normalize_time(captured_to)

    if (
        captured_from is not None
        and captured_to is not None
        and captured_from > captured_to
    ):
        raise ValueError("Start time must not be after end time.")

    # Load CLIP only when semantic ranking is requested.
    query_vector = None
    expected_configuration = None

    if query is not None:
        from multimedia.embedding_service import (
            MODEL_NAME,
            PRETRAINED,
            embed_text,
        )

        query_vector = embed_text(query.strip())

        expected_configuration = {
            "open_clip_version": version("open_clip_torch"),
            "architecture": MODEL_NAME,
            "pretrained": PRETRAINED,
            "device": "cpu",
            "normalized": True,
            "dimensions": int(query_vector.size),
            "storage_dtype": "little_endian_float32",
        }

    with SessionLocal() as db:
        now = utc_now()

        statement = (
            select(Frame, CaptureSession.history_expires_at)
            .join(
                CaptureSession,
                CaptureSession.session_id == Frame.session_id,
            )
            .where(
                Frame.session_id == session_id,
                Frame.expires_at > now,
                CaptureSession.history_expires_at > now,
                Frame.processing_status.in_(("ready", "partial")),
            )
        )

                # Restrict the result to the requested frame when one is supplied.
        # The existing session and expiry conditions still apply.
        if frame_id is not None:
            statement = statement.where(Frame.frame_id == frame_id)

        if captured_from is not None:
            statement = statement.where(
                Frame.captured_at >= captured_from
            )

        if captured_to is not None:
            statement = statement.where(
                Frame.captured_at <= captured_to
            )

        rows = db.execute(statement).all()
        matches = []

        for frame, history_expires_at in rows:
            item = {
                "frame_id": frame.frame_id,
                "image_storage_key": frame.image_storage_key,
                "captured_at": frame.captured_at.isoformat(),
                "similarity": None,
                "_captured_at": frame.captured_at,
                "_expires_at": min(
                    frame.expires_at, history_expires_at
                ),
            }

            if object_label is not None:
                model_id = current_model_id(
                    frame, "object_detection"
                )
                if model_id is None:
                    continue

                labels = db.scalars(
                    select(ObjectDetection.label).where(
                        ObjectDetection.frame_id == frame.frame_id,
                        ObjectDetection.model_id == model_id,
                    )
                ).all()

                if not any(
                    label.casefold() == object_label.strip().casefold()
                    for label in labels
                ):
                    continue

                item["matched_object"] = object_label.strip()

            if ocr_text is not None:
                model_id = current_model_id(frame, "ocr")
                if model_id is None:
                    continue

                texts = db.scalars(
                    select(OCRResult.recognized_text).where(
                        OCRResult.frame_id == frame.frame_id,
                        OCRResult.model_id == model_id,
                    )
                ).all()

                matched_texts = [
                    text for text in texts
                    if ocr_text.strip().casefold() in text.casefold()
                ]

                if not matched_texts:
                    continue

                item["matched_texts"] = matched_texts

            if query_vector is not None:
                model_id = current_model_id(
                    frame, "image_embedding"
                )
                if model_id is None:
                    continue

                embedding_row = db.execute(
                    select(FrameEmbedding, AIModel)
                    .join(
                        AIModel,
                        AIModel.model_id == FrameEmbedding.model_id,
                    )
                    .where(
                        FrameEmbedding.frame_id == frame.frame_id,
                        FrameEmbedding.model_id == model_id,
                        FrameEmbedding.embedding_kind == "image",
                        FrameEmbedding.is_normalized.is_(True),
                        AIModel.task == "embedding",
                        AIModel.provider == "OpenCLIP",
                        AIModel.model_name == MODEL_NAME,
                        AIModel.model_revision == PRETRAINED,
                    )
                ).one_or_none()

                if embedding_row is None:
                    continue

                embedding, model = embedding_row

                if model.configuration != expected_configuration:
                    continue

                if (
                    embedding.dimensions != query_vector.size
                    or len(embedding.vector_data)
                    != query_vector.size * 4
                ):
                    raise ValueError(
                        f"Invalid embedding size: frame {frame.frame_id}"
                    )

                vector = np.frombuffer(
                    embedding.vector_data, dtype="<f4"
                )

                if (
                    not np.isfinite(vector).all()
                    or not np.isclose(
                        np.linalg.norm(vector), 1.0, atol=1e-3
                    )
                ):
                    raise ValueError(
                        f"Invalid embedding: frame {frame.frame_id}"
                    )

                item["similarity"] = float(query_vector @ vector)

            matches.append(item)

    # Recheck time after comparisons.
    checked_at = utc_now()
    matches = [
        item for item in matches
        if item["_expires_at"] > checked_at
    ]

    if query_vector is not None:
        matches.sort(
            key=lambda item: (
                -item["similarity"], item["frame_id"]
            )
        )
    else:
        # Without semantic ranking, return the most recent first.
        matches.sort(
            key=lambda item: (
                item["_captured_at"], item["frame_id"]
            ),
            reverse=True,
        )

    results = matches[:top_k]

    for item in results:
        item.pop("_expires_at")
        item.pop("_captured_at")

    return results


def parse_time(value):
    try:
        return normalize_time(
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Use an ISO timestamp, for example "
            "2026-11-07T18:00:00Z"
        ) from error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", type=int, required=True)
    parser.add_argument("--query")
    parser.add_argument("--object", dest="object_label")
    parser.add_argument("--ocr", dest="ocr_text")
    parser.add_argument("--from", dest="captured_from", type=parse_time)
    parser.add_argument("--to", dest="captured_to", type=parse_time)
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    try:
        results = search_frames(
            session_id=args.session,
            query=args.query,
            top_k=args.top_k,
            object_label=args.object_label,
            ocr_text=args.ocr_text,
            captured_from=args.captured_from,
            captured_to=args.captured_to,
        )
    except ValueError as error:
        parser.error(str(error))

    if not results:
        print("No matching available frames found.")
        return

    for rank, item in enumerate(results, start=1):
        score = (
            f"{item['similarity']:.4f}"
            if item["similarity"] is not None
            else "not used"
        )
        print(
            f"{rank}. Frame {item['frame_id']} "
            f"| similarity={score} "
            f"| captured_at_utc={item['captured_at']} "
            f"| {item['image_storage_key']}"
        )

        if "matched_texts" in item:
            print("   OCR:", item["matched_texts"])


if __name__ == "__main__":
    main()