"""Bridge the question API to Member 2's frame-retrieval module.

This service deliberately reuses the existing search_frames implementation.
It does not duplicate embedding, OCR, object-detection, or ranking logic.
"""

from datetime import datetime, timezone
from time import perf_counter


DEFAULT_TOP_K = 3


def search_frames(**kwargs):
    # Import the AI retrieval pipeline only when real retrieval is requested.
    # This keeps unit tests independent from NumPy and OpenCLIP installations.
    from multimedia.frame_retrieval import search_frames as retrieve_frames

    return retrieve_frames(**kwargs)


def retrieve_question_evidence(question):
    started = perf_counter()

    # Read the requested frame saved when the question was created.
    # Older question objects and tests may not have retrieval metadata yet.
    configuration = getattr(question, "retrieval_configuration", None) or {}
    requested_frame_id = configuration.get("requested_frame_id")

    if requested_frame_id is not None:
        # Current-frame questions use the exact frame without semantic search.
        results = search_frames(
            session_id=question.session_id,
            query=None,
            top_k=1,
            frame_id=requested_frame_id,
        )
        selection_mode = "current_frame"

    else:
        # Questions without a frame ID retain the existing past-frame search.
        results = search_frames(
            session_id=question.session_id,
            query=question.question_text,
            top_k=DEFAULT_TOP_K,
            captured_from=question.search_from_at,
            captured_to=question.search_to_at,
        )
        selection_mode = "semantic_history"

    return {
        "retrieval_version": "member2-frame-retrieval-v1",
        "selection_mode": selection_mode,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "retrieval_latency_ms": round((perf_counter() - started) * 1000),
        "query": question.question_text,
        "top_k": 1 if requested_frame_id is not None else DEFAULT_TOP_K,
        "count": len(results),
        "frames": results,
    }
