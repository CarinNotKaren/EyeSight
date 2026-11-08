"""Unit tests for the Question API route handlers.

These tests use a lightweight fake SQLAlchemy session so they do not require
a running MySQL server or Member 2's NumPy/OpenCLIP retrieval dependencies.
"""

from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from assistant import question_service
from database.models.answer import Answer
from database.models.question import Question
from database.models.session import Session as DBSession
from routers import questions as question_router
from schemas.question import QuestionCreate


class FakeQuery:
    """Provide the small part of SQLAlchemy's Query API used by the router."""

    def __init__(self, first_result=None, all_result=None):
        self.first_result = first_result
        self.all_result = all_result or []

    def filter(self, *conditions):
        # Ignore SQL expressions; each test supplies the expected query result.
        return self

    def order_by(self, *ordering):
        return self

    def offset(self, value):
        return self

    def limit(self, value):
        return self

    def first(self):
        return self.first_result

    def all(self):
        return self.all_result


class FakeDB:
    """Track database operations without opening a real database connection."""

    def __init__(self, results=None):
        self.results = results or {}
        self.added = []
        self.commit_count = 0
        self.rollback_count = 0

    def query(self, model):
        # Return the result configured for the model under test.
        configured = self.results.get(model, {})
        return FakeQuery(
            first_result=configured.get("first"),
            all_result=configured.get("all"),
        )

    def add(self, instance):
        self.added.append(instance)

    def commit(self):
        self.commit_count += 1

    def refresh(self, instance):
        # The fake database does not modify objects after commit.
        return None

    def rollback(self):
        self.rollback_count += 1


def make_question_create():
    """Build a valid voice-question request with a stable client request ID."""
    return QuestionCreate(
        session_id=7,
        client_request_id=UUID("11111111-1111-4111-8111-111111111111"),
        input_type="voice",
        question_text=None,
        language_code="en",
    )


def test_create_question_saves_question_for_active_session():
    # The session is active and no question with this request ID exists.
    active_session = SimpleNamespace(session_id=7, status="active")
    db = FakeDB({
        DBSession: {"first": active_session},
        Question: {"first": None},
    })

    result = question_router.create_question(make_question_create(), db)

    # Verify the route created and persisted the expected question.
    assert len(db.added) == 1
    assert result is db.added[0]
    assert result.session_id == 7
    assert result.client_request_id == "11111111-1111-4111-8111-111111111111"
    assert result.input_type == "voice"
    assert db.commit_count == 1


def test_create_question_rejects_inactive_session():
    # Ended sessions must not accept new questions.
    ended_session = SimpleNamespace(session_id=7, status="ended")
    db = FakeDB({DBSession: {"first": ended_session}})

    with pytest.raises(HTTPException) as error:
        question_router.create_question(make_question_create(), db)

    assert error.value.status_code == 409
    assert db.added == []


def test_create_question_returns_existing_request_without_duplicate():
    # Retrying the same client request must return the existing record.
    active_session = SimpleNamespace(session_id=7, status="active")
    existing_question = SimpleNamespace(question_id=31)
    db = FakeDB({
        DBSession: {"first": active_session},
        Question: {"first": existing_question},
    })

    result = question_router.create_question(make_question_create(), db)

    assert result is existing_question
    assert db.added == []
    assert db.commit_count == 0


def test_get_question_returns_existing_question():
    # Return the question found by its primary key.
    existing_question = SimpleNamespace(question_id=31)
    db = FakeDB({Question: {"first": existing_question}})

    result = question_router.get_question(31, db)

    assert result is existing_question


def test_get_question_returns_404_when_missing():
    # A missing question ID must produce an HTTP 404 response.
    db = FakeDB({Question: {"first": None}})

    with pytest.raises(HTTPException) as error:
        question_router.get_question(999, db)

    assert error.value.status_code == 404


def test_get_question_answer_returns_saved_answer():
    # The route first checks the question, then retrieves its answer.
    existing_question = SimpleNamespace(question_id=31)
    saved_answer = SimpleNamespace(answer_id=12, question_id=31)
    db = FakeDB({
        Question: {"first": existing_question},
        Answer: {"first": saved_answer},
    })

    result = question_router.get_question_answer(31, db)

    assert result is saved_answer


def test_get_question_answer_returns_404_when_answer_is_missing():
    # An existing question may not have an answer while processing.
    existing_question = SimpleNamespace(question_id=31)
    db = FakeDB({
        Question: {"first": existing_question},
        Answer: {"first": None},
    })

    with pytest.raises(HTTPException) as error:
        question_router.get_question_answer(31, db)

    assert error.value.status_code == 404
    assert error.value.detail == "Answer not available yet"


def test_change_question_status_allows_valid_transition():
    # Use the real status service to verify the transcribing -> retrieving step.
    question = SimpleNamespace(
        question_id=31,
        status="transcribing",
        error_code=None,
    )
    db = FakeDB({Question: {"first": question}})

    result = question_router.change_question_status(31, "retrieving", db)

    assert result.status == "retrieving"
    assert result.error_code is None
    assert db.commit_count == 1


def test_change_question_status_rejects_invalid_transition():
    # A question cannot jump directly from received to completed.
    question = SimpleNamespace(
        question_id=31,
        status="received",
        error_code=None,
    )
    db = FakeDB({Question: {"first": question}})

    with pytest.raises(HTTPException) as error:
        question_router.change_question_status(31, "completed", db)

    assert error.value.status_code == 400
    assert db.commit_count == 0


def test_get_question_history_returns_paginated_session_questions():
    # Return the session's questions in the order supplied by the query.
    session = SimpleNamespace(session_id=7)
    history = [
        SimpleNamespace(question_id=33),
        SimpleNamespace(question_id=32),
    ]
    db = FakeDB({
        DBSession: {"first": session},
        Question: {"all": history},
    })

    result = question_router.get_question_history(
        session_id=7,
        db=db,
        limit=2,
        offset=1,
    )

    assert result == history


def test_get_question_history_returns_404_for_missing_session():
    # History cannot be retrieved for a session that does not exist.
    db = FakeDB({DBSession: {"first": None}})

    with pytest.raises(HTTPException) as error:
        question_router.get_question_history(999, db)

    assert error.value.status_code == 404


def test_transcription_saves_text_and_starts_retrieval(monkeypatch):
    # Start with a question waiting for Member 1's Whisper transcription.
    question = SimpleNamespace(
        question_id=31,
        session_id=7,
        question_text=None,
        language_code=None,
        search_from_at=None,
        search_to_at=None,
        status="transcribing",
        retrieval_configuration=None,
        error_code=None,
    )
    db = FakeDB({Question: {"first": question}})
    retrieved_evidence = {
        "retrieval_version": "member2-frame-retrieval-v1",
        "count": 1,
        "frames": [{"frame_id": 41, "image_storage_key": "frame-41.jpg"}],
    }

    # Mock the expensive retrieval step while exercising the route workflow.
    monkeypatch.setattr(
        question_router,
        "retrieve_question_evidence",
        lambda current_question: retrieved_evidence,
    )

    transcription = SimpleNamespace(
        question_text="  What is in front of me?  ",
        language_code="en",
    )
    result = question_router.update_question_transcription(31, transcription, db)

    # Verify the transcription and retrieved evidence were persisted.
    assert result.question_text == "What is in front of me?"
    assert result.language_code == "en"
    assert result.retrieval_configuration == retrieved_evidence
    assert result.status == "answering"
    assert result.error_code is None
    assert db.commit_count == 2


def test_transcription_marks_question_failed_when_retrieval_fails(monkeypatch):
    # A retrieval exception should move the persisted question to failed.
    question = SimpleNamespace(
        question_id=31,
        session_id=7,
        question_text=None,
        language_code=None,
        search_from_at=None,
        search_to_at=None,
        status="transcribing",
        retrieval_configuration=None,
        error_code=None,
    )
    db = FakeDB({Question: {"first": question}})

    def fail_retrieval(current_question):
        # Simulate Member 2's retrieval pipeline failing.
        raise RuntimeError("retrieval unavailable")

    monkeypatch.setattr(
        question_router,
        "retrieve_question_evidence",
        fail_retrieval,
    )

    transcription = SimpleNamespace(
        question_text="What is in front of me?",
        language_code="en",
    )

    with pytest.raises(HTTPException) as error:
        question_router.update_question_transcription(31, transcription, db)

    assert error.value.status_code == 502
    assert question.status == "failed"
    assert question.error_code == "visual_retrieval_failed"
    assert db.rollback_count == 1
