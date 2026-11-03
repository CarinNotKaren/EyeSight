from sqlalchemy import Column, String, text
from sqlalchemy.dialects import mysql

from database.base import Base


class AIModel(Base):
    __tablename__ = "ai_models"

    model_id = Column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True
    )

    task = Column(
        mysql.ENUM(
            "ocr",
            "object_detection",
            "embedding",
            "vision_language",
            "speech_to_text"
        ),
        nullable=False
    )

    provider = Column(String(100), nullable=False)

    model_name = Column(String(255), nullable=False)

    model_revision = Column(String(100), nullable=False)

    configuration = Column(mysql.JSON, nullable=False)

    created_at = Column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)")
    )