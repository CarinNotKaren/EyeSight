from sqlalchemy.orm import Session as DBSession

from database.models.question import Question


# Define valid processing stages for both text and voice questions.
ALLOWED_TRANSITIONS = {
    "received": ["transcribing", "retrieving", "failed"],
    "transcribing": ["retrieving", "failed"],
    "retrieving": ["answering", "failed"],
    "answering": ["completed", "failed"],
    "completed": [],
    "failed": [],
}


def update_question_status(
    db: DBSession,
    question_id: int,
    new_status: str,
    error_code: str | None = None,
):
    # Find the question in the database.
    question = db.query(Question).filter(
        Question.question_id == question_id
    ).first()

    if question is None:
        raise LookupError("Question not found")

    # Prevent invalid or backward status changes.
    allowed_statuses = ALLOWED_TRANSITIONS.get(question.status, [])
    if new_status not in allowed_statuses:
        raise ValueError(
            f"Cannot change question status "
            f"from '{question.status}' to '{new_status}'"
        )

    try:
        question.status = new_status
        question.error_code = (
            error_code if new_status == "failed" else None
        )
        db.commit()
        db.refresh(question)
        return question

    except Exception:
        db.rollback()
        raise
