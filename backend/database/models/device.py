
from datetime import datetime

from sqlalchemy import String, ForeignKey, Index, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class Device(Base):
    __tablename__ = "devices"

    device_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True
    )

    # Nullable to support legacy installations.
    user_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True),
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=True
    )

    installation_id: Mapped[str] = mapped_column(
        mysql.CHAR(36),
        nullable=False,
        unique=True
    )

    device_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    platform: Mapped[str] = mapped_column(
        mysql.ENUM("android", "ios"),
        nullable=False
    )

    app_version: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True
    )

    last_seen_at: Mapped[datetime | None] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)")
    )
    __table_args__ = (
        Index("idx_device_user", "user_id"),
    )
