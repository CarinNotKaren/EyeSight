"""Merge authentication migration branches and add device ownership."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "c81f9b2a6d10"
down_revision: Union[str, Sequence[str], None] = (
    "0787cc47def6",
    "51acc7ededdf",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge the parallel auth revisions and associate devices with users."""
    op.add_column(
        "devices",
        sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_devices_user_id_users",
        "devices",
        "users",
        ["user_id"],
        ["user_id"],
        ondelete="RESTRICT",
    )
    op.create_index("idx_device_user", "devices", ["user_id"], unique=False)


def downgrade() -> None:
    """Remove device ownership and split the migration heads again."""
    op.drop_index("idx_device_user", table_name="devices")
    op.drop_constraint(
        "fk_devices_user_id_users",
        "devices",
        type_="foreignkey",
    )
    op.drop_column("devices", "user_id")
