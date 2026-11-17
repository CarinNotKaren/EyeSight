#save your extracted frames in MySQL
import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from database.connection import SessionLocal
from database.models import User, Device, Session, Frame


def import_video_frames(report_path: str):
    """Import extracted frames into a new local demo session."""

    storage_root = (
        Path(__file__).resolve().parents[1] / "storage" / "frames"
    ).resolve()

    report_file = Path(report_path).resolve()

    if not report_file.is_relative_to(storage_root):
        raise ValueError("Report must be inside storage/frames.")

    report = json.loads(report_file.read_text(encoding="utf-8"))
    entries = report["frames"]

    if not entries:
        raise ValueError("This report contains no saved frames.")

    prepared = []

    for entry in entries:
        image_path = (report_file.parent / entry["filename"]).resolve()

        if not image_path.is_relative_to(report_file.parent):
            raise ValueError("Image path must stay inside the report folder.")

        if not image_path.is_file():
            raise FileNotFoundError(f"Missing image: {image_path}")

        offset = float(entry["video_timestamp_seconds"])

        if not math.isfinite(offset) or offset < 0:
            raise ValueError("Video timestamps must be finite and non-negative.")

        storage_key = image_path.relative_to(storage_root.parent).as_posix()
        prepared.append((entry, image_path, storage_key, offset))

    # Store UTC as timezone-naive values, matching our MySQL convention.
    imported_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # Give this demo a synthetic timeline ending at import time.
    started_at = imported_at - timedelta(
        seconds=max(item[3] for item in prepared)
    )

    with SessionLocal() as db:
        with db.begin():
            keys = [item[2] for item in prepared]

            existing = db.scalar(
                select(Frame.frame_id)
                .where(Frame.image_storage_key.in_(keys))
                .limit(1)
            )

            if existing is not None:
                raise ValueError("Some images are already imported.")

            demo_user = User(
                display_name="Local video test",
                preferred_language="en",
                email=f"video-test-{uuid4().hex}@fixture.invalid",
                password_hash="!",
            )
            demo_device = Device(
                installation_id=str(uuid4()),
                device_name="Demo device record - downloaded video",
                platform="android",
            )

            db.add_all([demo_user, demo_device])
            db.flush()

            demo_session = Session(
                user_id=demo_user.user_id,
                device_id=demo_device.device_id,
                language_code="en",
                status="ended",
                stream_status="stopped",
                started_at=started_at,
                ended_at=imported_at,
                consented_at=started_at,
                consent_version="local-stock-test-fixture",
                frame_retention_seconds=3600,
                history_expires_at=imported_at + timedelta(days=1),
            )

            db.add(demo_session)
            db.flush()

            for entry, image_path, storage_key, offset in prepared:
                captured_at = started_at + timedelta(seconds=offset)

                db.add(Frame(
                    session_id=demo_session.session_id,
                    sequence_number=entry["source_frame_index"],
                    captured_at=captured_at,
                    received_at=imported_at,
                    image_storage_key=storage_key,
                    mime_type="image/jpeg",
                    width_px=entry["width_px"],
                    height_px=entry["height_px"],
                    size_bytes=image_path.stat().st_size,
                    sharpness_score=entry["sharpness_score"],
                    brightness_score=entry["brightness_score"],
                    novelty_score=entry["novelty_score"],
                    selection_reason=(
                        "first_frame"
                        if entry["novelty_score"] is None
                        else "visual_change"
                    ),
                    processing_status="pending",
                    processing_details={
                        "source": "downloaded_video_test",
                        "source_video": report["source_video"],
                        "video_timestamp_seconds": offset,
                        "timestamp_is_synthetic": True,
                        "quality_check": "passed",
                    },
                    expires_at=captured_at + timedelta(
                        seconds=demo_session.frame_retention_seconds
                    ),
                ))

            session_id = demo_session.session_id

    return session_id, len(prepared)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("report_path")
    args = parser.parse_args()

    session_id, count = import_video_frames(args.report_path)

    print("Demo session ID:", session_id)
    print("Frames saved to MySQL:", count)