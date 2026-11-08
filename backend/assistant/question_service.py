from sqlalchemy.orm import Session as DBSession

from database.models.question import Question


# Define the valid processing stages for a voice question.
ALLOWED_TRANSITIONS = {
    "received": ["transcribing", "failed"],
    "transcribing": ["retrieving", "failed"],
    "retrieving": ["answering", "failed"],
    "answering": ["completed", "failed"],
    "completed": [],
    "failed": []
}


def update_question_status(
    db: DBSession,
    question_id: int,
    new_status: str,
    error_code: str | None = None
):
    # Find the question in the database.
    question = db.query(Question).filter(
        Question.question_id == question_id
    ).first()

    # Stop if the question does not exist.
    if question is None:
        raise LookupError("Question not found")

    # Get the statuses allowed after the current status.
    allowed_statuses = ALLOWED_TRANSITIONS.get(question.status, [])

    # Prevent invalid or backward status changes.
    if new_status not in allowed_statuses:
        raise ValueError(
            f"Cannot change question status "
            f"from '{question.status}' to '{new_status}'"
        )

    try:
        # Update the question's processing status.
        question.status = new_status

        # Save an error code only if processing failed.
        question.error_code = (
            error_code if new_status == "failed" else None
        )

        # Save the update to MySQL.
        db.commit()

        # Refresh the question with the saved database values.
        db.refresh(question)

        return question

    except Exception:
        # Roll back the transaction if saving fails.
        db.rollback()
        raise