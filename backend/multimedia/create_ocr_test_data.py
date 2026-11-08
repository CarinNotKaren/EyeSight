from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import cv2
from sqlalchemy import select

from database.connection import SessionLocal
from database.models import User, Device, Session, Frame
from multimedia.frame_quality import analyze_frame_quality


def create_ocr_test_data():
    storage = Path(__file__).resolve().parents[1] / "storage"
    prepared = []

    for filename in ("quality_test.png", "ocr_plain.png"):
        image_path = storage / "frames" / filename
        image = cv2.imread(str(image_path))
        quality = analyze_frame_quality(image)

        prepared.append((
            image_path,
            f"frames/{filename}",
            quality,
        ))

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    with SessionLocal() as db:
        with db.begin():
            keys = [item[1] for item in prepared]

            existing = db.scalar(
                select(Frame.frame_id)
                .where(Frame.image_storage_key.in_(keys))
                .limit(1)
            )

            if existing is not None:
                raise ValueError(
                    "These test images already have database records."
                )

            user = User(
                display_name="OCR local test",
                preferred_language="en",
            )
            device = Device(
                installation_id=str(uuid4()),
                device_name="Static-image test fixture",
                platform="android",
            )

            db.add_all([user, device])
            db.flush()

            session = Session(
                user_id=user.user_id,
                device_id=device.device_id,
                language_code="en",
                status="ended",
                stream_status="stopped",
                started_at=now,
                ended_at=now,
                consented_at=now,
                consent_version="local-static-test-fixture",
                frame_retention_seconds=3600,
                history_expires_at=now + timedelta(days=1),
            )

            db.add(session)
            db.flush()

            created = []

            for index, (image_path, storage_key, quality) in enumerate(prepared):
                frame = Frame(
                    session_id=session.session_id,
                    sequence_number=index,
                    captured_at=now,
                    received_at=now,
                    image_storage_key=storage_key,
                    mime_type="image/png",
                    width_px=quality["width_px"],
                    height_px=quality["height_px"],
                    size_bytes=image_path.stat().st_size,
                    sharpness_score=quality["sharpness_score"],
                    brightness_score=quality["brightness_score"],
                    novelty_score=None,
                    selection_reason="ocr_test_fixture",
                    processing_status="pending",
                    processing_details={
                        "source": "static_image_test",
                        "timestamp_is_synthetic": True,
                    },
                    expires_at=now + timedelta(hours=1),
                )

                db.add(frame)
                db.flush()

                created.append((frame.frame_id, image_path.name))

    return created


if __name__ == "__main__":
    for frame_id, filename in create_ocr_test_data():
        print(f"Frame ID {frame_id}: {filename}")