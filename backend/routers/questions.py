
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.dependencies import get_db
from database.models.question import Question
from database.models.session import Session as DBSession
from database.models.answer import Answer
from assistant.evidence_service import retrieve_question_evidence
from datetime import datetime, timezone

from fastapi import status
from sqlalchemy.exc import IntegrityError
# Import the schemas used to validate incoming question data and API responses.
from schemas.question import (
    QuestionCreate,       # Validates new question submissions.
    QuestionResponse,     # Defines the data returned when retrieving a question.
    AnswerResponse,       # Defines the data returned when retrieving an answer.
    TranscriptionUpdate  # Validates the transcription text and language received from Member 1.
)

# BaseModel defines the structure of API response schemas.
from pydantic import BaseModel, ConfigDict

# Import the service responsible for validating question status changes.
from assistant.question_service import update_question_status

# Query lets us validate pagination parameters.
from fastapi import Query

router = APIRouter(
    prefix="/api/questions",
    tags=["Questions"]
)

@router.post(
    "/",
    response_model=QuestionResponse,
    status_code=status.HTTP_201_CREATED
)
def create_question(
    question_data: QuestionCreate,
    db: Session = Depends(get_db)
):
    # Check that the requested session exists.
    db_session = db.query(DBSession).filter(
        DBSession.session_id == question_data.session_id
    ).first()

    if db_session is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )

    # Only accept questions for sessions that are currently active.
    if db_session.status != "active":
        raise HTTPException(
            status_code=409,
            detail="Cannot submit a question to an inactive session"
        )

    # Check whether this request was already submitted.
    # This makes retries safe and prevents duplicate questions.
    existing_question = db.query(Question).filter(
        Question.session_id == question_data.session_id,
        Question.client_request_id == str(question_data.client_request_id)
    ).first()

    if existing_question:
        return existing_question

    # Create the question with an explicit UTC timestamp.
    new_question = Question(
        session_id=question_data.session_id,
        client_request_id=str(question_data.client_request_id),
        input_type=question_data.input_type,
        question_text=question_data.question_text,
        language_code=question_data.language_code,
        search_from_at=question_data.search_from_at,
        search_to_at=question_data.search_to_at,
        received_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )

    try:
        # Save the new question in the database.
        db.add(new_question)
        db.commit()
        db.refresh(new_question)

    except IntegrityError:
        # Roll back if another request inserted the same client ID.
        db.rollback()

        # Retrieve the existing record after the duplicate conflict.
        existing_question = db.query(Question).filter(
            Question.session_id == question_data.session_id,
            Question.client_request_id == str(question_data.client_request_id)
        ).first()

        if existing_question:
            return existing_question

        raise HTTPException(
            status_code=409,
            detail="Could not create the question"
        )

    return new_question

@router.get(
    "/{question_id}",
    response_model=QuestionResponse
)
def get_question(
    question_id: int,
    db: Session = Depends(get_db)
):
    # Find the question using its primary key.
    question = db.query(Question).filter(
        Question.question_id == question_id
    ).first()

    # Return 404 if the requested question does not exist.
    if question is None:
        raise HTTPException(
            status_code=404,
            detail="Question not found"
        )

    # Return the question using the QuestionResponse schema.
    return question

@router.get(
    "/{question_id}/answer",
    response_model=AnswerResponse
)
def get_question_answer(
    question_id: int,
    db: Session = Depends(get_db)
):
    # First, verify that the requested question exists.
    question = db.query(Question).filter(
        Question.question_id == question_id
    ).first()

    if question is None:
        raise HTTPException(
            status_code=404,
            detail="Question not found"
        )

    # Retrieve the answer associated with this question.
    answer = db.query(Answer).filter(
        Answer.question_id == question_id
    ).first()

    # An answer may not exist yet if processing is still underway.
    if answer is None:
        raise HTTPException(
            status_code=404,
            detail="Answer not available yet"
        )

    # Return the answer using the AnswerResponse schema.
    return answer

@router.patch("/{question_id}/status")
def change_question_status(
    question_id: int,
    new_status: str,
    db: Session = Depends(get_db)
):
    try:
        # Update the question using the status-management service.
        question = update_question_status(
            db=db,
            question_id=question_id,
            new_status=new_status
        )

        # Return the updated question.
        return question

    except LookupError:
        # Return 404 when the question does not exist.
        raise HTTPException(
            status_code=404,
            detail="Question not found"
        )

    except ValueError as error:
        # Return 400 when the requested transition is invalid.
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

@router.get(
    "/session/{session_id}/history",
    response_model=list[QuestionResponse]
)
def get_question_history(
    session_id: int,
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0)
):
    # Check that the requested session exists.
    session = db.query(DBSession).filter(
        DBSession.session_id == session_id
    ).first()

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )

    # Retrieve the session's questions, newest first.
    questions = db.query(Question).filter(
        Question.session_id == session_id
    ).order_by(
        Question.received_at.desc()
    ).offset(offset).limit(limit).all()

    return questions


@router.patch("/{question_id}/transcription", response_model=QuestionResponse)
def update_question_transcription(
    question_id: int,
    transcription: TranscriptionUpdate,
    db: Session = Depends(get_db)
):
    # Find the question that needs to receive the transcription.
    question = db.query(Question).filter(
        Question.question_id == question_id
    ).first()

    # Return 404 if the requested question does not exist.
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found"
        )

    # Only accept a transcription while the question is being transcribed.
    if question.status != "transcribing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Question is not waiting for a transcription"
        )

    try:
        # Save the transcription from Member 1 before starting retrieval.
        question.question_text = transcription.question_text.strip()
        question.language_code = transcription.language_code
        question.status = "retrieving"
        db.commit()
        db.refresh(question)

        # Call Member 2's existing retrieval function through our bridge.
        retrieval_result = retrieve_question_evidence(question)

        # Persist the exact frame references for the later answering stage.
        question.retrieval_configuration = retrieval_result
        question.status = "answering"
        question.error_code = None
        db.commit()
        db.refresh(question)
        return question

    except Exception as error:
        # Mark the question failed if retrieval cannot complete.
        db.rollback()
        failed_question = db.query(Question).filter(
            Question.question_id == question_id
        ).first()

        if failed_question is not None:
            failed_question.status = "failed"
            failed_question.error_code = "visual_retrieval_failed"
            db.commit()

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Visual evidence retrieval failed"
        ) from error
