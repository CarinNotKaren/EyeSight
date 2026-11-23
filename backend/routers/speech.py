
"""Audio upload and Whisper transcription endpoint owned by Member 3."""

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from assistant.speech_to_text import (
    SUPPORTED_LANGUAGES,
    SpeechTranscriptionError,
    transcribe_audio,
)
from schemas.speech import SpeechTranscriptionResponse


# Keep detailed errors in the backend terminal, not in API responses.
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/speech",
    tags=["Speech"],
)

# The mobile app sends the recording as an uploaded file.
# A size limit prevents one request from filling the backend computer's memory.
MAX_AUDIO_SIZE_BYTES = 25 * 1024 * 1024

# These are common formats produced by phones and browsers.
# Whisper uses FFmpeg behind the scenes to decode the supported audio formats.
ALLOWED_AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".flac", ".mpeg", ".mpga",
}


@router.post(
    "/transcribe",
    response_model=SpeechTranscriptionResponse,
    status_code=200,
)
def transcribe_speech(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
):
    """Validate an uploaded recording, transcribe it, and return the transcript."""

    try:
        # The language field is optional. If omitted, Whisper detects it automatically.
        if language is not None:
            language = language.strip().lower()

            if language not in SUPPORTED_LANGUAGES:
                raise HTTPException(
                    status_code=422,
                    detail="The selected language is not supported by Whisper.",
                )

        # Check the filename extension before passing the recording to FFmpeg.
        suffix = Path(file.filename or "").suffix.lower()

        if suffix not in ALLOWED_AUDIO_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail="Unsupported audio file format.",
            )

        # Read only up to the allowed size plus one extra byte.
        # The extra byte tells us whether the upload exceeds the limit.
        audio_bytes = file.file.read(MAX_AUDIO_SIZE_BYTES + 1)

        if not audio_bytes:
            raise HTTPException(
                status_code=422,
                detail="The uploaded audio file is empty.",
            )

        if len(audio_bytes) > MAX_AUDIO_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Audio upload exceeds the 25 MB limit.",
            )

        # Store the recording temporarily for Whisper and FFmpeg.
        # TemporaryDirectory removes the file automatically afterward.
        with tempfile.TemporaryDirectory(prefix="eyesight_audio_") as temp_dir:
            temporary_audio_path = Path(temp_dir) / f"recording{suffix}"
            temporary_audio_path.write_bytes(audio_bytes)

            # The service handles the actual Whisper model and recognition.
            result = transcribe_audio(
                audio_path=str(temporary_audio_path),
                language=language,
            )

        return result

    except HTTPException:
        # Preserve the specific validation status codes (413, 415, and 422).
        raise

    except ValueError as error:
        # Invalid service input is a client error.
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    except SpeechTranscriptionError as error:
        # Log the original exception and traceback for local debugging.
        # The API still returns a safe, generic message to the mobile app.
        logger.exception("Speech transcription failed.")

        raise HTTPException(
            status_code=503,
            detail="Speech transcription is temporarily unavailable.",
        ) from error

    finally:
        # Close the uploaded file handle after success or failure.
        file.file.close()
