"""add_notes_to_abseil_pitches

Revision ID: a81ba98c675d
Revises: 0083
Create Date: 2026-06-06 22:06:31.318937

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0084"
down_revision: str | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("abseil_pitches", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column("abseil_pitches", "notes")
