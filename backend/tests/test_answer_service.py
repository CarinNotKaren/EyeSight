
"""Tests for VLM answer generation and answer-evidence persistence."""

from types import SimpleNamespace

import pytest

from assistant import answer_service
from database.models.answer import Answer
from database.models.answer_evidence import AnswerEvidence


class FakeQuery:
    """Small fake supporting the Answer lookup used by the service."""

    def filter(self, *conditions):
        # Accept SQLAlchemy filter expressions and keep the fake query chainable.
        return self

    def first(self):
        # Simulate a database lookup where no previous answer exists.
        return None


class FakeDB:
    """Track persisted ORM objects without connecting to MySQL."""

    def __init__(self):
        self.added = []
        self.commit_count = 0
        self.rollback_count = 0

    def query(self, model):
        return FakeQuery()

    def add(self, instance):
        self.added.append(instance)

        # Simulate the database assigning an answer ID.
        if isinstance(instance, Answer):
            instance.answer_id = 81

    def flush(self):
        # IDs are assigned by add() in this in-memory test double.
        return None

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def refresh(self, instance):
        return None


def make_question():
    """Create a question that has already completed visual retrieval."""
    return SimpleNamespace(
        question_id=31,
        session_id=7,
        question_text="What is in front of me?",
        language_code="en",
        status="answering",
        error_code=None,
        retrieval_configuration={
            "retrieval_latency_ms": 24,
            "frames": [],
        },
    )


def test_default_vlm_model_is_gemini():
    # Ensure the service uses the Gemini model selected for EyeSight.
    assert answer_service.DEFAULT_VLM_MODEL == "gemini-3.5-flash-lite"


def test_parse_vlm_response_reads_grounded_json():
    # A well-formed model response retains its grounded classification.
    result = answer_service.parse_vlm_response(
        '{"answer":"A chair is in front of you.",'
        '"answer_type":"grounded","uncertainty_reason":null}'
    )

    assert result["answer_text"] == "A chair is in front of you."
    assert result["answer_type"] == "grounded"
    assert result["uncertainty_reason"] is None


def test_parse_vlm_response_marks_unstructured_output_uncertain():
    # Plain text must never be treated as verified grounded output.
    result = answer_service.parse_vlm_response("There may be a chair nearby.")

    assert result["answer_type"] == "uncertain"
    assert result["answer_text"] == "There may be a chair nearby."
    assert result["uncertainty_reason"]


def test_parse_vlm_response_rejects_empty_output():
    # Empty model output cannot become a successful answer.
    with pytest.raises(answer_service.VLMGenerationError):
        answer_service.parse_vlm_response(" ")


def test_no_evidence_creates_safe_answer_without_calling_vlm(monkeypatch):
    db = FakeDB()
    question = make_question()

    # No valid frame images means the model must not be called.
    monkeypatch.setattr(answer_service, "load_question_images", lambda *args: [])
    monkeypatch.setattr(
        answer_service,
        "call_vision_model",
        lambda *args: pytest.fail("VLM must not run without image evidence"),
    )

    answer = answer_service.generate_and_persist_answer(db, question)

    assert answer.answer_type == "no_evidence"
    assert answer.model_id is None
    assert answer.answer_text
    assert question.status == "completed"
    assert answer.retrieval_latency_ms == 24
    assert db.commit_count == 1
    assert not any(isinstance(item, AnswerEvidence) for item in db.added)


def test_grounded_answer_persists_model_and_exact_frame_evidence(monkeypatch):
    # Simulate configured Gemini credentials without using a real API key.
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    db = FakeDB()
    question = make_question()

    images = [{
        "frame_id": 41,
        "retrieval_rank": 1,
        "image_storage_key": "frames/session-7/frame-41.jpg",
        "mime_type": "image/jpeg",
        "data_url": "data:image/jpeg;base64,ZmFrZQ==",
        "similarity": 0.87,
    }]

    # Simulate Member 2's retrieval result.
    monkeypatch.setattr(
        answer_service, "load_question_images", lambda *args: images
    )

    # Simulate a successful Gemini response without making a network request.
    monkeypatch.setattr(
        answer_service,
        "call_vision_model",
        lambda *args: (
            {
                "answer_text": "A chair is directly in front of you.",
                "answer_type": "grounded",
                "uncertainty_reason": None,
            },
            "gemini-3.5-flash-lite",
        ),
    )

    # Avoid a real AIModel database lookup in this unit test.
    monkeypatch.setattr(
        answer_service,
        "_get_or_create_model",
        lambda current_db, model_name: SimpleNamespace(model_id=9),
    )

    answer = answer_service.generate_and_persist_answer(db, question)

    evidence = next(
        item for item in db.added if isinstance(item, AnswerEvidence)
    )

    assert answer.answer_type == "grounded"
    assert answer.model_id == 9
    assert answer.answer_text.startswith("A chair")
    assert evidence.answer_id == 81
    assert evidence.frame_id == 41
    assert evidence.retrieval_rank == 1
    assert evidence.retrieval_method == "semantic"
    assert evidence.semantic_score == 0.87
    assert evidence.provided_to_model is True
    assert question.status == "completed"
    assert db.commit_count == 1


def test_provider_failure_persists_error_fallback(monkeypatch):
    # Configure Gemini credentials, but simulate an inference failure.
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    db = FakeDB()
    question = make_question()

    images = [{
        "frame_id": 41,
        "retrieval_rank": 1,
        "image_storage_key": "frames/session-7/frame-41.jpg",
        "mime_type": "image/jpeg",
        "data_url": "data:image/jpeg;base64,ZmFrZQ==",
        "similarity": 0.87,
    }]

    monkeypatch.setattr(
        answer_service, "load_question_images", lambda *args: images
    )

    def fail_model(*args):
        # Simulate a Gemini timeout without making a network request.
        raise answer_service.VLMGenerationError("provider timeout")

    monkeypatch.setattr(answer_service, "call_vision_model", fail_model)

    answer = answer_service.generate_and_persist_answer(db, question)

    evidence = next(
        item for item in db.added if isinstance(item, AnswerEvidence)
    )

    assert answer.answer_type == "error_fallback"
    assert answer.model_id is None
    assert "try again" in answer.answer_text.lower()
    assert answer.uncertainty_reason
    assert evidence.provided_to_model is False
    assert question.status == "completed"
    assert db.commit_count == 1
