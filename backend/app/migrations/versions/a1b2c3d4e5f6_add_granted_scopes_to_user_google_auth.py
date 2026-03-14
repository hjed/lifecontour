"""add granted_scopes to user_google_auth

Revision ID: a1b2c3d4e5f6
Revises: 285cd30b6c39
Create Date: 2026-03-13 22:29:47.389164

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "285cd30b6c39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        "user_google_auth", sa.Column("granted_scopes", sa.String(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column("user_google_auth", "granted_scopes")
