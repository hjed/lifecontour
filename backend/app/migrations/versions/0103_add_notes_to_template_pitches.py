"""add_notes_to_template_pitches

Revision ID: 0103
Revises: 0102
Create Date: 2026-07-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0103"
down_revision: str | None = "0102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column("template_pitches", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column("template_pitches", "notes")
