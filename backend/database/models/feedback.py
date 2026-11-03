from sqlalchemy import Column, ForeignKey, CheckConstraint, Text, text
from sqlalchemy.dialects import mysql
from database.base import Base


class Feedback(Base):
    __tablename__ = "feedback"

    feedback_id = Column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True
    )

    session_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False
    )

    answer_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("answers.answer_id", ondelete="CASCADE"),
        nullable=True
    )

    rating = Column(mysql.TINYINT(unsigned=True), nullable=False)
    comment = Column(Text, nullable=True)

    created_at = Column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)")
    )

    __table_args__ = (
        CheckConstraint(
            "rating >= 1 AND rating <= 5",
            name="ck_feedback_rating"
        ),
    )