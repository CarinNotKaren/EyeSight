
from sqlalchemy import (
    Column, String, Text, ForeignKey,
    UniqueConstraint, CheckConstraint, text
)
from sqlalchemy.dialects import mysql

from database.base import Base


class OCRResult(Base):
    __tablename__ = "ocr_results"

    ocr_result_id = Column(
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

    region_index = Column(mysql.INTEGER(unsigned=True), nullable=False)
    recognized_text = Column(Text, nullable=False)
    language_code = Column(String(16), nullable=True)
    confidence = Column(mysql.FLOAT, nullable=False)
    polygon = Column(mysql.JSON, nullable=False)
    reading_order = Column(mysql.INTEGER(unsigned=True), nullable=True)

    created_at = Column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)")
    )

    __table_args__ = (
        UniqueConstraint(
            "frame_id", "model_id", "region_index",
            name="uq_ocr_region"
        ),
        CheckConstraint(
            "confidence BETWEEN 0 AND 1",
            name="ck_ocr_confidence"
        ),
        CheckConstraint(
            "JSON_TYPE(polygon) = 'ARRAY'",
            name="ck_ocr_polygon"
        ),
    )
