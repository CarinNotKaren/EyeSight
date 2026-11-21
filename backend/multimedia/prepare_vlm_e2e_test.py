from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import cv2
from sqlalchemy import select

from database.connection import SessionLocal
from database.models import User, Device, Session as CaptureSession, Frame
from multimedia.frame_quality import analyze_frame_quality


# Resolve paths independently of the current terminal directory.
BACKEND_DIR = Path(__file__).resolve().parents[1]
IMAGE_PATH = BACKEND_DIR / "storage" / "frames" / "vlm_e2e_test_2.jpg"
IMAGE_STORAGE_KEY = "frames/vlm_e2e_test_2.jpg"


def prepare_vlm_e2e_test():
    """Create an isolated active session containing one VLM test frame."""

    # Ensure the copied test image exists.
    if not IMAGE_PATH.is_file():
        raise FileNotFoundError(f"Test image not found: {IMAGE_PATH}")

    # Read the image and calculate its quality metrics.
    image = cv2.imread(str(IMAGE_PATH))
    if image is None:
        raise ValueError("OpenCV could not read the test image.")

    quality = analyze_frame_quality(image)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    with SessionLocal() as db:
        try:
            # Avoid creating duplicate frame records.
            existing = db.scalar(
                select(Frame.frame_id).where(
                    Frame.image_storage_key == IMAGE_STORAGE_KEY
                )
            )
            if existing is not None:
                raise ValueError(
                    f"Frame already registered with ID {existing}."
                )

            # Create isolated test user and device records.
            test_user = User(
                display_name="EyeSight VLM E2E Test",
                email=f"vlm-e2e-{uuid4().hex}@example.test",
                password_hash="e2e-test-only-not-a-real-password-hash",
                preferred_language="en",
            )
            test_device = Device(
                installation_id=str(uuid4()),
                device_name="VLM E2E Test Device",
                platform="android",
            )

            db.add_all([test_user, test_device])
            db.flush()

            # Create an active session with valid retention periods.
            test_session = CaptureSession(
                user_id=test_user.user_id,
                device_id=test_device.device_id,
                language_code="en",
                status="active",
                stream_status="live",
                started_at=now - timedelta(seconds=2),
                last_heartbeat_at=now,
                consented_at=now - timedelta(seconds=2),
                consent_version="vlm-local-e2e-test",
                frame_retention_seconds=21600,
                history_expires_at=now + timedelta(days=1),
            )
            db.add(test_session)
            db.flush()

            # Register the copied image as pending for the existing pipeline.
            test_frame = Frame(
                session_id=test_session.session_id,
                sequence_number=1,
                captured_at=now - timedelta(seconds=1),
                received_at=now,
                image_storage_key=IMAGE_STORAGE_KEY,
                mime_type="image/jpeg",
                width_px=quality["width_px"],
                height_px=quality["height_px"],
                size_bytes=IMAGE_PATH.stat().st_size,
                sharpness_score=quality["sharpness_score"],
                brightness_score=quality["brightness_score"],
                selection_reason="manual_vlm_e2e_test",
                processing_status="pending",
                processing_details={
                    "source": "local_vlm_e2e_test",
                    "quality_analysis": "completed",
                },
                expires_at=now + timedelta(seconds=21600),
            )
            db.add(test_frame)
            db.commit()

            print("\nVLM test data created.")
            print("User ID:   ", test_user.user_id)
            print("Device ID: ", test_device.device_id)
            print("Session ID:", test_session.session_id)
            print("Frame ID:  ", test_frame.frame_id)
            print("Status:    ", test_frame.processing_status)

        except Exception:
            db.rollback()
            raise


if __name__ == "__main__":
    prepare_vlm_e2e_test()

