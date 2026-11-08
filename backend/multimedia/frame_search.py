import argparse
from datetime import datetime, timezone
from importlib.metadata import version

import numpy as np

from multimedia.embedding_service import (
    MODEL_NAME,
    PRETRAINED,
    embed_text,
)

from sqlalchemy import select

from database.connection import SessionLocal
from database.models import AIModel, Frame, FrameEmbedding
from database.models import Session as CaptureSession


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def search_frames(session_id, query, top_k=3):
    if not isinstance(top_k, int) or not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20.")

    # Use the same CLIP configuration as the stored image vectors.
    query_vector = embed_text(query)

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

        rows = db.execute(
            select(Frame, FrameEmbedding, AIModel)
            .join(
                FrameEmbedding,
                FrameEmbedding.frame_id == Frame.frame_id,
            )
            .join(
                AIModel,
                AIModel.model_id == FrameEmbedding.model_id,
            )
            .join(
                CaptureSession,
                CaptureSession.session_id == Frame.session_id,
            )
            .where(
                Frame.session_id == session_id,
                Frame.expires_at > now,
                CaptureSession.history_expires_at > now,
                FrameEmbedding.embedding_kind == "image",
                FrameEmbedding.is_normalized.is_(True),
                AIModel.task == "embedding",
                AIModel.provider == "OpenCLIP",
                AIModel.model_name == MODEL_NAME,
                AIModel.model_revision == PRETRAINED,
            )
        ).all()

        matches = {}

        for frame, embedding, model in rows:
            if model.configuration != expected_configuration:
                continue

            if (
                embedding.dimensions != query_vector.size
                or len(embedding.vector_data) != query_vector.size * 4
            ):
                raise ValueError(
                    f"Invalid embedding size for frame {frame.frame_id}."
                )

            vector = np.frombuffer(
                embedding.vector_data,
                dtype="<f4",
            )

            length = float(np.linalg.norm(vector))

            if not np.isfinite(vector).all() or not np.isclose(
                length, 1.0, atol=1e-3
            ):
                raise ValueError(
                    f"Invalid normalized vector for frame {frame.frame_id}."
                )

            score = float(query_vector @ vector)

            matches[frame.frame_id] = {
                "frame_id": frame.frame_id,
                "image_storage_key": frame.image_storage_key,
                "captured_at": frame.captured_at.isoformat(),
                "similarity": score,
                "_expires_at": min(
                    frame.expires_at,
                    db.get(
                        CaptureSession, frame.session_id
                    ).history_expires_at,
                ),
            }

        # Exclude anything that expired while we were comparing.
        checked_at = utc_now()
        results = [
            item for item in matches.values()
            if item["_expires_at"] > checked_at
        ]

    results.sort(
        key=lambda item: (-item["similarity"], item["frame_id"])
    )

    for item in results:
        item.pop("_expires_at")

    return results[:top_k]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", type=int, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    results = search_frames(
        args.session, args.query, args.top_k
    )

    if not results:
        print("No compatible, unexpired image embeddings found.")
        return

    for rank, item in enumerate(results, start=1):
        print(
            f"{rank}. Frame {item['frame_id']} "
            f"| similarity={item['similarity']:.4f} "
            f"| {item['image_storage_key']}"
        )


if __name__ == "__main__":
    main()