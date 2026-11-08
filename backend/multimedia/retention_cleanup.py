import argparse
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import SQLAlchemyError

from database.connection import SessionLocal
from database.models import Frame
from database.models import Session as CaptureSession


STORAGE_ROOT = (
    Path(__file__).resolve().parents[1] / "storage"
).resolve()
FRAMES_ROOT = (STORAGE_ROOT / "frames").resolve()


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_image_path(storage_key):
    path = (STORAGE_ROOT / storage_key).resolve()

    if not path.is_relative_to(FRAMES_ROOT) or path == FRAMES_ROOT:
        raise ValueError("Image path must be inside storage/frames.")

    if path.exists() and not path.is_file():
        raise ValueError("Image path is not a file.")

    return path


def get_preview_paths(image_path):
    """Return known preview paths belonging to this image."""
    previews = []

    for suffix in ("_ocr_preview.jpg", "_detection_preview.jpg"):
        candidate = image_path.with_name(image_path.stem + suffix)
        relative_key = candidate.relative_to(STORAGE_ROOT)
        previews.append(get_image_path(str(relative_key)))

    return previews


def expired_frames_statement(session_id=None):
    now = utc_now()

    statement = (
        select(Frame, CaptureSession.history_expires_at)
        .join(
            CaptureSession,
            CaptureSession.session_id == Frame.session_id,
        )
        .where(
            or_(
                Frame.expires_at <= now,
                CaptureSession.history_expires_at <= now,
            )
        )
        .order_by(Frame.frame_id)
    )

    if session_id is not None:
        statement = statement.where(
            Frame.session_id == session_id
        )

    return statement


def preview_expired_frames(session_id=None, limit=100):
    statement = expired_frames_statement(session_id).limit(limit)

    with SessionLocal() as db:
        rows = db.execute(statement).all()

        print("PREVIEW ONLY - nothing will be deleted.")
        print(f"Checked at UTC: {utc_now().isoformat()}")
        print(f"Expired frames listed: {len(rows)} (limit {limit})")

        for frame, history_expires_at in rows:
            preview_files = []

            try:
                path = get_image_path(frame.image_storage_key)
                preview_files = [
                    preview
                    for preview in get_preview_paths(path)
                    if preview.is_file()
                ]

                file_status = (
                    "image file exists"
                    if path.is_file()
                    else "image file already missing"
                )

            except (OSError, ValueError, RuntimeError) as error:
                file_status = f"BLOCKED: {error}"

            reason = (
                "session history expired"
                if history_expires_at <= utc_now()
                else "frame retention expired"
            )

            print(
                f"Frame {frame.frame_id} "
                f"| session {frame.session_id} "
                f"| {reason} "
                f"| {file_status} "
                f"| {frame.image_storage_key}"
            )

            for preview in preview_files:
                print(f"  Preview would be deleted: {preview}")


def cleanup_expired_frames(session_id=None, limit=100):
    statement = expired_frames_statement(session_id).limit(limit)

    with SessionLocal() as db:
        rows = db.execute(statement).all()
        frame_ids = [frame.frame_id for frame, _ in rows]

    deleted_count = 0
    failed_count = 0
    skipped_count = 0

    for frame_id in frame_ids:
        try:
            with SessionLocal() as db:
                with db.begin():
                    frame = db.scalar(
                        select(Frame)
                        .where(Frame.frame_id == frame_id)
                        .with_for_update()
                    )

                    if frame is None:
                        skipped_count += 1
                        continue

                    session = db.scalar(
                        select(CaptureSession)
                        .where(
                            CaptureSession.session_id
                            == frame.session_id
                        )
                        .with_for_update()
                    )

                    if session is None:
                        raise ValueError("Frame session is missing.")

                    # Recheck expiry immediately before deletion.
                    now = utc_now()

                    if (
                        frame.expires_at > now
                        and session.history_expires_at > now
                    ):
                        skipped_count += 1
                        continue

                    # Validate all paths before deleting anything.
                    path = get_image_path(frame.image_storage_key)
                    previews = get_preview_paths(path)

                    # Do not delete a preview that is independently
                    # registered as another frame's original image.
                    preview_keys = [
                        preview.relative_to(STORAGE_ROOT).as_posix()
                        for preview in previews
                    ]
                    registered_preview = db.scalar(
                        select(Frame.frame_id)
                        .where(
                            Frame.image_storage_key.in_(preview_keys)
                        )
                        .limit(1)
                    )

                    if registered_preview is not None:
                        raise ValueError(
                            "A preview path is registered as a frame."
                        )

                    # Remove previews before the original image.
                    # Missing files are acceptable on a retry.
                    for preview in previews:
                        preview.unlink(missing_ok=True)

                    path.unlink(missing_ok=True)

                    # MySQL cascades deletion to linked frame results.
                    # If commit fails, the frame row remains for retry.
                    db.execute(
                        delete(Frame).where(
                            Frame.frame_id == frame_id
                        )
                    )

            deleted_count += 1
            print(
                f"Deleted expired frame {frame_id}, "
                "its known previews, and linked data."
            )

        except (
            OSError,
            ValueError,
            RuntimeError,
            SQLAlchemyError,
        ) as error:
            failed_count += 1
            print(
                f"Frame {frame_id}: cleanup failed: {error}"
            )

    print(
        f"Cleanup finished: deleted={deleted_count}, "
        f"failed={failed_count}, skipped={skipped_count}"
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Preview or delete expired frames, "
            "known previews, and linked records."
        )
    )
    parser.add_argument("--session", type=int)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000.")

    if args.apply:
        cleanup_expired_frames(args.session, args.limit)
    else:
        preview_expired_frames(args.session, args.limit)


if __name__ == "__main__":
    main()