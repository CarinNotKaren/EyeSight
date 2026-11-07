import argparse
from datetime import datetime, timezone
from uuid import uuid4

# Load PyTorch before Paddle to avoid the Windows DLL issue.
import torch

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from database.connection import SessionLocal
from database.models import Frame
from database.models import Session as CaptureSession


STAGE_NAMES = ("ocr", "object_detection", "image_embedding")


class FrameUnavailableError(Exception):
    pass


class FrameBusyError(Exception):
    pass


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def check_available(db, frame):
    if frame is None:
        raise FrameUnavailableError("Frame no longer exists.")

    session = db.get(CaptureSession, frame.session_id)

    if session is None:
        raise FrameUnavailableError("Frame session no longer exists.")

    now = utc_now()

    if frame.expires_at <= now or session.history_expires_at <= now:
        raise FrameUnavailableError("Frame or session has expired.")


def verify_available(frame_id):
    with SessionLocal() as db:
        check_available(db, db.get(Frame, frame_id))


def run_ocr(frame_id):
    from multimedia.ocr_storage import process_frame_ocr

    regions = process_frame_ocr(frame_id)
    return {"region_count": len(regions)}


def run_objects(frame_id):
    from multimedia.object_storage import process_frame_objects

    objects = process_frame_objects(frame_id)
    return {"object_count": len(objects)}


def run_embedding(frame_id):
    from multimedia.embedding_storage import process_frame_embedding

    dimensions = process_frame_embedding(frame_id)
    return {"dimensions": dimensions}


def record_progress(frame_id, run_id, outcomes, final_status=None):
    with SessionLocal() as db:
        with db.begin():
            frame = db.scalar(
                select(Frame)
                .where(Frame.frame_id == frame_id)
                .with_for_update()
            )
            check_available(db, frame)

            details = dict(frame.processing_details or {})
            pipeline = dict(details.get("pipeline") or {})

            if pipeline.get("run_id") != run_id:
                raise FrameBusyError("Pipeline ownership changed.")

            pipeline["stages"] = dict(outcomes)

            for name, outcome in outcomes.items():
                if outcome["status"] == "failed":
                    details[name] = dict(outcome)

            if final_status is not None:
                completed_at = utc_now()
                pipeline["completed_at_utc"] = completed_at.isoformat()
                frame.processing_status = final_status
                frame.processed_at = completed_at

            details["pipeline"] = pipeline
            frame.processing_details = details


def record_unavailable(frame_id, run_id, outcomes, reason):
    # Record only why processing stopped.
    # Do not run models, extend retention, or create missing rows.
    with SessionLocal() as db:
        with db.begin():
            frame = db.scalar(
                select(Frame)
                .where(Frame.frame_id == frame_id)
                .with_for_update()
            )

            if frame is None:
                return

            details = dict(frame.processing_details or {})
            pipeline = dict(details.get("pipeline") or {})

            # Do not alter another worker's processing state.
            if pipeline.get("run_id") != run_id:
                return

            stages = dict(outcomes)

            for name in STAGE_NAMES:
                if name not in stages:
                    stages[name] = {
                        "status": "skipped",
                        "reason": "frame_unavailable",
                    }
                    details[name] = dict(stages[name])
                elif stages[name]["status"] == "failed":
                    details[name] = dict(stages[name])

            stopped_at = utc_now()
            pipeline.update({
                "status": "aborted",
                "reason": reason,
                "stages": stages,
                "completed_at_utc": stopped_at.isoformat(),
            })

            details["pipeline"] = pipeline
            frame.processing_details = details

            # The database enum has no "expired" status.
            # The reason above distinguishes expiry from model failure.
            frame.processing_status = "failed"
            frame.processed_at = stopped_at


def process_frame(frame_id):
    run_id = uuid4().hex
    outcomes = {}

    try:
        with SessionLocal() as db:
            with db.begin():
                frame = db.scalar(
                    select(Frame)
                    .where(Frame.frame_id == frame_id)
                    .with_for_update()
                )
                check_available(db, frame)

                if frame.processing_status == "processing":
                    raise FrameBusyError(
                        "Frame is already being processed."
                    )

                details = dict(frame.processing_details or {})

                for name in STAGE_NAMES:
                    details[name] = {"status": "pending"}

                details["pipeline"] = {
                    "run_id": run_id,
                    "status": "processing",
                    "started_at_utc": utc_now().isoformat(),
                    "stages": {},
                }

                frame.processing_details = details
                frame.processing_status = "processing"
                frame.processed_at = None

        stages = (
            ("ocr", run_ocr),
            ("object_detection", run_objects),
            ("image_embedding", run_embedding),
        )

        for name, function in stages:
            verify_available(frame_id)
            print(f"Frame {frame_id}: starting {name}", flush=True)

            try:
                result = function(frame_id)
                outcomes[name] = {
                    "status": "completed",
                    **result,
                }

            except SQLAlchemyError:
                # Stop on database failures; progress cannot be trusted
                # until it can be saved.
                raise

            except Exception as error:
                # Check whether expiry/deletion caused the stage to stop.
                verify_available(frame_id)

                outcomes[name] = {
                    "status": "failed",
                    "error_type": type(error).__name__,
                }

                print(
                    f"Frame {frame_id}: {name} failed "
                    f"({type(error).__name__})",
                    flush=True,
                )

            record_progress(frame_id, run_id, outcomes)

        completed = sum(
            item["status"] == "completed"
            for item in outcomes.values()
        )

        if completed == len(stages):
            status = "ready"
        elif completed > 0:
            status = "partial"
        else:
            status = "failed"

        record_progress(
            frame_id,
            run_id,
            outcomes,
            final_status=status,
        )

        return {"status": status, "stages": outcomes}

    except FrameUnavailableError as error:
        reason = str(error)
        record_unavailable(frame_id, run_id, outcomes, reason)

        return {
            "status": "skipped",
            "reason": reason,
            "stages": outcomes,
        }

    except FrameBusyError as error:
        return {
            "status": "skipped",
            "reason": str(error),
        }


def main():
    parser = argparse.ArgumentParser(
        description="Run OCR, object detection, and image embeddings."
    )
    parser.add_argument("--session", type=int, required=True)
    args = parser.parse_args()

    try:
        with SessionLocal() as db:
            now = utc_now()

            frame_ids = db.scalars(
                select(Frame.frame_id)
                .join(
                    CaptureSession,
                    CaptureSession.session_id == Frame.session_id,
                )
                .where(
                    Frame.session_id == args.session,
                    Frame.expires_at > now,
                    CaptureSession.history_expires_at > now,
                )
                .order_by(Frame.sequence_number)
            ).all()

        if not frame_ids:
            print("No unexpired frames found for this session.")
            return

        for frame_id in frame_ids:
            result = process_frame(frame_id)
            print(f"Frame {frame_id}: {result}", flush=True)

    except SQLAlchemyError as error:
        print(
            f"Pipeline stopped because of a database error "
            f"({type(error).__name__}).",
            flush=True,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()