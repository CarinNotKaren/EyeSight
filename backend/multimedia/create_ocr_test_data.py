import argparse
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

import cv2
from sqlalchemy import select

from database.connection import SessionLocal
from database.models import User, Device, Session, Frame
from multimedia.frame_quality import analyze_frame_quality


STORAGE_ROOT = Path(__file__).resolve().parents[1] / "storage"
FRAMES_ROOT = STORAGE_ROOT / "frames"


def create_ocr_test_data(*, multilingual=False, source_dir=None):
    """Create local test fixtures without changing existing records."""
    prepared = []

    if multilingual:
        source_root = (
            Path(source_dir)
            if source_dir is not None
            else Path(gettempdir()) / "eyesight-ocr-language-tests"
        )

        sources = [
            ("en", source_root / "en.png"),
            ("fr", source_root / "fr.png"),
            ("ar", source_root / "ar.png"),
        ]
    else:
        sources = [
            ("en", FRAMES_ROOT / "quality_test.png"),
            ("en", FRAMES_ROOT / "ocr_plain.png"),
        ]

    # Validate every source before creating files or database records.
    for language, image_path in sources:
        if not image_path.is_file():
            raise FileNotFoundError(f"Missing test image: {image_path}")

        image = cv2.imread(str(image_path))

        if image is None:
            raise ValueError(f"Could not read test image: {image_path}")

        quality = analyze_frame_quality(image)

        prepared.append({
            "language": language,
            "image_path": image_path,
            "quality": quality,
        })

    if multilingual:
        # Each run gets its own image copies and storage keys.
        destination = (
            FRAMES_ROOT / f"ocr_languages_{uuid4().hex}"
        )
        destination.mkdir(parents=True, exist_ok=False)

        for item in prepared:
            copied_path = destination / item["image_path"].name
            shutil.copyfile(item["image_path"], copied_path)
            item["image_path"] = copied_path

    for item in prepared:
        item["storage_key"] = (
            item["image_path"]
            .relative_to(STORAGE_ROOT)
            .as_posix()
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    created = []
    session_summaries = []

    with SessionLocal() as db:
        with db.begin():
            keys = [item["storage_key"] for item in prepared]

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
                email=f"ocr-test-{uuid4().hex}@fixture.invalid",
                password_hash="!",
            )

            device = Device(
                installation_id=str(uuid4()),
                device_name="Static-image test fixture",
                platform="android",
            )

            db.add_all([user, device])
            db.flush()

            languages = list(dict.fromkeys(
                item["language"] for item in prepared
            ))

            for language in languages:
                # Separate sessions let the pipeline select each
                # session's configured OCR language automatically.
                session = Session(
                    user_id=user.user_id,
                    device_id=device.device_id,
                    language_code=language,
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

                language_images = [
                    item
                    for item in prepared
                    if item["language"] == language
                ]

                session_summaries.append(
                    (session.session_id, language)
                )

                for index, item in enumerate(language_images):
                    image_path = item["image_path"]
                    quality = item["quality"]

                    frame = Frame(
                        session_id=session.session_id,
                        sequence_number=index,
                        captured_at=now,
                        received_at=now,
                        image_storage_key=item["storage_key"],
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
                            "fixture_language": language,
                        },
                        expires_at=now + timedelta(hours=1),
                    )

                    db.add(frame)
                    db.flush()

                    created.append(
                        (frame.frame_id, image_path.name)
                    )

    # Report only after the transaction commits successfully.
    for session_id, language in session_summaries:
        print(f"Session ID {session_id}: language={language}")

    return created


def main():
    parser = argparse.ArgumentParser(
        description="Create local OCR test frames and sessions."
    )

    parser.add_argument(
        "--multilingual",
        action="store_true",
        help="Import en.png, fr.png, and ar.png into separate sessions.",
    )

    parser.add_argument(
        "--source-dir",
        type=Path,
        help="Folder containing the three multilingual test images.",
    )

    args = parser.parse_args()

    if args.source_dir is not None and not args.multilingual:
        parser.error("--source-dir requires --multilingual.")

    created = create_ocr_test_data(
        multilingual=args.multilingual,
        source_dir=args.source_dir,
    )

    for frame_id, filename in created:
        print(f"Frame ID {frame_id}: {filename}")


if __name__ == "__main__":
    main()