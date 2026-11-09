from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QuestionCreate(BaseModel):
    # Identify the session to which this question belongs.
    session_id: int

    # Unique client-generated ID prevents duplicate question submissions.
    client_request_id: UUID

        # Optional exact frame to use for a question about the current view.
    # When omitted, the retrieval service searches relevant past frames.
    frame_id: int | None = Field(default=None, gt=0)

    # A question can be submitted as typed text or recorded voice.
    input_type: Literal["voice", "text"]

    # Voice questions may initially have no text because transcription
    # has not happened yet. Text questions must include question_text.
    question_text: str | None = None

    # Language used for the question, such as "en", "fr", or "ar".
    language_code: str | None = Field(default=None, max_length=16)

    # Optional time range used later when retrieving visual evidence.
    search_from_at: datetime | None = None
    search_to_at: datetime | None = None

    @model_validator(mode="after")
    def validate_question(self):
        # Reject text submissions that contain no question.
        if self.input_type == "text" and not self.question_text:
            raise ValueError("question_text is required for text input")

        # Ensure the requested search interval is valid.
        if (
            self.search_from_at is not None
            and self.search_to_at is not None
            and self.search_from_at > self.search_to_at
        ):
            raise ValueError("search_from_at must be before search_to_at")

        return self


class QuestionResponse(BaseModel):
    # Allow Pydantic to read values directly from SQLAlchemy objects.
    model_config = ConfigDict(from_attributes=True)

    question_id: int
    session_id: int
    client_request_id: str
    input_type: str
    question_text: str | None
    language_code: str | None
    status: str
    received_at: datetime

class AnswerResponse(BaseModel):
    # Allow FastAPI to serialize SQLAlchemy Answer objects.
    model_config = ConfigDict(from_attributes=True)

    answer_id: int
    question_id: int
    model_id: int | None
    answer_text: str
    language_code: str
    answer_type: str
    uncertainty_reason: str | None
    prompt_version: str
    stt_latency_ms: int | None
    retrieval_latency_ms: int | None
    generation_latency_ms: int | None
    server_total_latency_ms: int
    playback_started_at: datetime | None
    created_at: datetime

# Define the structure of the transcription received from Member 1.
class TranscriptionUpdate(BaseModel):

    # Store the text recognized from the user's voice recording.
    question_text: str = Field(min_length=1)

    # Store the language detected by Whisper.
    language_code: str = Field(min_length=2, max_length=16)

class AnswerEvidenceResponse(BaseModel):
    """Public, storage-safe reference to a frame used for an answer."""

    model_config = ConfigDict(from_attributes=True)

    answer_id: int
    frame_id: int
    retrieval_rank: int
    retrieval_method: str
    semantic_score: float | None
    combined_score: float | None
    provided_to_model: bool
