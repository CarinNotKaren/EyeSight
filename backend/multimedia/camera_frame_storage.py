from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
from sqlalchemy import func, select

from database.connection import SessionLocal
from database.models import Frame
from database.models import Session as CaptureSession
from multimedia.frame_quality import evaluate_frame_quality
from multimedia.frame_similarity import compare_frames


STORAGE_ROOT = Path(__file__).resolve().parents[1] / "storage"
FRAMES_ROOT = STORAGE_ROOT / "frames"


def read_previous_frame(storage_key: str) -> np.ndarray | None:
    """Read the previous frame if its file is still available."""
    try:
        image_path = (STORAGE_ROOT / storage_key).resolve()

        if not image_path.is_relative_to(FRAMES_ROOT.resolve()):
            return None

        image_bytes = image_path.read_bytes()
        if not image_bytes:
            return None

        return cv2.imdecode(
            np.frombuffer(image_bytes, dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
    except (OSError, RuntimeError, ValueError, cv2.error):
        return None


def save_camera_frame(
    session_id: int,
    image_bytes: bytes,
    *,
    select_for_history: bool = False,
) -> int | None:
    """Return a saved frame ID, or None if history selection skips the image."""
    if type(session_id) is not int or session_id <= 0:
        raise ValueError("Session ID must be a positive integer.")

    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise ValueError("Image bytes are required.")

    if image_bytes.startswith(b"\xff\xd8\xff"):
        extension, mime_type = ".jpg", "image/jpeg"
    elif image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        extension, mime_type = ".png", "image/png"
    else:
        raise ValueError("Camera image must be JPEG or PNG.")

    try:
        image = cv2.imdecode(
            np.frombuffer(image_bytes, dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
    except cv2.error as error:
        raise ValueError("Could not decode the camera image.") from error

    if image is None:
        raise ValueError("Could not decode the camera image.")

    quality = evaluate_frame_quality(image)
    saved_path = None
    commit_started = False

    try:
        with SessionLocal() as db:
            with db.begin():
                # Compare and save under the same lock for each session.
                session = db.scalar(
                    select(CaptureSession)
                    .where(CaptureSession.session_id == session_id)
                    .with_for_update()
                )
                now = datetime.now(timezone.utc).replace(tzinfo=None)

                if session is None:
                    raise ValueError("Capture session does not exist.")
                if session.status != "active":
                    raise ValueError("Capture session must be active.")
                if session.history_expires_at <= now:
                    raise ValueError("Capture session history has expired.")

                novelty_score = None

                if select_for_history:
                    if not quality["passes_quality_check"]:
                        return None

                    previous_key = db.scalar(
                        select(Frame.image_storage_key)
                        .where(
                            Frame.session_id == session_id,
                            Frame.expires_at > now,
                            Frame.image_storage_key.like(
                                f"frames/camera/{session_id}/%"
                            ),
                        )
                        .order_by(Frame.sequence_number.desc())
                        .limit(1)
                    )

                    if previous_key is not None:
                        previous_image = read_previous_frame(previous_key)

                        if previous_image is not None:
                            comparison = compare_frames(image, previous_image)
                            novelty_score = comparison["novelty_score"]

                            if comparison["is_duplicate"]:
                                return None

                expires_at = min(
                    now + timedelta(seconds=session.frame_retention_seconds),
                    session.history_expires_at,
                )

                last_sequence = db.scalar(
                    select(func.max(Frame.sequence_number))
                    .where(Frame.session_id == session_id)
                )
                sequence_number = (
                    0 if last_sequence is None else last_sequence + 1
                )

                filename = f"{uuid4().hex}{extension}"
                relative_path = Path("camera") / str(session_id) / filename
                image_path = FRAMES_ROOT / relative_path
                image_path.parent.mkdir(parents=True, exist_ok=True)

                with image_path.open("xb") as destination:
                    saved_path = image_path
                    destination.write(image_bytes)

                frame = Frame(
                    session_id=session_id,
                    sequence_number=sequence_number,
                    captured_at=now,
                    received_at=now,
                    image_storage_key=(Path("frames") / relative_path).as_posix(),
                    mime_type=mime_type,
                    width_px=quality["width_px"],
                    height_px=quality["height_px"],
                    size_bytes=len(image_bytes),
                    sharpness_score=quality["sharpness_score"],
                    brightness_score=quality["brightness_score"],
                    novelty_score=novelty_score,
                    selection_reason=(
                        "camera_history" if select_for_history else "camera_upload"
                    ),
                    processing_status="pending",
                    processing_details={"source": "camera_upload"},
                    expires_at=expires_at,
                )
                db.add(frame)
                db.flush()
                frame_id = frame.frame_id

                # Keep the file if a failed commit leaves its outcome uncertain.
                commit_started = True

    except Exception:
        if saved_path is not None and not commit_started:
            saved_path.unlink(missing_ok=True)
        raise

    return frame_id