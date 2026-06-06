"""Add photo_url column to contacts table

Revision ID: 0083
Revises: 0082
Create Date: 2026-06-06 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0083"
down_revision: str | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("photo_url", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contacts", "photo_url")
