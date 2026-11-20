"""Audio upload and Whisper transcription endpoint owned by Member 3."""

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from assistant.speech_to_text import (
    SUPPORTED_LANGUAGES,
    SpeechTranscriptionError,
    transcribe_audio,
)
from schemas.speech import SpeechTranscriptionResponse

router = APIRouter(
    prefix="/api/speech",
    tags=["Speech"],
)

# Keep the upload limit aligned with the team interface contract.
MAX_AUDIO_SIZE_BYTES = 25 * 1024 * 1024

# Whisper/FFmpeg can decode these common browser and mobile recording formats.
ALLOWED_AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".flac", ".mpeg", ".mpga",
}


@router.post(
    "/transcribe",
    response_model=SpeechTranscriptionResponse,
    status_code=status.HTTP_200_OK,
)
def transcribe_speech(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
):
    """Validate an uploaded recording, transcribe it, and return the transcript."""
    if language is not None:
        language = language.strip().lower()

        if language not in SUPPORTED_LANGUAGES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="language must be one of: en, fr, ar.",
            )

    suffix = Path(file.filename or "").suffix.lower()

    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported audio file format.",
        )

    # Read at most one byte beyond the limit to reject oversized uploads safely.
    audio_bytes = file.file.read(MAX_AUDIO_SIZE_BYTES + 1)

    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The uploaded audio file is empty.",
        )

    if len(audio_bytes) > MAX_AUDIO_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio upload exceeds the 25 MB limit.",
        )

    # Use a temporary file because Whisper/FFmpeg accepts a filesystem path.
    # The file is deleted automatically after inference, including on errors.
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=suffix,
            delete=True,
        ) as temporary_audio:
            temporary_audio.write(audio_bytes)
            temporary_audio.flush()

            result = transcribe_audio(
                audio_path=temporary_audio.name,
                language=language,
            )

        return result

    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except SpeechTranscriptionError as error:
        # Do not expose local paths, model internals, or provider details.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Speech transcription is temporarily unavailable.",
        ) from error
    finally:
        # Close the incoming upload handle after processing.
        file.file.close()
