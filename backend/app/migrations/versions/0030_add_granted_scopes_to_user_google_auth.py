"""add granted_scopes to user_google_auth

Revision ID: 8d687ded575d
Revises: 0029
Create Date: 2026-03-13 22:29:47.389164

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0030"
down_revision: str | None = "0029"
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
