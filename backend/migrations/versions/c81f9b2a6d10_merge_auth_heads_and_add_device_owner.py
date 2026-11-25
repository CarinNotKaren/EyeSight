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
    """Merge auth revisions and safely add device ownership."""

    # Inspect the current database because a previous MySQL migration
    # attempt may have applied some DDL operations before failing.
    inspector = sa.inspect(op.get_bind())

    # Add user_id only if the previous attempt did not create it.
    columns = [column["name"] for column in inspector.get_columns("devices")]
    if "user_id" not in columns:
        op.add_column(
            "devices",
            sa.Column("user_id", mysql.BIGINT(unsigned=True), nullable=True),
        )

    # Re-inspect to check the foreign keys currently present.
    inspector = sa.inspect(op.get_bind())
    foreign_keys = inspector.get_foreign_keys("devices")

    # Create the ownership foreign key only if it is missing.
    if not any(
        fk["name"] == "fk_devices_user_id_users"
        for fk in foreign_keys
    ):
        op.create_foreign_key(
            "fk_devices_user_id_users",
            "devices",
            "users",
            ["user_id"],
            ["user_id"],
            ondelete="RESTRICT",
        )

    # Re-inspect to check the indexes currently present.
    inspector = sa.inspect(op.get_bind())
    indexes = inspector.get_indexes("devices")

    # Create the user ownership index only if it is missing.
    if not any(
        index["name"] == "idx_device_user"
        for index in indexes
    ):
        op.create_index(
            "idx_device_user",
            "devices",
            ["user_id"],
            unique=False,
        )



def downgrade() -> None:
    """Remove device ownership and split the migration heads again."""
    op.drop_index("idx_device_user", table_name="devices")
    op.drop_constraint(
        "fk_devices_user_id_users",
        "devices",
        type_="foreignkey",
    )
    op.drop_column("devices", "user_id")
