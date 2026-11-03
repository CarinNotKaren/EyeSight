
from sqlalchemy import (
    Column, String, ForeignKey,
    UniqueConstraint, CheckConstraint, Index, text
)
from sqlalchemy.dialects import mysql

from database.base import Base


class ObjectDetection(Base):
    __tablename__ = "object_detections"

    detection_id = Column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True
    )

    frame_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("frames.frame_id", ondelete="CASCADE"),
        nullable=False
    )

    model_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("ai_models.model_id", ondelete="RESTRICT"),
        nullable=False
    )

    detection_index = Column(mysql.INTEGER(unsigned=True), nullable=False)
    class_id = Column(mysql.INTEGER(unsigned=True), nullable=False)
    label = Column(String(100), nullable=False)

    confidence = Column(mysql.FLOAT, nullable=False)

    x_min = Column(mysql.FLOAT, nullable=False)
    y_min = Column(mysql.FLOAT, nullable=False)
    x_max = Column(mysql.FLOAT, nullable=False)
    y_max = Column(mysql.FLOAT, nullable=False)

    created_at = Column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)")
    )

    __table_args__ = (
        UniqueConstraint(
            "frame_id", "model_id", "detection_index",
            name="uq_detection"
        ),
        CheckConstraint(
            "confidence BETWEEN 0 AND 1",
            name="ck_detection_confidence"
        ),
        CheckConstraint(
            "x_min >= 0 AND x_max <= 1 AND x_min < x_max",
            name="ck_detection_x_coordinates"
        ),
        CheckConstraint(
            "y_min >= 0 AND y_max <= 1 AND y_min < y_max",
            name="ck_detection_y_coordinates"
        ),
        Index("idx_object_label", "label", "frame_id"),
    )
