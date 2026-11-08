import argparse
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np

from multimedia.embedding_service import (
    MODEL_NAME,
    PRETRAINED,
    embed_image,
)

import cv2
from sqlalchemy import select

from database.connection import SessionLocal
from database.models import AIModel, Frame, FrameEmbedding
from database.models import Session as CaptureSession


STORAGE_ROOT = Path(__file__).resolve().parents[1] / "storage"


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def check_available(db, frame):
    if frame is None:
        raise ValueError("Frame does not exist.")

    session = db.get(CaptureSession, frame.session_id)
    now = utc_now()

    if (
        session is None
        or frame.expires_at <= now
        or session.history_expires_at <= now
    ):
        raise ValueError(f"Frame {frame.frame_id} has expired.")


def process_frame_embedding(frame_id):
    with SessionLocal() as db:
        frame = db.get(Frame, frame_id)
        check_available(db, frame)

        storage_key = frame.image_storage_key
        expected_size = (frame.width_px, frame.height_px)

    image_path = (STORAGE_ROOT / storage_key).resolve()
    frames_root = (STORAGE_ROOT / "frames").resolve()

    if not image_path.is_relative_to(frames_root):
        raise ValueError("Image must be inside storage/frames.")

    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Cannot read image: {image_path}")

    if (image.shape[1], image.shape[0]) != expected_size:
        raise ValueError("Image dimensions differ from database metadata.")

    vector = embed_image(image)

    if vector.shape != (512,) or not np.isfinite(vector).all():
        raise ValueError("Expected a finite 512-dimensional vector.")

    # Explicit float32 format: four bytes per number.
    vector_bytes = vector.astype("<f4").tobytes()

    configuration = {
        "open_clip_version": version("open_clip_torch"),
        "architecture": MODEL_NAME,
        "pretrained": PRETRAINED,
        "device": "cpu",
        "normalized": True,
        "dimensions": int(vector.size),
        "storage_dtype": "little_endian_float32",
    }

    with SessionLocal() as db:
        with db.begin():
            frame = db.scalar(
                select(Frame)
                .where(Frame.frame_id == frame_id)
                .with_for_update()
            )
            check_available(db, frame)

            if frame.image_storage_key != storage_key:
                raise ValueError("Frame image path changed during processing.")

            candidates = db.scalars(
                select(AIModel).where(
                    AIModel.task == "embedding",
                    AIModel.provider == "OpenCLIP",
                    AIModel.model_name == MODEL_NAME,
                    AIModel.model_revision == PRETRAINED,
                )
            ).all()

            model = next(
                (
                    item for item in candidates
                    if item.configuration == configuration
                ),
                None,
            )

            if model is None:
                model = AIModel(
                    task="embedding",
                    provider="OpenCLIP",
                    model_name=MODEL_NAME,
                    model_revision=PRETRAINED,
                    configuration=configuration,
                )
                db.add(model)
                db.flush()

            embedding = db.scalar(
                select(FrameEmbedding).where(
                    FrameEmbedding.frame_id == frame_id,
                    FrameEmbedding.model_id == model.model_id,
                    FrameEmbedding.embedding_kind == "image",
                )
            )

            if embedding is None:
                embedding = FrameEmbedding(
                    frame_id=frame_id,
                    model_id=model.model_id,
                    embedding_kind="image",
                )
                db.add(embedding)

            embedding.dimensions = int(vector.size)
            embedding.vector_data = vector_bytes
            embedding.is_normalized = True
            embedding.source_text = None

            details = dict(frame.processing_details or {})
            details["image_embedding"] = {
                "status": "completed",
                "model_id": model.model_id,
                "dimensions": int(vector.size),
                "completed_at_utc": utc_now().isoformat(),
            }
            frame.processing_details = details

    return int(vector.size)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", type=int, required=True)
    args = parser.parse_args()

    with SessionLocal() as db:
        frame_ids = db.scalars(
            select(Frame.frame_id)
            .where(Frame.session_id == args.session)
            .order_by(Frame.sequence_number)
        ).all()

    if not frame_ids:
        raise ValueError("No frames found for this session.")

    for frame_id in frame_ids:
        dimensions = process_frame_embedding(frame_id)
        print(f"Frame {frame_id}: saved image vector ({dimensions} dimensions)")


if __name__ == "__main__":
    main()