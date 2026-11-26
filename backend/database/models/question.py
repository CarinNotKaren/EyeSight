
from datetime import datetime
from typing import Any

from sqlalchemy import (
    String, Text, ForeignKey,
    UniqueConstraint, CheckConstraint, Index, text
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class Question(Base):
    __tablename__ = "questions"

    question_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True
    )

    session_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False
    )

    client_request_id: Mapped[str] = mapped_column(
        mysql.CHAR(36),
        nullable=False
    )

    input_type: Mapped[str] = mapped_column(
        mysql.ENUM("voice", "text"),
        nullable=False
    )

    question_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    language_code: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True
    )

    stt_model_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("ai_models.model_id", ondelete="RESTRICT"),
        nullable=True
    )

    status: Mapped[str] = mapped_column(
        mysql.ENUM(
            "received", "transcribing", "retrieving",
            "answering", "completed", "failed"
        ),
        nullable=False,
        server_default=text("'received'")
    )

    search_from_at: Mapped[datetime | None] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=True
    )

    search_to_at: Mapped[datetime | None] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=True
    )

    retrieval_configuration: Mapped[dict[str, Any] | None] = mapped_column(
        mysql.JSON,
        nullable=True
    )

    error_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    received_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "session_id", "client_request_id",
            name="uq_question_request"
        ),
        CheckConstraint(
            "search_from_at IS NULL OR search_to_at IS NULL "
            "OR search_from_at <= search_to_at",
            name="ck_question_search_range"
        ),
        CheckConstraint(
            "input_type <> 'text' OR question_text IS NOT NULL",
            name="ck_question_text_required"
        ),
        Index("idx_question_history", "session_id", "received_at"),
    )
