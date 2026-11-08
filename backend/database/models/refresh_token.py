
from sqlalchemy import Column, ForeignKey, String, text
from sqlalchemy.dialects import mysql

from database.base import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    token_id = Column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True
    )

    user_id = Column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False
    )

    token_hash = Column(
        String(64),
        nullable=False,
        unique=True
    )

    expires_at = Column(
        mysql.DATETIME(fsp=6),
        nullable=False
    )

    revoked_at = Column(
        mysql.DATETIME(fsp=6),
        nullable=True
    )

    created_at = Column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)")
    )
