
from datetime import datetime
from typing import Any

from sqlalchemy import (
    String, Text, ForeignKey,
    UniqueConstraint, CheckConstraint, Index, text
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class Frame(Base):
    __tablename__ = "frames"

    frame_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True
    )

    session_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False
    )

    sequence_number: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        nullable=False
    )

    captured_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False
    )

    received_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False
    )

    image_storage_key: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        unique=True
    )

    mime_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    width_px: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        nullable=False
    )

    height_px: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=True),
        nullable=False
    )

    size_bytes: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        nullable=False
    )

    sharpness_score: Mapped[float] = mapped_column(
        mysql.FLOAT,
        nullable=False
    )

    brightness_score: Mapped[float] = mapped_column(
        mysql.FLOAT,
        nullable=False
    )

    novelty_score: Mapped[float | None] = mapped_column(
        mysql.FLOAT,
        nullable=True
    )

    selection_reason: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    description_model_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("ai_models.model_id", ondelete="RESTRICT"),
        nullable=True
    )

    processing_status: Mapped[str] = mapped_column(
        mysql.ENUM("pending", "processing", "ready", "partial", "failed"),
        nullable=False,
        server_default=text("'pending'")
    )

    processing_details: Mapped[dict[str, Any] | None] = mapped_column(
        mysql.JSON,
        nullable=True
    )

    processed_at: Mapped[datetime | None] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=True
    )

    expires_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "session_id", "sequence_number",
            name="uq_frame_sequence"
        ),
        CheckConstraint(
            "width_px > 0 AND height_px > 0 AND size_bytes > 0",
            name="ck_frames_dimensions_size"
        ),
        CheckConstraint(
            "sharpness_score >= 0",
            name="ck_frames_sharpness"
        ),
        CheckConstraint(
            "brightness_score BETWEEN 0 AND 255",
            name="ck_frames_brightness"
        ),
        CheckConstraint(
            "novelty_score IS NULL OR novelty_score BETWEEN 0 AND 1",
            name="ck_frames_novelty"
        ),
        CheckConstraint(
            "expires_at > captured_at",
            name="ck_frames_expiry"
        ),
        Index("idx_frame_timeline", "session_id", "captured_at"),
        Index("idx_frame_expiry", "expires_at"),
        Index("idx_frame_processing", "processing_status", "received_at"),
    )
