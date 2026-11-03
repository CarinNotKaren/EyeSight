from sqlalchemy import Column, String, text
from sqlalchemy.dialects import mysql

from database.base import Base


class Device(Base):
    __tablename__ = "devices"

    device_id = Column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True
    )

    installation_id = Column(
        mysql.CHAR(36),
        nullable=False,
        unique=True
    )

    device_name = Column(String(100), nullable=False)

    platform = Column(
        mysql.ENUM("android", "ios"),
        nullable=False
    )

    app_version = Column(String(30), nullable=True)

    last_seen_at = Column(
        mysql.DATETIME(fsp=6),
        nullable=True
    )

    created_at = Column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)")
    )