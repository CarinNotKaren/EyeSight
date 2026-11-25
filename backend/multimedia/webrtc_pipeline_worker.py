"""Process pending WebRTC frames using Member 2's existing pipeline."""

import argparse
from sqlalchemy import select

from database.connection import SessionLocal
from database.models.frame import Frame
from database.models.session import Session as CaptureSession
from multimedia.frame_pipeline import process_frame, utc_now


def process_pending_session_frames(session_id: int) -> int:
    """Process pending frames until the session has no remaining pending rows."""
    processed_count = 0
    while True:
        with SessionLocal() as db:
            now = utc_now()
            frame_ids = db.scalars(
                select(Frame.frame_id)
                .join(CaptureSession, CaptureSession.session_id == Frame.session_id)
                .where(
                    Frame.session_id == session_id,
                    Frame.processing_status == "pending",
                    Frame.expires_at > now,
                    CaptureSession.status == "active",
                    CaptureSession.history_expires_at > now,
                )
                .order_by(Frame.sequence_number)
            ).all()
        if not frame_ids:
            return processed_count
        for frame_id in frame_ids:
            result = process_frame(frame_id)
            if result and result.get("status") in ("ready", "partial", "failed"):
                processed_count += 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process pending EyeSight frames for one live WebRTC session."
    )
    parser.add_argument("--session", type=int, required=True)
    args = parser.parse_args()
    process_pending_session_frames(args.session)


if __name__ == "__main__":
    main()
