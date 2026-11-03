from sqlalchemy import Column, ForeignKey, CheckConstraint, String, Text, Index
from sqlalchemy.dialects import mysql
from database.base import Base


class Alert(Base):
    __tablename__ = "alerts"

    alert_id = Column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True
    )

    session_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False
    )

    frame_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("frames.frame_id", ondelete="SET NULL"),
        nullable=True
    )

    alert_type = Column(String(50), nullable=False)
    message_text = Column(Text, nullable=False)
    language_code = Column(String(16), nullable=False)

    created_at = Column(mysql.DATETIME(fsp=6), nullable=False)
    delivered_at = Column(mysql.DATETIME(fsp=6), nullable=True)

    __table_args__ = (
        Index("idx_alert_timeline", "session_id", "created_at"),

        CheckConstraint(
            "delivered_at IS NULL OR delivered_at >= created_at",
            name="ck_alert_delivered_at"
        ),
    )