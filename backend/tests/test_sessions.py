"""Unit tests for authenticated device and capture-session lifecycle routes."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from database.models.device import Device
from database.models.session import Session as CaptureSession
from routers import sessions as sessions_router


class FakeQuery:
    """Small SQLAlchemy-query stand-in for isolated route tests."""

    def __init__(self, result):
        self.result = result

    def filter(self, *conditions):
        # Route filters are exercised by the route's explicit test setup.
        return self

    def first(self):
        return self.result


class FakeDB:
    """Capture writes without requiring a running MySQL instance."""

    def __init__(self, query_result=None):
        self.query_result = query_result
        self.added = None
        self.committed = False

    def query(self, model):
        return FakeQuery(self.query_result)

    def add(self, item):
        self.added = item

    def commit(self):
        self.committed = True

    def refresh(self, item):
        # Simulate an auto-increment ID assigned by MySQL.
        if isinstance(item, CaptureSession):
            item.session_id = 321
        elif isinstance(item, Device):
            item.device_id = 123


def test_access_token_helper_rejects_invalid_token(monkeypatch):
    """Invalid access tokens must not produce an authenticated user ID."""
    monkeypatch.setattr(sessions_router, "verify_access_token", lambda token: None)
    credentials = SimpleNamespace(credentials="invalid-token")

    with pytest.raises(HTTPException) as error:
        sessions_router._get_user_id(credentials)

    assert error.value.status_code == 401


def test_device_registration_rejects_another_users_installation():
    """A user must not take ownership of an installation registered elsewhere."""
    existing_device = SimpleNamespace(user_id=22)
    db = FakeDB(query_result=existing_device)
    payload = sessions_router.DeviceRegistration(
        installation_id=uuid4(),
        platform="android",
    )

    with pytest.raises(HTTPException) as error:
        sessions_router.register_device(payload, user_id=11, db=db)

    assert error.value.status_code == 403
    assert db.committed is False


def test_device_registration_creates_owned_device():
    """New installation records must be linked to the authenticated user."""
    db = FakeDB(query_result=None)
    payload = sessions_router.DeviceRegistration(
        installation_id=uuid4(),
        platform="ios",
        device_name="Test iPhone",
        app_version="1.0.0",
    )

    response = sessions_router.register_device(payload, user_id=11, db=db)

    assert db.committed is True
    assert db.added.user_id == 11
    assert response["device_id"] == 123
    assert response["platform"] == "ios"


def test_session_creation_requires_explicit_consent():
    """A session must not be created when the user has not consented."""
    payload = sessions_router.SessionCreate(
        device_id=123,
        language_code="en",
        consent=False,
        consent_version="1.0",
    )

    with pytest.raises(HTTPException) as error:
        sessions_router.create_capture_session(payload, user_id=11, db=FakeDB())

    assert error.value.status_code == 400


def test_session_creation_rejects_device_owned_by_another_user():
    """A capture session can only use a device owned by the signed-in user."""
    device = SimpleNamespace(device_id=123, user_id=22)
    db = FakeDB(query_result=device)
    payload = sessions_router.SessionCreate(
        device_id=123,
        language_code="en",
        consent=True,
        consent_version="1.0",
    )

    with pytest.raises(HTTPException) as error:
        sessions_router.create_capture_session(payload, user_id=11, db=db)

    assert error.value.status_code == 404
    assert db.committed is False


def test_session_creation_starts_in_connecting_state():
    """A session remains starting until the WebRTC peer actually connects."""
    device = SimpleNamespace(device_id=123, user_id=11)
    db = FakeDB(query_result=device)
    payload = sessions_router.SessionCreate(
        device_id=123,
        language_code="fr",
        consent=True,
        consent_version="1.0",
    )

    response = sessions_router.create_capture_session(
        payload,
        user_id=11,
        db=db,
    )

    assert db.committed is True
    assert db.added.user_id == 11
    assert db.added.status == "starting"
    assert db.added.stream_status == "connecting"
    assert db.added.consented_at <= db.added.started_at
    assert response["session_id"] == 321
    assert response["status"] == "starting"


def test_session_end_closes_the_peer_connection(monkeypatch):
    """Ending a session must persist its state and release the WebRTC peer."""
    capture_session = SimpleNamespace(
        session_id=321,
        user_id=11,
        status="active",
        stream_status="live",
        ended_at=None,
        last_heartbeat_at=None,
    )
    db = FakeDB(query_result=capture_session)
    closed = []

    async def fake_close_stream(session_id):
        closed.append(session_id)

    from multimedia import webrtc_receiver
    monkeypatch.setattr(
        webrtc_receiver.webrtc_receiver,
        "close_stream",
        fake_close_stream,
    )

    response = asyncio.run(
        sessions_router.end_capture_session(
            session_id=321,
            user_id=11,
            db=db,
        )
    )

    assert db.committed is True
    assert capture_session.status == "ended"
    assert capture_session.stream_status == "stopped"
    assert closed == [321]
    assert response["status"] == "ended"
