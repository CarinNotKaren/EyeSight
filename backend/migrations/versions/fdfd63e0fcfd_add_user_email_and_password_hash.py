"""Add email and password hash columns safely."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "fdfd63e0fcfd"
down_revision: Union[str, Sequence[str], None] = "9ae7a37f57bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add authentication columns, tolerating the parallel legacy migration."""
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("users")}

    if "email" not in columns:
        op.add_column("users", sa.Column("email", sa.String(255), nullable=True))
    if "password_hash" not in columns:
        op.add_column(
            "users",
            sa.Column("password_hash", sa.String(255), nullable=True),
        )

    # Backfill old rows before enforcing non-null values.
    op.execute("""
        UPDATE users
        SET
            email = CONCAT('legacy-user-', user_id, '@migration.invalid'),
            password_hash = '!'
        WHERE email IS NULL OR password_hash IS NULL
    """)

    op.alter_column(
        "users", "email",
        existing_type=sa.String(255),
        nullable=False,
    )
    op.alter_column(
        "users", "password_hash",
        existing_type=sa.String(255),
        nullable=False,
    )

    inspector = sa.inspect(op.get_bind())
    has_email_unique = any(
        item.get("column_names") == ["email"]
        for item in inspector.get_unique_constraints("users")
    )
    if not has_email_unique:
        op.create_unique_constraint("uq_users_email", "users", ["email"])


def downgrade() -> None:
    """Remove authentication columns when rolling back this migration."""
    inspector = sa.inspect(op.get_bind())
    has_email_unique = any(
        item.get("column_names") == ["email"]
        for item in inspector.get_unique_constraints("users")
    )
    if has_email_unique:
        op.drop_constraint("uq_users_email", "users", type_="unique")

    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "password_hash" in columns:
        op.drop_column("users", "password_hash")
    if "email" in columns:
        op.drop_column("users", "email")
