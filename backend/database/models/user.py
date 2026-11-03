from sqlalchemy import Column, String, text
from sqlalchemy.dialects import mysql

from database.base import Base


class User(Base):
    __tablename__ = "users"

    user_id = Column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True
    )

    display_name = Column(String(100), nullable=False)

    preferred_language = Column(
        String(16),
        nullable=False,
        server_default=text("'en'")
    )

    created_at = Column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)")
    )