import argparse
import json
import math
from pathlib import Path
from uuid import uuid4

import cv2

from multimedia.frame_quality import evaluate_frame_quality
from multimedia.frame_similarity import compare_frames


def extract_useful_frames(video_path: str, sample_interval: float = 1.0):
    """Select useful frames from a saved video."""

    if not math.isfinite(sample_interval) or sample_interval <= 0:
        raise ValueError("Sample interval must be a positive number.")

    source = Path(video_path)

    if not source.is_file():
        raise FileNotFoundError(f"Video not found: {source}")

    capture = cv2.VideoCapture(str(source))

    try:
        if not capture.isOpened():
            raise ValueError("OpenCV could not open this video.")

        fps = capture.get(cv2.CAP_PROP_FPS)

        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("Video has no usable frame-rate information.")

        # A separate folder for every run prevents overwriting images.
        output_folder = (
            Path(__file__).resolve().parents[1]
            / "storage"
            / "frames"
            / f"video_{uuid4().hex[:12]}"
        )
        output_folder.mkdir(parents=True, exist_ok=False)

        previous_saved_frame = None
        saved_frames = []
        frame_index = 0
        next_sample_time = 0.0

        counts = {
            "sampled": 0,
            "rejected_quality": 0,
            "rejected_duplicate": 0,
            "saved": 0,
        }

        while True:
            success, frame = capture.read()

            if not success:
                break

            # Approximate position in this video, not a real-world date.
            timestamp_seconds = frame_index / fps
            current_index = frame_index
            frame_index += 1

            if timestamp_seconds < next_sample_time:
                continue

            next_sample_time = timestamp_seconds + sample_interval
            counts["sampled"] += 1

            quality = evaluate_frame_quality(frame)

            if not quality["passes_quality_check"]:
                counts["rejected_quality"] += 1
                continue

            novelty_score = None

            if previous_saved_frame is not None:
                comparison = compare_frames(frame, previous_saved_frame)
                novelty_score = comparison["novelty_score"]

                if comparison["is_duplicate"]:
                    counts["rejected_duplicate"] += 1
                    continue

            filename = f"frame_{current_index:06d}.jpg"
            destination = output_folder / filename

            if not cv2.imwrite(str(destination), frame):
                raise OSError(f"Could not save image: {destination}")

            saved_frames.append({
                "filename": filename,
                "source_frame_index": current_index,
                "video_timestamp_seconds": timestamp_seconds,
                "novelty_score": novelty_score,
                **quality,
            })

            previous_saved_frame = frame.copy()
            counts["saved"] += 1

        report = {
            "source_video": source.name,
            "fps": fps,
            "timestamp_method": "frame_index / nominal_fps",
            "sample_interval_seconds": sample_interval,
            "quality_thresholds": {
                "min_sharpness": 50.0,
                "min_brightness": 25.0,
            },
            "duplicate_threshold": 0.02,
            "counts": counts,
            "frames": saved_frames,
        }

        report_path = output_folder / "selection_report.json"
        report_path.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )

        return output_folder, counts

    finally:
        capture.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video_path")
    parser.add_argument("--interval", type=float, default=1.0)
    arguments = parser.parse_args()

    folder, results = extract_useful_frames(
        arguments.video_path,
        arguments.interval,
    )

    print("Results:", results)
    print("Saved in:", folder)