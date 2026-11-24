"""Authenticated device registration and capture-session lifecycle APIs."""

import os
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.dependencies import get_db
from database.models.device import Device
from database.models.session import Session as CaptureSession
from security.jwt import verify_access_token

router = APIRouter(tags=["Capture Sessions"])
bearer_scheme = HTTPBearer()

# Keep retention configurable so the team can align it with its approved policy.
FRAME_RETENTION_SECONDS = int(
    os.getenv("SESSION_FRAME_RETENTION_SECONDS", "86400")
)


def _get_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> int:
    """Validate the existing access token and return its user ID."""
    user_id = verify_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return int(user_id)


class DeviceRegistration(BaseModel):
    """Mobile installation details used to associate capture sessions."""

    installation_id: UUID
    platform: Literal["ios", "android"]
    device_name: str = Field(default="EyeSight mobile device", max_length=100)
    app_version: str | None = Field(default=None, max_length=30)


class DeviceResponse(BaseModel):
    device_id: int
    installation_id: UUID
    platform: str


class SessionCreate(BaseModel):
    """A session can only be created after the user explicitly consents."""

    device_id: int = Field(gt=0)
    language_code: str = Field(default="en", min_length=2, max_length=16)
    consent: bool
    consent_version: str = Field(min_length=1, max_length=30)


class SessionResponse(BaseModel):
    session_id: int
    status: str
    stream_status: str
    started_at: datetime
    history_expires_at: datetime


@router.post("/api/devices/register", response_model=DeviceResponse)
def register_device(
    data: DeviceRegistration,
    user_id: int = Depends(_get_user_id),
    db: Session = Depends(get_db),
):
    """Create or refresh the installation record for an authenticated user."""
    # The current schema identifies a physical installation globally; session
    # ownership is enforced separately through the authenticated user_id.
    device = db.query(Device).filter(
        Device.installation_id == str(data.installation_id)
    ).first()

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if device is None:
        device = Device(
            installation_id=str(data.installation_id),
            device_name=data.device_name,
            platform=data.platform,
            app_version=data.app_version,
            last_seen_at=now,
        )
        db.add(device)
    else:
        device.device_name = data.device_name
        device.platform = data.platform
        device.app_version = data.app_version
        device.last_seen_at = now

    db.commit()
    db.refresh(device)

    return {
        "device_id": device.device_id,
        "installation_id": device.installation_id,
        "platform": device.platform,
    }


@router.post("/api/sessions", response_model=SessionResponse, status_code=201)
def create_capture_session(
    data: SessionCreate,
    user_id: int = Depends(_get_user_id),
    db: Session = Depends(get_db),
):
    """Create an active capture session after explicit recording consent."""
    if not data.consent:
        raise HTTPException(
            status_code=400,
            detail="Recording consent is required to start a session",
        )

    device = db.query(Device).filter(
        Device.device_id == data.device_id
    ).first()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    if FRAME_RETENTION_SECONDS <= 0:
        raise HTTPException(
            status_code=500,
            detail="Session retention configuration must be positive",
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expires_at = now + timedelta(seconds=FRAME_RETENTION_SECONDS)

    capture_session = CaptureSession(
        user_id=user_id,
        device_id=device.device_id,
        language_code=data.language_code,
        status="active",
        stream_status="connecting",
        started_at=now,
        consented_at=now,
        consent_version=data.consent_version,
        frame_retention_seconds=FRAME_RETENTION_SECONDS,
        history_expires_at=expires_at,
        last_heartbeat_at=now,
    )

    db.add(capture_session)
    db.commit()
    db.refresh(capture_session)

    return {
        "session_id": capture_session.session_id,
        "status": capture_session.status,
        "stream_status": capture_session.stream_status,
        "started_at": capture_session.started_at,
        "history_expires_at": capture_session.history_expires_at,
    }


@router.post("/api/sessions/{session_id}/end")
def end_capture_session(
    session_id: int,
    user_id: int = Depends(_get_user_id),
    db: Session = Depends(get_db),
):
    """End only a session owned by the authenticated user; safe to retry."""
    capture_session = db.query(CaptureSession).filter(
        CaptureSession.session_id == session_id,
        CaptureSession.user_id == user_id,
    ).first()

    if capture_session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if capture_session.status != "ended":
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        capture_session.status = "ended"
        capture_session.stream_status = "stopped"
        capture_session.ended_at = now
        capture_session.last_heartbeat_at = now
        db.commit()
        db.refresh(capture_session)

    return {
        "session_id": capture_session.session_id,
        "status": capture_session.status,
        "stream_status": capture_session.stream_status,
    }
