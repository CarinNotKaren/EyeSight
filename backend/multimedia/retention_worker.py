import argparse
import math
from threading import Event

from sqlalchemy.exc import SQLAlchemyError

from multimedia.retention_cleanup import cleanup_expired_frames


def run_worker(interval_seconds=60, session_id=None, limit=100):
    stop_event = Event()

    print(
        f"Retention worker started. "
        f"Checking every {interval_seconds:g} seconds.",
        flush=True,
    )
    print("Press Ctrl+C to stop.", flush=True)

    try:
        while not stop_event.is_set():
            try:
                cleanup_expired_frames(
                    session_id=session_id,
                    limit=limit,
                )
            except SQLAlchemyError as error:
                # A temporary database failure should not stop the worker.
                print(
                    f"Cleanup database error: {type(error).__name__}. "
                    "Will retry on the next cycle.",
                    flush=True,
                )

            stop_event.wait(interval_seconds)

    except KeyboardInterrupt:
        print("\nRetention worker stopped.", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Periodically delete expired frame files and records."
    )
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--session", type=int)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error("--interval must be a positive, finite number.")

    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000.")

    run_worker(
        interval_seconds=args.interval,
        session_id=args.session,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()