"""Response schema for the speech transcription API."""

from pydantic import BaseModel, Field


class SpeechTranscriptionResponse(BaseModel):
    """Transcript returned to the mobile app for user review."""

    transcript: str = Field(min_length=1)
    language: str = Field(pattern="^(en|fr|ar)$")
    duration_seconds: float | None = Field(default=None, ge=0)
