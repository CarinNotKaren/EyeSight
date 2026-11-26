"""Local Whisper speech-to-text service for EyeSight.

The API router receives and temporarily stores the uploaded recording.
This service takes that file, asks Whisper to recognize the spoken words,
and returns the transcript plus information about the recording.
"""

import os
from functools import lru_cache
from pathlib import Path

from whisper.tokenizer import LANGUAGES

# Support all languages available in the installed OpenAI Whisper package.
SUPPORTED_LANGUAGES = frozenset(LANGUAGES.keys())
DEFAULT_MODEL_NAME = "base"


class SpeechTranscriptionError(RuntimeError):
    """Raised when audio cannot be transcribed by the configured Whisper model."""


def _get_model_name():
    """Read the selected benchmarked Whisper checkpoint from the environment."""
    model_name = os.getenv("WHISPER_MODEL", DEFAULT_MODEL_NAME).strip().lower()

    if model_name not in {"base", "small"}:
        raise ValueError("WHISPER_MODEL must be either 'base' or 'small'.")

    return model_name


@lru_cache(maxsize=2)
def _load_model(model_name):
    """Load each Whisper checkpoint once instead of reloading it per request."""
    try:
        import whisper

        # CPU is the default so this also works on laptops without a supported GPU.
        # WHISPER_DEVICE can be changed later if we decide to use an available GPU.
        device = os.getenv("WHISPER_DEVICE", "cpu").strip().lower()
        return whisper.load_model(model_name, device=device)
    except Exception as error:
        raise SpeechTranscriptionError(
            f"Whisper model could not be loaded ({type(error).__name__})."
        ) from error


def _normalize_language(language_value):
    """Normalize Whisper's detected language value to en, fr, or ar."""
    value = (language_value or "").strip().lower()

    # Whisper usually gives us short codes such as 'en' and 'fr'.
    # This first check handles that normal response without extra work.
    if value in SUPPORTED_LANGUAGES:
        return value

    # If a language name is returned instead (for example, 'french'),
    # convert it to the short code expected by EyeSight's API.
    try:
        import whisper

        language_codes = {
            name.lower(): code
            for code, name in whisper.tokenizer.LANGUAGES.items()
        }
        return language_codes.get(value)
    except Exception:
        return None


def transcribe_audio(audio_path: str, language: str | None = None) -> dict:
    """Transcribe one recording and return the agreed API-compatible result.

    Args:
        audio_path: Temporary path to an uploaded audio file.
        language: 'en', 'fr', 'ar', or None to let Whisper detect the language.

    Returns:
        A dictionary containing transcript, language, and duration_seconds.
    """
    if language is not None:
        language = language.strip().lower()

        if language not in SUPPORTED_LANGUAGES:
            raise ValueError("language must be one of: en, fr, ar.")

    path = Path(audio_path)

    if not path.is_file():
        raise ValueError("The uploaded audio file is unavailable.")

    model_name = _get_model_name()
    model = _load_model(model_name)

    try:
        import whisper

        # Whisper cannot work directly with the uploaded file handle.
        # load_audio decodes the file and converts it into the audio format
        # Whisper expects (16 kHz audio samples).
        audio = whisper.load_audio(str(path))

        # Because the samples are now at 16,000 samples per second,
        # dividing their count by 16,000 gives the recording length in seconds.
        duration_seconds = round(len(audio) / whisper.audio.SAMPLE_RATE, 2)

        # If the user chose a language, tell Whisper which language to listen for.
        # If language is None, Whisper detects the spoken language automatically.
        result = model.transcribe(
            audio,
            language=language,
            task="transcribe",
            fp16=False,
            verbose=False,
        )

        transcript = (result.get("text") or "").strip()
        detected_language = result.get("language")

        # Whisper can return an empty string for silence or audio it cannot
        # understand. We treat that as a failed transcription, not a valid answer.
        if not transcript:
            raise SpeechTranscriptionError("No speech could be recognized.")

        # Use the language selected by the user when available.
        # Otherwise, convert Whisper's detected language into our API language code.
        normalized_language = language or _normalize_language(detected_language)

        if normalized_language not in SUPPORTED_LANGUAGES:
            raise SpeechTranscriptionError(
                "The detected language is not one of the supported languages."
            )

        return {
            "transcript": transcript,
            "language": normalized_language,
            "duration_seconds": duration_seconds,
        }

    except SpeechTranscriptionError:
        raise
    except Exception as error:
        # Convert low-level Whisper/FFmpeg errors into one service-level error.
        # The API route will turn this into a safe HTTP response for the app.
        raise SpeechTranscriptionError(
            f"Audio transcription failed ({type(error).__name__})."
        ) from error
