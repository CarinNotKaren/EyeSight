"""Server-side WebRTC receiver for live EyeSight camera streams."""
import subprocess
import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

import cv2
from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer
from aiortc.sdp import candidate_from_sdp

from multimedia.camera_frame_storage import save_camera_frame
from database.connection import SessionLocal
from database.models.frame import Frame

logger = logging.getLogger(__name__)

# Keep a bounded number of active peer connections per backend process.
MAX_ACTIVE_STREAMS = int(os.getenv("WEBRTC_MAX_ACTIVE_STREAMS", "8"))
# Sample history at a controlled rate rather than storing every video frame.
FRAME_SAMPLE_INTERVAL_SECONDS = float(os.getenv("WEBRTC_FRAME_SAMPLE_INTERVAL_SECONDS", "1.0"))
MAX_FRAME_WIDTH = int(os.getenv("WEBRTC_MAX_FRAME_WIDTH", "1280"))
JPEG_QUALITY = int(os.getenv("WEBRTC_JPEG_QUALITY", "85"))


def build_rtc_configuration() -> RTCConfiguration:
    """Build STUN/TURN configuration from backend environment settings."""
    ice_servers = []
    stun_url = os.getenv("WEBRTC_STUN_URL", "stun:stun.l.google.com:19302")
    if stun_url:
        ice_servers.append(RTCIceServer(urls=stun_url))

    turn_url = os.getenv("WEBRTC_TURN_URL")
    if turn_url:
        ice_servers.append(
            RTCIceServer(
                urls=turn_url,
                username=os.getenv("WEBRTC_TURN_USERNAME"),
                credential=os.getenv("WEBRTC_TURN_CREDENTIAL"),
            )
        )
    return RTCConfiguration(iceServers=ice_servers)


@dataclass
class StreamState:
    """Runtime state for one authenticated capture session."""

    session_id: int
    owner_user_id: int
    peer: RTCPeerConnection
    connected_at: float = field(default_factory=time.monotonic)
    last_saved_at: float = 0.0
    last_frame_id: int | None = None
    last_frame_at: float | None = None
    latest_jpeg: bytes | None = None
    received_frames: int = 0
    saved_frames: int = 0
    frame_task: asyncio.Task | None = None
    closed: bool = False


class WebRTCReceiver:
    """Manage inbound peers and publish decoded previews to dashboard viewers."""

    def __init__(self) -> None:
        self._streams: dict[int, StreamState] = {}
        self._viewers: dict[int, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self._pipeline_tasks: dict[int, asyncio.Task] = {}

    async def create_stream(self, session_id: int, owner_user_id: int) -> StreamState:
        async with self._lock:
            existing = self._streams.get(session_id)
            if existing and not existing.closed:
                raise ValueError("A WebRTC stream is already connected to this session.")
            if len(self._streams) >= MAX_ACTIVE_STREAMS:
                raise RuntimeError("The server has reached its active stream limit.")

            peer = RTCPeerConnection(configuration=build_rtc_configuration())
            state = StreamState(session_id, owner_user_id, peer)
            self._streams[session_id] = state

            @peer.on("track")
            def on_track(track):
                if track.kind == "video":
                    state.frame_task = asyncio.create_task(self._receive_video(state, track))

            @peer.on("connectionstatechange")
            async def on_connection_state_change():
                logger.info("WebRTC session %s connection state: %s", session_id, peer.connectionState)
                if peer.connectionState in ("failed", "closed"):
                    await self.close_stream(session_id)

            @peer.on("iceconnectionstatechange")
            async def on_ice_state_change():
                logger.info("WebRTC session %s ICE state: %s", session_id, peer.iceConnectionState)
                if peer.iceConnectionState == "failed":
                    await self.close_stream(session_id)

            return state

    async def _receive_video(self, state: StreamState, track: Any) -> None:
        """Decode video, publish a dashboard preview, and sample history frames."""
        try:
            while not state.closed:
                video_frame = await track.recv()
                state.received_frames += 1

                # Convert PyAV's decoded frame into OpenCV's BGR image format.
                image = video_frame.to_ndarray(format="bgr24")
                if image is None or image.size == 0:
                    continue

                height, width = image.shape[:2]
                if width > MAX_FRAME_WIDTH:
                    new_height = max(1, int(height * MAX_FRAME_WIDTH / width))
                    image = cv2.resize(image, (MAX_FRAME_WIDTH, new_height))

                encoded_ok, encoded = cv2.imencode(
                    ".jpg",
                    image,
                    [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
                )
                if not encoded_ok:
                    continue

                jpeg_bytes = encoded.tobytes()
                state.latest_jpeg = jpeg_bytes
                state.last_frame_at = time.time()
                self._publish_preview(state.session_id, jpeg_bytes)

                now = time.monotonic()
                if now - state.last_saved_at < FRAME_SAMPLE_INTERVAL_SECONDS:
                    continue

                                # Run synchronous database, image-processing and file operations
                # in a worker thread to keep the WebRTC event loop responsive.
                frame_id = await asyncio.to_thread(
                    save_camera_frame,
                    state.session_id,
                    jpeg_bytes,
                    select_for_history=True,
                )
                
                state.last_saved_at = now
                if frame_id is not None:
                    state.last_frame_id = frame_id
                    state.saved_frames += 1
                    logger.info("Saved WebRTC frame %s for session %s", frame_id, state.session_id)
                    self._schedule_frame_processing(state.session_id)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Video receiver failed for session %s", state.session_id)
            await self.close_stream(state.session_id)

    def _publish_preview(self, session_id: int, jpeg_bytes: bytes) -> None:
        """Fan out the newest JPEG without building an unbounded viewer queue."""
        for queue in tuple(self._viewers.get(session_id, set())):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(jpeg_bytes)
            except asyncio.QueueFull:
                pass

    async def add_viewer(self, session_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._viewers.setdefault(session_id, set()).add(queue)
        state = self._streams.get(session_id)
        if state and state.latest_jpeg:
            queue.put_nowait(state.latest_jpeg)
        return queue

    async def remove_viewer(self, session_id: int, queue: asyncio.Queue) -> None:
        viewers = self._viewers.get(session_id)
        if viewers:
            viewers.discard(queue)
            if not viewers:
                self._viewers.pop(session_id, None)

    def get_stream(self, session_id: int) -> StreamState | None:
        return self._streams.get(session_id)


    def _has_pending_frames(self, session_id: int) -> bool:
        """Check whether this session has frames waiting for Member 2's pipeline."""
        with SessionLocal() as db:
            return db.query(Frame.frame_id).filter(
                Frame.session_id == session_id,
                Frame.processing_status == "pending",
            ).first() is not None

    def _schedule_frame_processing(self, session_id: int) -> None:
        """Run the synchronous ML pipeline in a child process, not the media loop."""
        current = self._pipeline_tasks.get(session_id)
        if current and not current.done():
            return
        task = asyncio.create_task(self._run_frame_pipeline(session_id))
        self._pipeline_tasks[session_id] = task
        task.add_done_callback(
            lambda completed: asyncio.create_task(
                self._restart_if_pending(session_id, completed)
            )
        )

    async def _run_frame_pipeline(self, session_id: int) -> bool:
        """Start the pending-frame worker as a separate Python process."""
        backend_dir = Path(__file__).resolve().parents[1]

        # Launch the worker without using asyncio's unsupported Windows
        # subprocess transport.
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "multimedia.webrtc_pipeline_worker",
                "--session",
                str(session_id),
            ],
            cwd=str(backend_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Check periodically without blocking the FastAPI event loop.
        while process.poll() is None:
            await asyncio.sleep(0.1)

        return_code = process.returncode

        if return_code != 0:
            logger.error(
                "Frame worker exited with code %s for session %s",
                return_code,
                session_id,
            )
            return False

        return True

    async def _restart_if_pending(self, session_id: int, completed: asyncio.Task) -> None:
        """Catch frames saved just as a previous worker was exiting."""
        if self._pipeline_tasks.get(session_id) is completed:
            self._pipeline_tasks.pop(session_id, None)
        if completed.cancelled():
            return
        try:
            succeeded = completed.result()
        except Exception:
            logger.exception("Frame worker failed for session %s", session_id)
            return
        if not succeeded:
            return
        try:
            if self._has_pending_frames(session_id) and session_id in self._streams:
                self._schedule_frame_processing(session_id)
        except Exception:
            logger.exception("Could not check pending frames for session %s", session_id)

    async def add_ice_candidate(self, session_id: int, payload: dict) -> None:
        """Apply a trickled ICE candidate from the mobile peer."""
        state = self._streams.get(session_id)
        if state is None or state.closed:
            raise ValueError("No active WebRTC connection exists for this session.")

        candidate_text = payload.get("candidate")
        if not candidate_text:
            await state.peer.addIceCandidate(None)
            return

        candidate = candidate_from_sdp(candidate_text.split(":", 1)[-1])
        candidate.sdpMid = payload.get("sdpMid")
        candidate.sdpMLineIndex = payload.get("sdpMLineIndex")
        await state.peer.addIceCandidate(candidate)

    async def close_stream(self, session_id: int) -> None:
        async with self._lock:
            state = self._streams.pop(session_id, None)
            if state is None or state.closed:
                return
            state.closed = True

        current_task = asyncio.current_task()
        if state.frame_task and state.frame_task is not current_task:
            state.frame_task.cancel()
            try:
                await state.frame_task
            except (asyncio.CancelledError, Exception):
                pass

        await state.peer.close()
        state.latest_jpeg = None

    async def close_all(self) -> None:
        for session_id in list(self._streams):
            await self.close_stream(session_id)


# Shared process-local manager used by signaling and dashboard routes.
webrtc_receiver = WebRTCReceiver()
