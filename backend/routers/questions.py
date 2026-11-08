from datetime import datetime, timezone
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from assistant.answer_service import generate_and_persist_answer
from assistant.evidence_service import retrieve_question_evidence
from assistant.question_service import update_question_status
from database.dependencies import get_db
from database.models.answer import Answer
from database.models.answer_evidence import AnswerEvidence
from database.models.question import Question
from database.models.session import Session as DBSession
from schemas.question import (
    AnswerEvidenceResponse,
    AnswerResponse,
    QuestionCreate,
    QuestionResponse,
    TranscriptionUpdate,
)

router = APIRouter(
    prefix="/api/questions",
    tags=["Questions"],
)


def _mark_question_failed(db, question_id, error_code):
    """Persist a terminal failure after rolling back the failed operation."""
    db.rollback()
    failed_question = db.query(Question).filter(
        Question.question_id == question_id
    ).first()

    if failed_question is not None:
        failed_question.status = "failed"
        failed_question.error_code = error_code
        db.commit()


def _retrieve_and_answer(question, db):
    """Run the shared retrieval -> VLM -> Answer/Evidence persistence flow."""
    retrieval_started = perf_counter()

    try:
        # Reuse Member 2's retrieval implementation and preserve its metadata.
        retrieval_result = retrieve_question_evidence(question)
        retrieval_result["retrieval_latency_ms"] = round(
            (perf_counter() - retrieval_started) * 1000
        )

        question.retrieval_configuration = retrieval_result
        question.status = "answering"
        question.error_code = None
        db.commit()
        db.refresh(question)

    except Exception as error:
        _mark_question_failed(
            db, question.question_id, "visual_retrieval_failed"
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Visual evidence retrieval failed",
        ) from error

    try:
        # The service persists the answer and the exact frame evidence.
        # Provider failures become a safe error_fallback answer in that service.
        generate_and_persist_answer(db, question)
        db.refresh(question)
        return question

    except Exception as error:
        _mark_question_failed(
            db, question.question_id, "answer_persistence_failed"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The answer could not be saved",
        ) from error


@router.post(
    "/",
    response_model=QuestionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_question(
    question_data: QuestionCreate,
    db: Session = Depends(get_db),
):
    # Check that the requested session exists.
    db_session = db.query(DBSession).filter(
        DBSession.session_id == question_data.session_id
    ).first()

    if db_session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Only accept questions for sessions that are currently active.
    if db_session.status != "active":
        raise HTTPException(
            status_code=409,
            detail="Cannot submit a question to an inactive session",
        )

    # Make client retries safe and prevent duplicate question records.
    existing_question = db.query(Question).filter(
        Question.session_id == question_data.session_id,
        Question.client_request_id == str(question_data.client_request_id),
    ).first()

    if existing_question:
        return existing_question

    new_question = Question(
        session_id=question_data.session_id,
        client_request_id=str(question_data.client_request_id),
        input_type=question_data.input_type,
        question_text=question_data.question_text,
        language_code=question_data.language_code,
        search_from_at=question_data.search_from_at,
        search_to_at=question_data.search_to_at,
        received_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    try:
        db.add(new_question)
        db.commit()
        db.refresh(new_question)

    except IntegrityError:
        # Handle a duplicate request inserted concurrently by another client.
        db.rollback()
        existing_question = db.query(Question).filter(
            Question.session_id == question_data.session_id,
            Question.client_request_id == str(question_data.client_request_id),
        ).first()

        if existing_question:
            return existing_question

        raise HTTPException(
            status_code=409,
            detail="Could not create the question",
        )

    return new_question


@router.get(
    "/{question_id}",
    response_model=QuestionResponse,
)
def get_question(
    question_id: int,
    db: Session = Depends(get_db),
):
    question = db.query(Question).filter(
        Question.question_id == question_id
    ).first()

    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    return question


@router.get(
    "/{question_id}/answer",
    response_model=AnswerResponse,
)
def get_question_answer(
    question_id: int,
    db: Session = Depends(get_db),
):
    # Verify that the question exists before looking up its answer.
    question = db.query(Question).filter(
        Question.question_id == question_id
    ).first()

    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    answer = db.query(Answer).filter(
        Answer.question_id == question_id
    ).first()

    if answer is None:
        raise HTTPException(
            status_code=404,
            detail="Answer not available yet",
        )

    return answer


@router.get(
    "/{question_id}/answer/evidence",
    response_model=list[AnswerEvidenceResponse],
)
def get_question_answer_evidence(
    question_id: int,
    db: Session = Depends(get_db),
):
    """Return the frame references and retrieval scores supporting an answer."""
    question = db.query(Question).filter(
        Question.question_id == question_id
    ).first()

    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    answer = db.query(Answer).filter(
        Answer.question_id == question_id
    ).first()

    if answer is None:
        raise HTTPException(
            status_code=404,
            detail="Answer not available yet",
        )

    # Do not expose local storage paths or raw image bytes through this route.
    return db.query(AnswerEvidence).filter(
        AnswerEvidence.answer_id == answer.answer_id
    ).order_by(AnswerEvidence.retrieval_rank).all()


@router.patch("/{question_id}/status")
def change_question_status(
    question_id: int,
    new_status: str,
    db: Session = Depends(get_db),
):
    try:
        return update_question_status(
            db=db,
            question_id=question_id,
            new_status=new_status,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Question not found")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get(
    "/session/{session_id}/history",
    response_model=list[QuestionResponse],
)
def get_question_history(
    session_id: int,
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    session = db.query(DBSession).filter(
        DBSession.session_id == session_id
    ).first()

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Return the newest questions first, with bounded pagination.
    return db.query(Question).filter(
        Question.session_id == session_id
    ).order_by(
        Question.received_at.desc()
    ).offset(offset).limit(limit).all()


@router.patch(
    "/{question_id}/transcription",
    response_model=QuestionResponse,
)
def update_question_transcription(
    question_id: int,
    transcription: TranscriptionUpdate,
    db: Session = Depends(get_db),
):
    question = db.query(Question).filter(
        Question.question_id == question_id
    ).first()

    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    if question.status != "transcribing":
        raise HTTPException(
            status_code=409,
            detail="Question is not waiting for a transcription",
        )

    question_text = transcription.question_text.strip()
    if not question_text:
        raise HTTPException(
            status_code=422,
            detail="Transcription text cannot be empty",
        )

    # Save Member 1's transcription before retrieval starts.
    question.question_text = question_text
    question.language_code = transcription.language_code
    question.status = "retrieving"
    db.commit()
    db.refresh(question)

    # Voice questions continue automatically through retrieval and answering.
    return _retrieve_and_answer(question, db)


@router.post(
    "/{question_id}/process",
    response_model=QuestionResponse,
)
def process_text_question(
    question_id: int,
    db: Session = Depends(get_db),
):
    """Start retrieval and VLM answering for a previously submitted text question."""
    question = db.query(Question).filter(
        Question.question_id == question_id
    ).first()

    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    if question.input_type != "text" or not question.question_text:
        raise HTTPException(
            status_code=409,
            detail="Only submitted text questions can use this endpoint",
        )

    if question.status != "received":
        raise HTTPException(
            status_code=409,
            detail="Question is not waiting to be processed",
        )

    question.status = "retrieving"
    db.commit()
    db.refresh(question)

    return _retrieve_and_answer(question, db)
