"""Tests for audio upload validation and the Whisper service contract."""

import sys
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from assistant import speech_to_text
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


def test_transcribe_route_rejects_upload_over_limit(monkeypatch):
    # Reduce the limit for this test instead of allocating a 25 MB fixture.
    monkeypatch.setattr(speech_router, "MAX_AUDIO_SIZE_BYTES", 4)

    with pytest.raises(HTTPException) as error:
        speech_router.transcribe_speech(
            file=make_upload(content=b"12345"),
            language="en",
        )

    assert error.value.status_code == 413


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


def test_transcribe_audio_returns_detected_language_and_duration(
    monkeypatch,
    tmp_path,
):
    # Mock Whisper so the test verifies the service contract without model weights.
    fake_model = SimpleNamespace(
        transcribe=lambda audio, **kwargs: {
            "text": "Bonjour, comment allez-vous?",
            "language": "fr",
        }
    )
    fake_whisper = SimpleNamespace(
        load_audio=lambda path: [0.0] * 32000,
        audio=SimpleNamespace(SAMPLE_RATE=16000),
        tokenizer=SimpleNamespace(LANGUAGES={
            "en": "english",
            "fr": "french",
            "ar": "arabic",
        }),
    )
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)
    monkeypatch.setattr(speech_to_text, "_load_model", lambda name: fake_model)

    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"mock audio")

    result = speech_to_text.transcribe_audio(str(audio_file), language=None)

    assert result == {
        "transcript": "Bonjour, comment allez-vous?",
        "language": "fr",
        "duration_seconds": 2.0,
    }


def test_transcribe_audio_uses_explicit_language(monkeypatch, tmp_path):
    # An explicitly selected language is forwarded to the model.
    received = {}
    fake_model = SimpleNamespace(
        transcribe=lambda audio, **kwargs: received.update(kwargs) or {
            "text": "مرحبا",
            "language": "ar",
        }
    )
    fake_whisper = SimpleNamespace(
        load_audio=lambda path: [0.0] * 16000,
        audio=SimpleNamespace(SAMPLE_RATE=16000),
        tokenizer=SimpleNamespace(LANGUAGES={}),
    )
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)
    monkeypatch.setattr(speech_to_text, "_load_model", lambda name: fake_model)

    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"mock audio")

    result = speech_to_text.transcribe_audio(str(audio_file), language="ar")

    assert received["language"] == "ar"
    assert result["language"] == "ar"
    assert result["duration_seconds"] == 1.0


def test_transcribe_audio_rejects_unsupported_language(tmp_path):
    # Keep the model from being loaded when the language code is invalid.
    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"mock audio")

    with pytest.raises(ValueError, match="language must be one of"):
        speech_to_text.transcribe_audio(str(audio_file), language="de")


def test_transcribe_audio_rejects_empty_transcription(monkeypatch, tmp_path):
    # Silence or unintelligible audio must not produce an empty successful result.
    fake_model = SimpleNamespace(
        transcribe=lambda audio, **kwargs: {"text": " ", "language": "en"}
    )
    fake_whisper = SimpleNamespace(
        load_audio=lambda path: [0.0] * 16000,
        audio=SimpleNamespace(SAMPLE_RATE=16000),
        tokenizer=SimpleNamespace(LANGUAGES={}),
    )
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)
    monkeypatch.setattr(speech_to_text, "_load_model", lambda name: fake_model)

    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"mock audio")

    with pytest.raises(speech_to_text.SpeechTranscriptionError):
        speech_to_text.transcribe_audio(str(audio_file), language="en")
