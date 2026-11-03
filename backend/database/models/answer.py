from sqlalchemy import Column, ForeignKey, String, Text
from sqlalchemy.dialects import mysql
from database.base import Base


class Answer(Base):
    __tablename__ = "answers"

    answer_id = Column(mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True)

    question_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("questions.question_id", ondelete="CASCADE"),
        nullable=False,
        unique=True
    )

    model_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("ai_models.model_id", ondelete="RESTRICT"),
        nullable=True
    )

    answer_text = Column(Text, nullable=False)
    language_code = Column(String(16), nullable=False)

    answer_type = Column(
        mysql.ENUM("grounded", "uncertain", "no_evidence", "error_fallback"),
        nullable=False
    )

    uncertainty_reason = Column(String(255), nullable=True)
    prompt_version = Column(String(50), nullable=False)

    stt_latency_ms = Column(mysql.INTEGER(unsigned=True), nullable=True)
    retrieval_latency_ms = Column(mysql.INTEGER(unsigned=True), nullable=True)
    generation_latency_ms = Column(mysql.INTEGER(unsigned=True), nullable=True)

    server_total_latency_ms = Column(mysql.INTEGER(unsigned=True), nullable=False)

    playback_started_at = Column(mysql.DATETIME(fsp=6), nullable=True)
    created_at = Column(mysql.DATETIME(fsp=6), nullable=False)