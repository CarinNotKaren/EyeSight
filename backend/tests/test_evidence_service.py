from datetime import datetime, timezone
from types import SimpleNamespace

from assistant import evidence_service


def test_retrieve_question_evidence_forwards_question_and_time_filters(monkeypatch):
    captured = {}

    # Replace Member 2's heavy retrieval function with a focused test double.
    def fake_search_frames(**kwargs):
        captured.update(kwargs)
        return [
            {
                "frame_id": 41,
                "image_storage_key": "frames/session-7/frame-41.jpg",
                "captured_at": "2026-11-08T10:15:00",
                "similarity": 0.82,
            }
        ]

    monkeypatch.setattr(evidence_service, "search_frames", fake_search_frames)

    question = SimpleNamespace(
        session_id=7,
        question_text="What is in front of me?",
        search_from_at=datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc),
        search_to_at=datetime(2026, 11, 8, 10, 30, tzinfo=timezone.utc),
    )

    result = evidence_service.retrieve_question_evidence(question)

    # Verify the bridge forwards the session, text, and requested time range.
    assert captured["session_id"] == 7
    assert captured["query"] == "What is in front of me?"
    assert captured["top_k"] == evidence_service.DEFAULT_TOP_K
    assert captured["captured_from"] == question.search_from_at
    assert captured["captured_to"] == question.search_to_at

    # Verify the returned evidence is JSON-compatible and retains frame IDs.
    assert result["count"] == 1
    assert result["frames"][0]["frame_id"] == 41
    assert result["frames"][0]["image_storage_key"].endswith("frame-41.jpg")
    assert result["query"] == question.question_text
    assert result["retrieval_version"] == "member2-frame-retrieval-v1"


def test_retrieve_question_evidence_preserves_empty_results(monkeypatch):
    # An empty result is valid: the answering stage can produce a no-evidence response.
    monkeypatch.setattr(evidence_service, "search_frames", lambda **kwargs: [])

    question = SimpleNamespace(
        session_id=7,
        question_text="What is in front of me?",
        search_from_at=None,
        search_to_at=None,
    )

    result = evidence_service.retrieve_question_evidence(question)

    assert result["count"] == 0
    assert result["frames"] == []

def test_retrieve_question_evidence_uses_exact_current_frame(monkeypatch):
    captured = {}

    # Capture the retrieval arguments without loading Member 2's ML dependencies.
    def fake_search_frames(**kwargs):
        captured.update(kwargs)
        return [
            {
                "frame_id": 52,
                "image_storage_key": "frames/session-7/frame-52.jpg",
                "captured_at": "2026-11-09T10:15:00",
                "similarity": None,
            }
        ]

    monkeypatch.setattr(evidence_service, "search_frames", fake_search_frames)

    question = SimpleNamespace(
        session_id=7,
        question_text="What is in front of me?",
        search_from_at=None,
        search_to_at=None,
        retrieval_configuration={"requested_frame_id": 52},
    )

    result = evidence_service.retrieve_question_evidence(question)

    # The exact frame is requested without semantic embedding.
    assert captured["session_id"] == 7
    assert captured["frame_id"] == 52
    assert captured["query"] is None
    assert captured["top_k"] == 1

    assert result["selection_mode"] == "current_frame"
    assert result["count"] == 1
    assert result["frames"][0]["frame_id"] == 52


def test_retrieve_question_evidence_keeps_semantic_history_fallback(monkeypatch):
    captured = {}

    # Capture the normal past-frame search arguments.
    def fake_search_frames(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(evidence_service, "search_frames", fake_search_frames)

    question = SimpleNamespace(
        session_id=7,
        question_text="What is in front of me?",
        search_from_at=None,
        search_to_at=None,
        retrieval_configuration=None,
    )

    result = evidence_service.retrieve_question_evidence(question)

    assert "frame_id" not in captured
    assert captured["query"] == question.question_text
    assert captured["top_k"] == evidence_service.DEFAULT_TOP_K
    assert result["selection_mode"] == "semantic_history"
    assert result["count"] == 0