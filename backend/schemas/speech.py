"""Response schema for the speech transcription API."""

from pydantic import BaseModel, Field


class SpeechTranscriptionResponse(BaseModel):
    """Transcript returned to the mobile app for user review."""

    # The recognized words. It must not be empty because an empty transcript
    # means Whisper did not recognize any speech.
    transcript: str = Field(min_length=1)

    # Use the same short language codes throughout the project:
    # en = English, fr = French, and ar = Arabic.
    language: str = Field(pattern="^(en|fr|ar)$")

    # How long the original recording was, in seconds.
    # It is optional in case a caller does not have duration information,
    # but when provided it cannot be a negative number.
    duration_seconds: float | None = Field(default=None, ge=0)
