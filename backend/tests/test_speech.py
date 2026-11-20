"""Tests for audio upload validation and the Whisper service contract."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from routers import speech as speech_router


def make_upload(filename="question.wav", content=b"sample-audio"):
    """Create an in-memory upload without writing test recordings to disk."""
    return UploadFile(
        filename=filename,
        file=BytesIO(content),
    )


def test_transcribe_route_returns_whisper_result(monkeypatch):
    # Replace the real model call so the route test does not download weights.
    expected = {
        "transcript": "What is in front of me?",
        "language": "en",
        "duration_seconds": 2.8,
    }
    monkeypatch.setattr(speech_router, "transcribe_audio", lambda **kwargs: expected)

    result = speech_router.transcribe_speech(
        file=make_upload(),
        language="en",
    )

    assert result == expected


def test_transcribe_route_allows_automatic_language_detection(monkeypatch):
    # An omitted language must be passed to Whisper as None for detection.
    received = {}
    monkeypatch.setattr(
        speech_router,
        "transcribe_audio",
        lambda **kwargs: received.update(kwargs) or {
            "transcript": "Bonjour.",
            "language": "fr",
            "duration_seconds": 1.2,
        },
    )

    result = speech_router.transcribe_speech(
        file=make_upload("question.m4a"),
        language=None,
    )

    assert received["language"] is None
    assert result["language"] == "fr"


def test_transcribe_route_rejects_unsupported_language():
    # Only the agreed project language codes are accepted.
    with pytest.raises(HTTPException) as error:
        speech_router.transcribe_speech(
            file=make_upload(),
            language="de",
        )

    assert error.value.status_code == 422


def test_transcribe_route_rejects_unsupported_file_extension():
    # Non-audio uploads must be rejected before invoking Whisper.
    with pytest.raises(HTTPException) as error:
        speech_router.transcribe_speech(
            file=make_upload("document.pdf"),
            language="en",
        )

    assert error.value.status_code == 415


def test_transcribe_route_rejects_empty_audio():
    # Empty uploads should not trigger model loading.
    with pytest.raises(HTTPException) as error:
        speech_router.transcribe_speech(
            file=make_upload(content=b""),
            language="en",
        )

    assert error.value.status_code == 422


def test_transcribe_route_rejects_upload_over_25_mb():
    # Test the size guard without allocating a 25 MB fixture.
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        speech_router,
        "MAX_AUDIO_SIZE_BYTES",
        4,
    )

    try:
        with pytest.raises(HTTPException) as error:
            speech_router.transcribe_speech(
                file=make_upload(content=b"12345"),
                language="en",
            )

        assert error.value.status_code == 413
    finally:
        monkeypatch.undo()


def test_transcribe_route_hides_model_error(monkeypatch):
    # Internal model exceptions must not leak paths or implementation details.
    monkeypatch.setattr(
        speech_router,
        "transcribe_audio",
        lambda **kwargs: (_ for _ in ()).throw(
            speech_router.SpeechTranscriptionError("private model detail")
        ),
    )

    with pytest.raises(HTTPException) as error:
        speech_router.transcribe_speech(
            file=make_upload(),
            language="en",
        )

    assert error.value.status_code == 503
    assert error.value.detail == "Speech transcription is temporarily unavailable."
