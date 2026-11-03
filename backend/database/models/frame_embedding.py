
from sqlalchemy import (
    Column, Text, ForeignKey,
    UniqueConstraint, CheckConstraint, Index, text
)
from sqlalchemy.dialects import mysql

from database.base import Base


class FrameEmbedding(Base):
    __tablename__ = "frame_embeddings"

    embedding_id = Column(
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

    embedding_kind = Column(
        mysql.ENUM("image", "frame_text"),
        nullable=False
    )

    dimensions = Column(mysql.INTEGER(unsigned=True), nullable=False)
    vector_data = Column(mysql.BLOB, nullable=False)
    is_normalized = Column(mysql.BOOLEAN, nullable=False)
    source_text = Column(Text, nullable=True)

    created_at = Column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)")
    )

    __table_args__ = (
        UniqueConstraint(
            "frame_id", "model_id", "embedding_kind",
            name="uq_frame_embedding"
        ),
        CheckConstraint(
            "dimensions > 0 AND OCTET_LENGTH(vector_data) = dimensions * 4",
            name="ck_embedding_dimensions"
        ),
        CheckConstraint(
            "is_normalized IN (0,1)",
            name="ck_embedding_normalized"
        ),
        CheckConstraint(
            "(embedding_kind = 'image' AND source_text IS NULL) "
            "OR (embedding_kind = 'frame_text' AND source_text IS NOT NULL)",
            name="ck_embedding_source_text"
        ),
        Index(
            "idx_embedding_model",
            "model_id", "embedding_kind", "frame_id"
        ),
    )
