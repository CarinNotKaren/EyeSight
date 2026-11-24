
"""Local WebRTC media integration test using a synthetic camera."""

import asyncio

import av
import cv2
import numpy as np
import pytest
from aiortc import RTCConfiguration, RTCPeerConnection, VideoStreamTrack

import multimedia.webrtc_receiver as receiver_module
from multimedia.webrtc_receiver import WebRTCReceiver


class SyntheticVideoTrack(VideoStreamTrack):
    """Generate video frames to simulate a mobile camera."""

    async def recv(self):
        # Use aiortc's timestamp helper to produce correctly paced video.
        pts, time_base = await self.next_timestamp()

        # Generate a simple 320x240 image.
        image = np.zeros((240, 320, 3), dtype=np.uint8)
        image[:, :, 1] = 180

        # Convert the image into a PyAV video frame.
        frame = av.VideoFrame.from_ndarray(image, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame


def test_webrtc_receives_video_and_publishes_preview(monkeypatch):
    """Verify local negotiation, video reception, preview and frame sampling."""

    async def run_test():
        receiver = WebRTCReceiver()
        sender = RTCPeerConnection(
            configuration=RTCConfiguration(iceServers=[])
        )

        # Keep this test independent of external STUN/TURN servers.
        monkeypatch.setattr(
            receiver_module,
            "build_rtc_configuration",
            lambda: RTCConfiguration(iceServers=[]),
        )

        # Replace database storage with a predictable test function.
        monkeypatch.setattr(
            receiver_module,
            "save_camera_frame",
            lambda session_id, image_bytes, *, select_for_history=False: 123,
        )

        # Sample the first received frame immediately.
        monkeypatch.setattr(
            receiver_module,
            "FRAME_SAMPLE_INTERVAL_SECONDS",
            0.0,
        )

        # Do not launch the real image-processing subprocess during this test.
        monkeypatch.setattr(
            receiver,
            "_schedule_frame_processing",
            lambda session_id: None,
        )

        state = None
        viewer_queue = None

        try:
            # Create the backend receiver and dashboard viewer.
            state = await receiver.create_stream(
                session_id=999999,
                owner_user_id=1,
            )
            viewer_queue = await receiver.add_viewer(999999)

            # Simulate the mobile device sending its camera video.
            sender.addTrack(SyntheticVideoTrack())

            # Negotiate the WebRTC connection.
            offer = await sender.createOffer()
            await sender.setLocalDescription(offer)

            await state.peer.setRemoteDescription(sender.localDescription)

            answer = await state.peer.createAnswer()
            await state.peer.setLocalDescription(answer)

            await sender.setRemoteDescription(state.peer.localDescription)

            # Wait until the dashboard receives an actual JPEG preview.
            jpeg_bytes = await asyncio.wait_for(
                viewer_queue.get(),
                timeout=15,
            )

            assert isinstance(jpeg_bytes, bytes)
            assert jpeg_bytes.startswith(b"\xff\xd8")

            # Wait until at least one frame has been accepted for storage.
            async def wait_for_saved_frame():
                while state.saved_frames == 0:
                    await asyncio.sleep(0.05)

            await asyncio.wait_for(wait_for_saved_frame(), timeout=10)

            # Verify that the JPEG can be decoded into an OpenCV image.
            decoded_image = cv2.imdecode(
                np.frombuffer(jpeg_bytes, dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )

            assert decoded_image is not None
            assert decoded_image.shape[:2] == (240, 320)
            assert state.received_frames > 0
            assert state.saved_frames > 0
            assert state.last_frame_id == 123

        finally:
            # Clean up both peers even if an assertion fails.
            if viewer_queue is not None:
                await receiver.remove_viewer(999999, viewer_queue)

            await receiver.close_all()
            await sender.close()

    asyncio.run(run_test())
