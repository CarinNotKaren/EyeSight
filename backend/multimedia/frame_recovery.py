import argparse
from datetime import datetime, timezone

from sqlalchemy import select

from database.connection import SessionLocal
from database.models import Frame
from database.models import Session as CaptureSession


STAGE_NAMES = ("ocr", "object_detection", "image_embedding")


def recover_frame(frame_id, expected_run_id, *, apply=False):
    """Recover a run after its processing worker has been stopped."""
    if type(frame_id) is not int or frame_id <= 0:
        raise ValueError("Frame ID must be a positive integer.")

    if not isinstance(expected_run_id, str) or not expected_run_id.strip():
        raise ValueError("The expected pipeline run ID is required.")

    with SessionLocal() as db:
        with db.begin():
            frame = db.scalar(
                select(Frame)
                .where(Frame.frame_id == frame_id)
                .with_for_update()
            )

            if frame is None:
                raise ValueError("Frame does not exist.")

            session = db.scalar(
                select(CaptureSession)
                .where(CaptureSession.session_id == frame.session_id)
                .with_for_update()
            )

            now = datetime.now(timezone.utc).replace(tzinfo=None)

            if session is None:
                raise ValueError("Capture session does not exist.")

            if frame.expires_at <= now or session.history_expires_at <= now:
                raise ValueError(
                    "Frame or session has expired. Use retention cleanup."
                )

            if frame.processing_status != "processing":
                raise ValueError("Frame is no longer marked processing.")

            details = dict(frame.processing_details or {})
            pipeline = dict(details.get("pipeline") or {})

            if pipeline.get("run_id") != expected_run_id:
                raise ValueError(
                    "Pipeline run ID changed. Inspect the frame again."
                )

            result = {
                "frame_id": frame.frame_id,
                "session_id": frame.session_id,
                "run_id": expected_run_id,
                "action": "recovered" if apply else "preview",
            }

            if not apply:
                return result

            stages = {}

            for name in STAGE_NAMES:
                stage = dict(details.get(name) or {})

                if stage.get("status") != "completed":
                    stage = {
                        "status": "skipped",
                        "reason": "worker_stopped",
                    }
                    details[name] = stage

                stages[name] = stage

            pipeline.update({
                "status": "failed",
                "reason": "manual_recovery_after_worker_stop",
                "stages": stages,
                "completed_at_utc": now.isoformat(),
            })

            details["pipeline"] = pipeline
            frame.processing_details = details
            frame.processing_status = "failed"
            frame.processed_at = now

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Recover one frame after its processing worker has stopped."
    )
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--workers-stopped",
        action="store_true",
        help="Confirm that processing workers for this frame have stopped.",
    )
    args = parser.parse_args()

    if args.apply and not args.workers_stopped:
        parser.error(
            "--apply requires --workers-stopped. Stop the processing "
            "workers before recovering a frame."
        )

    try:
        result = recover_frame(
            args.frame,
            args.run_id,
            apply=args.apply,
        )
    except ValueError as error:
        parser.error(str(error))

    print(result)

    if args.apply:
        print("Recovery saved. The frame can now be retried.")
    else:
        print("Preview completed. No recovery changes were saved.")


if __name__ == "__main__":
    main()