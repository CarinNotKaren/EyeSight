"""Compare Whisper Base and Small on the same audio files.

Run from backend:
    python -m scripts.benchmark_whisper path/to/en.wav path/to/fr.wav path/to/ar.wav

Run separately with --language en, --language fr, and --language ar for
controlled language-specific comparisons. Audio files stay local.
"""

import argparse
import os
from pathlib import Path
from time import perf_counter

from assistant.speech_to_text import _load_model, transcribe_audio


def main():
    parser = argparse.ArgumentParser(description="Benchmark Whisper Base vs Small.")
    parser.add_argument("audio_files", nargs="+", help="Local audio files to compare.")
    parser.add_argument(
        "--language",
        choices=("en", "fr", "ar"),
        default=None,
        help="Known language; omit to test automatic language detection.",
    )
    args = parser.parse_args()

    for model_name in ("base", "small"):
        os.environ["WHISPER_MODEL"] = model_name

        print(f"\n=== Whisper {model_name.title()} ===")

        # Measure checkpoint loading separately from audio inference.
        loading_started = perf_counter()
        _load_model(model_name)
        loading_seconds = perf_counter() - loading_started
        print({"model_load_seconds": round(loading_seconds, 3)})

        for audio_file in args.audio_files:
            path = Path(audio_file)

            if not path.is_file():
                print({"file": path.name, "error": "file not found"})
                continue

            inference_started = perf_counter()

            try:
                result = transcribe_audio(str(path), args.language)
                inference_seconds = perf_counter() - inference_started

                print({
                    "file": path.name,
                    "language": result["language"],
                    "duration_seconds": result["duration_seconds"],
                    "transcription_seconds": round(inference_seconds, 3),
                    "transcript": result["transcript"],
                })
            except Exception as error:
                print({
                    "file": path.name,
                    "error": type(error).__name__,
                    "message": str(error),
                })


if __name__ == "__main__":
    main()
