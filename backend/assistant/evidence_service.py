"""Bridge the question API to Member 2's frame-retrieval module.

This service deliberately reuses the existing search_frames implementation.
It does not duplicate embedding, OCR, object-detection, or ranking logic.
"""

from datetime import datetime, timezone


DEFAULT_TOP_K = 3


def search_frames(**kwargs):
    # Import the AI retrieval pipeline only when real retrieval is requested.
    # This keeps unit tests independent from NumPy and OpenCLIP installations.
    from multimedia.frame_retrieval import search_frames as retrieve_frames

    return retrieve_frames(**kwargs)


def retrieve_question_evidence(question):
    """Retrieve and serialize visual evidence for one persisted question."""

    # Member 2's function accepts naive UTC datetimes, matching our DB models.
    results = search_frames(
        session_id=question.session_id,
        query=question.question_text,
        top_k=DEFAULT_TOP_K,
        captured_from=question.search_from_at,
        captured_to=question.search_to_at,
    )

    # SQLAlchemy's MySQL JSON column needs ordinary JSON-compatible values.
    # Keep frame IDs and storage keys for the later image-loading/answering stage.
    return {
        "retrieval_version": "member2-frame-retrieval-v1",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "query": question.question_text,
        "top_k": DEFAULT_TOP_K,
        "count": len(results),
        "frames": results,
    }
