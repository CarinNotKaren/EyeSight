from sqlalchemy import (
    Column,
    String,
    ForeignKey,
    CheckConstraint,
    Index,
    text
)
from sqlalchemy.dialects import mysql

from database.base import Base


class Session(Base):
    __tablename__ = "sessions"

    session_id = Column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True
    )

    user_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False
    )

    device_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("devices.device_id", ondelete="RESTRICT"),
        nullable=False
    )

    language_code = Column(
        String(16),
        nullable=False,
        server_default=text("'en'")
    )

    status = Column(
        mysql.ENUM("starting", "active", "ended", "failed"),
        nullable=False,
        server_default=text("'starting'")
    )

    stream_status = Column(
        mysql.ENUM("connecting", "live", "disconnected", "stopped"),
        nullable=False,
        server_default=text("'connecting'")
    )

    started_at = Column(mysql.DATETIME(fsp=6), nullable=False)
    ended_at = Column(mysql.DATETIME(fsp=6), nullable=True)
    last_heartbeat_at = Column(mysql.DATETIME(fsp=6), nullable=True)
    consented_at = Column(mysql.DATETIME(fsp=6), nullable=False)

    consent_version = Column(String(30), nullable=False)

    frame_retention_seconds = Column(
        mysql.INTEGER(unsigned=True),
        nullable=False
    )

    history_expires_at = Column(
        mysql.DATETIME(fsp=6),
        nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "frame_retention_seconds > 0",
            name="ck_sessions_frame_retention"
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ck_sessions_ended_at"
        ),
        CheckConstraint(
            "consented_at <= started_at",
            name="ck_sessions_consented_at"
        ),
        CheckConstraint(
            "history_expires_at > started_at",
            name="ck_sessions_history_expiry"
        ),
        Index("idx_session_user_time", "user_id", "started_at"),
        Index("idx_session_health", "status", "last_heartbeat_at"),
        Index("idx_session_expiry", "history_expires_at"),
    )