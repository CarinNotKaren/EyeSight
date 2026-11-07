
from sqlalchemy import (
    Column, String, Text, ForeignKey,
    UniqueConstraint, CheckConstraint, Index, text
)
from sqlalchemy.dialects import mysql

from database.base import Base


class Question(Base):
    __tablename__ = "questions"

    question_id = Column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True
    )

    session_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False
    )

    client_request_id = Column(mysql.CHAR(36), nullable=False)

    input_type = Column(
        mysql.ENUM("voice", "text"),
        nullable=False
    )

    question_text = Column(Text, nullable=True)
    language_code = Column(String(16), nullable=True)

    stt_model_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("ai_models.model_id", ondelete="RESTRICT"),
        nullable=True
    )

    status = Column(
        mysql.ENUM(
            "received", "transcribing", "retrieving",
            "answering", "completed", "failed"
        ),
        nullable=False,
        server_default=text("'received'")
    )

    search_from_at = Column(mysql.DATETIME(fsp=6), nullable=True)
    search_to_at = Column(mysql.DATETIME(fsp=6), nullable=True)
    retrieval_configuration = Column(mysql.JSON, nullable=True)
    error_code = Column(String(100), nullable=True)
    received_at = Column(mysql.DATETIME(fsp=6), nullable=False)

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


