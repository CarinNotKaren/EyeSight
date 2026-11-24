"""Authenticated WebRTC signaling and dashboard preview endpoints."""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from aiortc import RTCSessionDescription
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketState

from database.dependencies import get_db
from database.models.session import Session as CaptureSession
from database.models.user import User
from multimedia.webrtc_receiver import webrtc_receiver
from security.jwt import verify_access_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WebRTC"])

# Bound signaling payload size before allocating an aiortc peer connection.
MAX_SIGNAL_MESSAGE_BYTES = int(os.getenv("WEBRTC_MAX_SIGNAL_MESSAGE_BYTES", "65536"))
OFFER_TIMEOUT_SECONDS = float(os.getenv("WEBRTC_OFFER_TIMEOUT_SECONDS", "20"))


class OfferPayload(BaseModel):
    type: str = Field(pattern="^offer$")
    sdp: str = Field(min_length=1, max_length=MAX_SIGNAL_MESSAGE_BYTES)


def _authenticate_token(token: str | None, db: Session) -> User:
    """Validate the same signed access token used by the existing REST API."""
    if not token:
        raise HTTPException(status_code=401, detail="Access token is required.")
    user_id = verify_access_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.")
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User account was not found.")
    return user


def _get_owned_active_session(db: Session, session_id: int, user_id: int):
    """Require an active, unexpired session owned by the authenticated user."""
    capture_session = db.query(CaptureSession).filter(
        CaptureSession.session_id == session_id,
        CaptureSession.user_id == user_id,
    ).first()
    if capture_session is None:
        raise HTTPException(status_code=404, detail="Capture session was not found.")
    if capture_session.status != "active":
        raise HTTPException(status_code=409, detail="Capture session is not active.")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if capture_session.history_expires_at <= now:
        raise HTTPException(status_code=410, detail="Capture session history has expired.")
    return capture_session


def _set_stream_status(session_id: int, status_value: str) -> None:
    """Persist lifecycle state without holding a DB session during socket awaits."""
    from database.connection import SessionLocal

    with SessionLocal() as db:
        capture_session = db.query(CaptureSession).filter(
            CaptureSession.session_id == session_id
        ).first()
        if capture_session is not None:
            capture_session.stream_status = status_value
            capture_session.last_heartbeat_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()


async def _send_json(websocket: WebSocket, payload: dict) -> None:
    await websocket.send_text(json.dumps(payload))


@router.websocket("/ws/webrtc/{session_id}")
async def webrtc_signaling(websocket: WebSocket, session_id: int):
    """Mobile signaling: offer/answer, optional ICE candidates, heartbeat and stop."""
    from database.connection import SessionLocal

    token = websocket.query_params.get("token")
    db = SessionLocal()
    state = None
    accepted = False
    stopped_by_client = False

    try:
        user = _authenticate_token(token, db)
        _get_owned_active_session(db, session_id, user.user_id)
        await websocket.accept()
        accepted = True
        _set_stream_status(session_id, "connecting")

        # The first message must be a complete SDP offer from the mobile camera peer.
        raw_message = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=OFFER_TIMEOUT_SECONDS,
        )
        if len(raw_message.encode("utf-8")) > MAX_SIGNAL_MESSAGE_BYTES:
            await _send_json(websocket, {"type": "error", "code": "message_too_large"})
            return

        try:
            offer = OfferPayload.model_validate(json.loads(raw_message))
        except Exception:
            await _send_json(websocket, {"type": "error", "code": "invalid_offer"})
            return

        state = await webrtc_receiver.create_stream(session_id, user.user_id)
        await state.peer.setRemoteDescription(
            RTCSessionDescription(sdp=offer.sdp, type="offer")
        )
        answer = await state.peer.createAnswer()
        await state.peer.setLocalDescription(answer)

        # aiortc gathers local ICE candidates during setLocalDescription.
        await _send_json(websocket, {
            "type": "answer",
            "sdp": state.peer.localDescription.sdp,
        })
        _set_stream_status(session_id, "live")
        await _send_json(websocket, {
            "type": "stream-state",
            "state": "connected",
            "session_id": session_id,
        })

        while True:
            raw_message = await websocket.receive_text()
            if len(raw_message.encode("utf-8")) > MAX_SIGNAL_MESSAGE_BYTES:
                await _send_json(websocket, {"type": "error", "code": "message_too_large"})
                continue
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                await _send_json(websocket, {"type": "error", "code": "invalid_json"})
                continue

            message_type = message.get("type")
            if message_type == "ice-candidate":
                try:
                    await webrtc_receiver.add_ice_candidate(session_id, message)
                    await _send_json(websocket, {"type": "ice-candidate-accepted"})
                except (ValueError, TypeError) as error:
                    await _send_json(websocket, {
                        "type": "error",
                        "code": "invalid_ice_candidate",
                        "message": str(error),
                    })
            elif message_type == "heartbeat":
                _set_stream_status(session_id, "live")
                await _send_json(websocket, {"type": "heartbeat-ack"})
            elif message_type == "stop":
                stopped_by_client = True
                await _send_json(websocket, {"type": "stream-state", "state": "stopped"})
                break
            else:
                await _send_json(websocket, {"type": "error", "code": "unknown_message_type"})

    except WebSocketDisconnect:
        logger.info("WebRTC signaling disconnected for session %s", session_id)
    except asyncio.TimeoutError:
        if accepted:
            await _send_json(websocket, {"type": "error", "code": "offer_timeout"})
    except HTTPException as error:
        if not accepted:
            await websocket.close(code=4401 if error.status_code == 401 else 4404)
        else:
            await _send_json(websocket, {"type": "error", "code": "session_not_authorized"})
    except Exception:
        logger.exception("WebRTC signaling failed for session %s", session_id)
        if accepted and websocket.client_state == WebSocketState.CONNECTED:
            await _send_json(websocket, {"type": "error", "code": "signaling_failed"})
    finally:
        db.close()
        if state is not None:
            await webrtc_receiver.close_stream(session_id)
        if accepted:
            try:
                _set_stream_status(session_id, "stopped" if stopped_by_client else "disconnected")
            except Exception:
                logger.exception("Could not update stream status for session %s", session_id)


@router.get("/api/webrtc/sessions/{session_id}/status")
def get_webrtc_status(
    session_id: int,
    token: str,
    db: Session = Depends(get_db),
):
    """Return live connection and frame counters for an owned active session."""
    user = _authenticate_token(token, db)
    capture_session = _get_owned_active_session(db, session_id, user.user_id)
    state = webrtc_receiver.get_stream(session_id)
    return {
        "session_id": session_id,
        "session_status": capture_session.status,
        "stream_status": capture_session.stream_status,
        "connected": bool(state and not state.closed and state.peer.connectionState == "connected"),
        "connection_state": state.peer.connectionState if state else "closed",
        "ice_connection_state": state.peer.iceConnectionState if state else "closed",
        "received_frames": state.received_frames if state else 0,
        "saved_frames": state.saved_frames if state else 0,
        "last_frame_id": state.last_frame_id if state else None,
        "last_frame_at": state.last_frame_at if state else None,
    }


@router.websocket("/ws/webrtc/{session_id}/watch")
async def watch_webrtc_preview(websocket: WebSocket, session_id: int):
    """Stream JPEG preview frames as binary WebSocket messages to the dashboard."""
    from database.connection import SessionLocal

    token = websocket.query_params.get("token")
    db = SessionLocal()
    queue = None
    try:
        user = _authenticate_token(token, db)
        _get_owned_active_session(db, session_id, user.user_id)
        await websocket.accept()
        queue = await webrtc_receiver.add_viewer(session_id)
        await _send_json(websocket, {
            "type": "preview-ready",
            "session_id": session_id,
            "format": "jpeg-binary",
        })
        while True:
            jpeg_bytes = await queue.get()
            await websocket.send_bytes(jpeg_bytes)
    except WebSocketDisconnect:
        pass
    except HTTPException:
        await websocket.close(code=4401)
    finally:
        db.close()
        if queue is not None:
            await webrtc_receiver.remove_viewer(session_id, queue)
