from sqlalchemy import Column, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects import mysql
from database.base import Base


class AnswerEvidence(Base):
    __tablename__ = "answer_evidence"

    answer_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("answers.answer_id", ondelete="CASCADE"),
        primary_key=True
    )

    frame_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("frames.frame_id", ondelete="CASCADE"),
        primary_key=True
    )

    retrieval_rank = Column(mysql.INTEGER(unsigned=True), nullable=False)

    retrieval_method = Column(
        mysql.ENUM("semantic", "ocr", "time", "hybrid"),
        nullable=False
    )

    semantic_score = Column(mysql.FLOAT, nullable=True)
    combined_score = Column(mysql.FLOAT, nullable=True)
    provided_to_model = Column(mysql.BOOLEAN, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "answer_id",
            "retrieval_rank",
            name="uq_evidence_rank"
        ),

        CheckConstraint(
            "retrieval_rank > 0",
            name="ck_evidence_rank"
        ),

        CheckConstraint(
            "semantic_score IS NULL OR (semantic_score >= -1 AND semantic_score <= 1)",
            name="ck_evidence_semantic_score"
        ),

        CheckConstraint(
            "provided_to_model IN (0, 1)",
            name="ck_evidence_provided"
        ),
    )