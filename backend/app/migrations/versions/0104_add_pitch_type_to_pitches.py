"""add_pitch_type_to_pitches

Revision ID: 0104
Revises: 0103
Create Date: 2026-07-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0104"
down_revision: str | None = "0103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        "abseil_pitches", sa.Column("pitch_type", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "template_pitches", sa.Column("pitch_type", sa.String(length=50), nullable=True)
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column("template_pitches", "pitch_type")
    op.drop_column("abseil_pitches", "pitch_type")
