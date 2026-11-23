# EyeSight Whisper Speech-to-Text

This module is maintained by Member 3 for the reassigned Whisper and audio-upload work. It does not modify Member 1's mobile recording code or Member 2's multimedia processing code.

## Model selection

The team plan requires comparing multilingual Whisper Base and Small checkpoints. The initial default is `base`; use the same audio samples and language settings for both models before choosing the final checkpoint.

Supported language codes are:

- `en` — English
- `fr` — French
- `ar` — Arabic

Set these values in the local `backend/.env` file:

```dotenv
WHISPER_MODEL=base
WHISPER_DEVICE=cpu
```

Change `WHISPER_MODEL` to `small` when benchmarking the Small checkpoint. The model is loaded lazily and cached for reuse. The first run downloads the selected checkpoint into the local Whisper cache; subsequent runs reuse it.

## System prerequisite

OpenAI Whisper uses FFmpeg to decode uploaded audio. Install FFmpeg on the backend computer and make sure the `ffmpeg` executable is available on PATH.

Verify from PowerShell:

```powershell
ffmpeg -version
```

## Python dependency

From the backend directory and the project's active virtual environment:

```powershell
python -m pip install -r requirements.txt
```

## API contract

### `POST /api/speech/transcribe`

Content type: `multipart/form-data`

| Field | Required | Description |
|---|---|---|
| `file` | Yes | Audio recording; supported extensions include WAV, MP3, M4A, MP4, WebM, OGG and FLAC |
| `language` | No | `en`, `fr`, or `ar`; omit to let Whisper detect the language |

Maximum upload size: 25 MB.

Successful response (HTTP 200):

```json
{
  "transcript": "What is in front of me?",
  "language": "en",
  "duration_seconds": 2.8
}
```

The transcript is returned to the mobile app for user review. This endpoint does not create a question, write audio to permanent storage, or change the question/answer database schema. The frontend submits the reviewed transcript through the existing question workflow.

Expected validation responses include:

- HTTP 415 for an unsupported file extension.
- HTTP 413 when the upload exceeds 25 MB.
- HTTP 422 for an empty recording or unsupported language.
- HTTP 503 when the transcription model is unavailable or inference fails.

Temporary audio files are deleted after transcription.

## Whisper Base vs Small benchmark

Use the same recordings for both checkpoints. Test English, French and Arabic separately, including clear speech and noisy recordings.

Example PowerShell commands from `backend`:

```powershell
python -m scripts.benchmark_whisper .\tests\audio\english.wav .\tests\audio\french.wav .\tests\audio\arabic.wav --language en
python -m scripts.benchmark_whisper .\tests\audio\english.wav .\tests\audio\french.wav .\tests\audio\arabic.wav --language fr
python -m scripts.benchmark_whisper .\tests\audio\english.wav .\tests\audio\french.wav .\tests\audio\arabic.wav --language ar
```

Use the matching language-specific recordings for each run. Record model loading time and transcription time separately. Calculate Word Error Rate (WER) against the verified reference transcripts and document results by language, model, hardware and recording condition. Do not commit real participant recordings or private audio samples.

## Tests

Run the route and service tests without downloading Whisper weights:

```powershell
python -m pytest tests/test_speech.py -v
```

The tests mock model inference and cover upload validation, supported languages, automatic language detection, empty transcription and safe error responses.
