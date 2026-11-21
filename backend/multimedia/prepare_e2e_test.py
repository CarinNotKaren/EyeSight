
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import cv2
from sqlalchemy import select

from database.connection import SessionLocal
from database.models import User, Device, Session as CaptureSession, Frame
from multimedia.frame_quality import analyze_frame_quality


# Resolve the backend and image paths independently of the terminal's location.
BACKEND_DIR = Path(__file__).resolve().parents[1]
IMAGE_PATH = BACKEND_DIR / "storage" / "frames" / "e2e_test.jpg"

# This key is relative to the backend storage directory.
IMAGE_STORAGE_KEY = "frames/e2e_test.jpg"


def prepare_e2e_test():
    """Create a temporary user, device, active session, and pending test frame."""

    # Make sure the test image exists before touching the database.
    if not IMAGE_PATH.is_file():
        raise FileNotFoundError(f"Test image not found: {IMAGE_PATH}")

    # Load the image using OpenCV.
    image = cv2.imread(str(IMAGE_PATH))

    if image is None:
        raise ValueError("OpenCV could not read the test image.")

    # Calculate the image dimensions, sharpness, and brightness.
    quality = analyze_frame_quality(image)

    # Use the actual file size for the Frame record.
    image_size = IMAGE_PATH.stat().st_size

    # Use UTC timestamps to keep the test records consistent.
    now = datetime.now(timezone.utc)
    session_started_at = now - timedelta(seconds=2)
    captured_at = now - timedelta(seconds=1)

    with SessionLocal() as db:
        try:
            # Prevent a duplicate frame record if this script is run twice.
            existing_frame = db.scalar(
                select(Frame).where(
                    Frame.image_storage_key == IMAGE_STORAGE_KEY
                )
            )

            if existing_frame:
                raise ValueError(
                    f"A frame already uses {IMAGE_STORAGE_KEY}. "
                    "Do not create a duplicate test record."
                )

            # Create an isolated test user with a dummy, non-login password hash.
            test_user = User(
                display_name="EyeSight E2E Test User",
                email=f"eyesight-e2e-{uuid4().hex}@example.test",
                password_hash="e2e-test-only-not-a-real-password-hash",
                preferred_language="en",
            )
            db.add(test_user)
            db.flush()

            # Create a test device with a unique installation ID.
            test_device = Device(
                installation_id=str(uuid4()),
                device_name="EyeSight E2E Test Device",
                platform="android",
            )
            db.add(test_device)
            db.flush()

            # Create an active session because the question endpoint
            # only accepts questions belonging to active sessions.
            test_session = CaptureSession(
                user_id=test_user.user_id,
                device_id=test_device.device_id,
                language_code="en",
                status="active",
                stream_status="live",
                started_at=session_started_at,
                last_heartbeat_at=now,
                consented_at=session_started_at,
                consent_version="e2e-local-test",
                frame_retention_seconds=3600,
                history_expires_at=now + timedelta(days=1),
            )
            db.add(test_session)
            db.flush()

            # Register the image as a pending frame.
            # The existing frame pipeline will process it in the next step.
            test_frame = Frame(
                session_id=test_session.session_id,
                sequence_number=1,
                captured_at=captured_at,
                received_at=now,
                image_storage_key=IMAGE_STORAGE_KEY,
                mime_type="image/jpeg",
                width_px=quality["width_px"],
                height_px=quality["height_px"],
                size_bytes=image_size,
                sharpness_score=quality["sharpness_score"],
                brightness_score=quality["brightness_score"],

                # Required non-null field identifying how the frame was selected.
                selection_reason="manual_e2e_test",

                processing_status="pending",
                processing_details={
                    "source": "local_e2e_test",
                    "quality_analysis": "completed",
                },
                expires_at=captured_at + timedelta(seconds=3600),
            )
            db.add(test_frame)

            # Save all four related records together.
            db.commit()

            # Print the IDs needed for the next integration-test steps.
            print("\nE2E test data created successfully.")
            print(f"User ID:    {test_user.user_id}")
            print(f"Device ID:  {test_device.device_id}")
            print(f"Session ID: {test_session.session_id}")
            print(f"Frame ID:   {test_frame.frame_id}")
            print(f"Image:      {IMAGE_PATH}")
            print(
                f"Dimensions: {quality['width_px']} x "
                f"{quality['height_px']}"
            )
            print(f"Sharpness:  {quality['sharpness_score']:.2f}")
            print(f"Brightness: {quality['brightness_score']:.2f}")
            print(f"Status:     {test_frame.processing_status}")

        except Exception:
            # Roll back partial inserts if any step fails.
            db.rollback()
            raise


if __name__ == "__main__":
    prepare_e2e_test()
