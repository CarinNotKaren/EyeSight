"""Read-only dashboard APIs for authenticated users."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database.dependencies import get_db
from database.models.answer import Answer
from database.models.answer_evidence import AnswerEvidence
from database.models.device import Device
from database.models.frame import Frame
from database.models.object_detection import ObjectDetection
from database.models.ocr_result import OCRResult
from database.models.question import Question
from database.models.session import Session as CaptureSession
from routers.sessions import _get_user_id

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _owned_session(db: Session, session_id: int, user_id: int):
    """Return only an unexpired session owned by the authenticated user."""
    capture = db.query(CaptureSession).filter(
        CaptureSession.session_id == session_id,
        CaptureSession.user_id == user_id,
    ).first()
    if capture is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if capture.history_expires_at <= _now():
        raise HTTPException(status_code=410, detail="Session history has expired")
    return capture


@router.get("/sessions")
def list_dashboard_sessions(
    user_id: int = Depends(_get_user_id),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List the current user's sessions with their registered device metadata."""
    rows = db.query(CaptureSession, Device).join(
        Device, Device.device_id == CaptureSession.device_id
    ).filter(
        CaptureSession.user_id == user_id,
        CaptureSession.history_expires_at > _now(),
    ).order_by(
        CaptureSession.started_at.desc()
    ).offset(offset).limit(limit).all()

    return [{
        "session_id": session.session_id,
        "language_code": session.language_code,
        "status": session.status,
        "stream_status": session.stream_status,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "last_heartbeat_at": session.last_heartbeat_at,
        "history_expires_at": session.history_expires_at,
        "device": {
            "device_id": device.device_id,
            "device_name": device.device_name,
            "platform": device.platform,
            "app_version": device.app_version,
            "last_seen_at": device.last_seen_at,
        },
    } for session, device in rows]


@router.get("/sessions/{session_id}")
def get_dashboard_session(
    session_id: int,
    user_id: int = Depends(_get_user_id),
    db: Session = Depends(get_db),
):
    """Return a single owned session and its device details."""
    capture = _owned_session(db, session_id, user_id)
    device = db.get(Device, capture.device_id)
    return {
        "session_id": capture.session_id,
        "language_code": capture.language_code,
        "status": capture.status,
        "stream_status": capture.stream_status,
        "started_at": capture.started_at,
        "ended_at": capture.ended_at,
        "last_heartbeat_at": capture.last_heartbeat_at,
        "history_expires_at": capture.history_expires_at,
        "device": None if device is None else {
            "device_id": device.device_id,
            "device_name": device.device_name,
            "platform": device.platform,
            "app_version": device.app_version,
            "last_seen_at": device.last_seen_at,
        },
    }


@router.get("/sessions/{session_id}/frames")
def list_dashboard_frames(
    session_id: int,
    user_id: int = Depends(_get_user_id),
    db: Session = Depends(get_db),
    limit: int = Query(default=40, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List unexpired frame metadata and analysis for one owned session."""
    capture = _owned_session(db, session_id, user_id)
    frames = db.query(Frame).filter(
        Frame.session_id == session_id,
        Frame.expires_at > _now(),
        CaptureSession.history_expires_at > _now(),
    ).order_by(
        Frame.captured_at.desc()
    ).offset(offset).limit(limit).all()

    results = []
    for frame in frames:
        details = dict(frame.processing_details or {})
        ocr_stage = details.get("ocr") or {}
        object_stage = details.get("object_detection") or {}

        ocr_rows = []
        if ocr_stage.get("status") == "completed" and ocr_stage.get("model_id"):
            ocr_rows = db.query(OCRResult).filter(
                OCRResult.frame_id == frame.frame_id,
                OCRResult.model_id == ocr_stage["model_id"],
            ).order_by(OCRResult.region_index).all()

        object_rows = []
        if object_stage.get("status") == "completed" and object_stage.get("model_id"):
            object_rows = db.query(ObjectDetection).filter(
                ObjectDetection.frame_id == frame.frame_id,
                ObjectDetection.model_id == object_stage["model_id"],
            ).order_by(ObjectDetection.detection_index).all()

        results.append({
            "frame_id": frame.frame_id,
            "sequence_number": frame.sequence_number,
            "captured_at": frame.captured_at,
            "width_px": frame.width_px,
            "height_px": frame.height_px,
            "size_bytes": frame.size_bytes,
            "mime_type": frame.mime_type,
            "sharpness_score": frame.sharpness_score,
            "brightness_score": frame.brightness_score,
            "novelty_score": frame.novelty_score,
            "selection_reason": frame.selection_reason,
            "processing_status": frame.processing_status,
            "processing_details": details,
            "processed_at": frame.processed_at,
            "image_url": f"/api/dashboard/sessions/{session_id}/frames/{frame.frame_id}/image",
            "ocr": [{
                "text": row.recognized_text,
                "language_code": row.language_code,
                "confidence": row.confidence,
                "polygon": row.polygon,
                "region_index": row.region_index,
            } for row in ocr_rows],
            "objects": [{
                "label": row.label,
                "confidence": row.confidence,
                "box": {
                    "x_min": row.x_min,
                    "y_min": row.y_min,
                    "x_max": row.x_max,
                    "y_max": row.y_max,
                },
            } for row in object_rows],
        })
    return results


@router.get("/sessions/{session_id}/frames/{frame_id}/image")
def get_dashboard_frame_image(
    session_id: int,
    frame_id: int,
    user_id: int = Depends(_get_user_id),
    db: Session = Depends(get_db),
):
    """Stream an image only after verifying session ownership and safe storage path."""
    capture = _owned_session(db, session_id, user_id)
    frame = db.query(Frame).filter(
        Frame.frame_id == frame_id,
        Frame.session_id == session_id,
        Frame.expires_at > _now(),
    ).first()
    if frame is None:
        raise HTTPException(status_code=404, detail="Frame not found")

    storage_root = (Path(__file__).resolve().parents[1] / "storage").resolve()
    frames_root = (storage_root / "frames").resolve()
    image_path = (storage_root / frame.image_storage_key).resolve()
    if not image_path.is_relative_to(frames_root) or image_path == frames_root:
        raise HTTPException(status_code=404, detail="Frame image not found")
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Frame image not found")

    return FileResponse(
        image_path,
        media_type=frame.mime_type,
        filename=f"eyesight-frame-{frame.frame_id}",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/sessions/{session_id}/questions")
def list_dashboard_questions(
    session_id: int,
    user_id: int = Depends(_get_user_id),
    db: Session = Depends(get_db),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Return a session's question/answer history and safe evidence references."""
    _owned_session(db, session_id, user_id)
    questions = db.query(Question).filter(
        Question.session_id == session_id,
    ).order_by(
        Question.received_at.desc()
    ).offset(offset).limit(limit).all()

    output = []
    for question in questions:
        answer = db.query(Answer).filter(
            Answer.question_id == question.question_id
        ).first()
        evidence = []
        if answer is not None:
            evidence = db.query(AnswerEvidence).filter(
                AnswerEvidence.answer_id == answer.answer_id
            ).order_by(AnswerEvidence.retrieval_rank).all()

        output.append({
            "question_id": question.question_id,
            "session_id": question.session_id,
            "input_type": question.input_type,
            "question_text": question.question_text,
            "language_code": question.language_code,
            "status": question.status,
            "received_at": question.received_at,
            "answer": None if answer is None else {
                "answer_id": answer.answer_id,
                "answer_text": answer.answer_text,
                "language_code": answer.language_code,
                "answer_type": answer.answer_type,
                "uncertainty_reason": answer.uncertainty_reason,
                "created_at": answer.created_at,
            },
            "evidence": [{
                "frame_id": item.frame_id,
                "retrieval_rank": item.retrieval_rank,
                "retrieval_method": item.retrieval_method,
                "semantic_score": item.semantic_score,
                "combined_score": item.combined_score,
                "provided_to_model": item.provided_to_model,
            } for item in evidence],
        })
    return output
