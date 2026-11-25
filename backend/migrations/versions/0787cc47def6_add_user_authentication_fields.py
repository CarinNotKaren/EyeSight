"""Add user authentication fields safely for existing installations."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0787cc47def6"
down_revision: Union[str, Sequence[str], None] = "9ae7a37f57bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add email/password columns without breaking existing user rows."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("users")}

    # Add missing columns as nullable so legacy rows can be backfilled.
    if "email" not in columns:
        op.add_column("users", sa.Column("email", sa.String(255), nullable=True))
    if "password_hash" not in columns:
        op.add_column(
            "users",
            sa.Column("password_hash", sa.String(255), nullable=True),
        )

    # Existing accounts receive unique, non-login placeholder credentials.
    op.execute("""
        UPDATE users
        SET
            email = CONCAT('legacy-user-', user_id, '@migration.invalid'),
            password_hash = '!'
        WHERE email IS NULL OR password_hash IS NULL
    """)

    # Enforce the same non-null contract regardless of which parallel
    # authentication migration ran first.
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

    # Avoid recreating the same unique constraint if the sibling migration
    # has already added it.
    inspector = sa.inspect(op.get_bind())
    has_email_unique = any(
        item.get("column_names") == ["email"]
        for item in inspector.get_unique_constraints("users")
    )
    if not has_email_unique:
        op.create_unique_constraint("uq_users_email", "users", ["email"])


def downgrade() -> None:
    """Remove the authentication fields."""
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
