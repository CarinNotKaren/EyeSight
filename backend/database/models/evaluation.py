from sqlalchemy import Column, ForeignKey, CheckConstraint, String, Text
from sqlalchemy.dialects import mysql
from database.base import Base


class Evaluation(Base):
    __tablename__ = "evaluations"

    evaluation_id = Column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True
    )

    answer_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("answers.answer_id", ondelete="CASCADE"),
        nullable=False
    )

    test_case_code = Column(String(100), nullable=False)
    evaluation_version = Column(String(50), nullable=False)

    expected_answer = Column(Text, nullable=True)

    answer_verdict = Column(
        mysql.ENUM("correct", "partial", "incorrect", "unjudged"),
        nullable=False,
        server_default="unjudged"
    )

    retrieved_count = Column(mysql.INTEGER(unsigned=True), nullable=True)
    relevant_count = Column(mysql.INTEGER(unsigned=True), nullable=True)
    relevant_retrieved_count = Column(mysql.INTEGER(unsigned=True), nullable=True)

    end_to_end_latency_ms = Column(mysql.INTEGER(unsigned=True), nullable=True)

    notes = Column(Text, nullable=True)
    evaluated_at = Column(mysql.DATETIME(fsp=6), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "relevant_retrieved_count IS NULL OR "
            "(retrieved_count IS NOT NULL AND "
            "relevant_retrieved_count <= retrieved_count)",
            name="ck_evaluation_retrieved_count"
        ),

        CheckConstraint(
            "relevant_count IS NULL OR "
            "relevant_retrieved_count IS NULL OR "
            "relevant_retrieved_count <= relevant_count",
            name="ck_evaluation_relevant_count"
        ),
    )