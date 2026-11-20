"""Local Whisper speech-to-text service for EyeSight.

The model is loaded lazily and reused across requests. The API route owns
temporary audio files; this module only handles model inference.
"""

import os
from functools import lru_cache
from pathlib import Path

SUPPORTED_LANGUAGES = {"en", "fr", "ar"}
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

        # Keep CPU as the default for compatibility with the team's laptops.
        device = os.getenv("WHISPER_DEVICE", "cpu").strip().lower()
        return whisper.load_model(model_name, device=device)
    except Exception as error:
        raise SpeechTranscriptionError(
            f"Whisper model could not be loaded ({type(error).__name__})."
        ) from error


def _normalize_language(language_name):
    """Convert Whisper's detected language name into the project's ISO code."""
    try:
        import whisper

        language_codes = {
            name.lower(): code
            for code, name in whisper.tokenizer.LANGUAGES.items()
        }
        return language_codes.get(language_name.lower())
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

        # Decode and resample audio once; the same samples provide duration.
        audio = whisper.load_audio(str(path))
        duration_seconds = round(len(audio) / whisper.audio.SAMPLE_RATE, 2)

        # Use the selected language or allow Whisper to detect it automatically.
        result = model.transcribe(
            audio,
            language=language,
            task="transcribe",
            fp16=False,
            verbose=False,
        )

        transcript = (result.get("text") or "").strip()
        detected_language = result.get("language")

        if not transcript:
            raise SpeechTranscriptionError("No speech could be recognized.")

        # Return the explicitly selected language, otherwise normalize detection.
        normalized_language = language or _normalize_language(detected_language or "")

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
        raise SpeechTranscriptionError(
            f"Audio transcription failed ({type(error).__name__})."
        ) from error
