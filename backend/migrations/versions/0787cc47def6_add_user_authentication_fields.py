"""Add user authentication fields

Revision ID: 0787cc47def6
Revises: 9ae7a37f57bc
Create Date: 2026-11-07 15:15:27.331986

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0787cc47def6'
down_revision: Union[str, Sequence[str], None] = '9ae7a37f57bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""

    # 1. Add the new columns as nullable temporarily.
    # This prevents problems with existing users in the database.
    op.add_column(
        'users',
        sa.Column('email', sa.String(length=255), nullable=True)
    )

    op.add_column(
        'users',
        sa.Column('password_hash', sa.String(length=255), nullable=True)
    )

    # 2. Give existing users unique placeholder emails.
    # The .invalid domain is reserved and cannot be used as a real email domain.
    # The '!' password value is an unusable placeholder, not a real password hash.
    op.execute("""
        UPDATE users
        SET
            email = CONCAT('legacy-user-', user_id, '@migration.invalid'),
            password_hash = '!'
        WHERE email IS NULL OR password_hash IS NULL
    """)

    # 3. Make both columns mandatory now that existing rows have values.
    op.alter_column(
        'users',
        'email',
        existing_type=sa.String(length=255),
        nullable=False
    )

    op.alter_column(
        'users',
        'password_hash',
        existing_type=sa.String(length=255),
        nullable=False
    )

    # 4. Add a named unique constraint to prevent duplicate email addresses.
    op.create_unique_constraint(
        'uq_users_email',
        'users',
        ['email']
    )


def downgrade() -> None:
    """Revert the authentication fields."""

    # Remove the unique constraint before dropping the email column.
    op.drop_constraint(
        'uq_users_email',
        'users',
        type_='unique'
    )

    # Remove the authentication columns.
    op.drop_column('users', 'password_hash')
    op.drop_column('users', 'email')