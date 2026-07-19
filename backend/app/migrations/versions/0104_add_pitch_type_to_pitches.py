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

_PITCH_TYPE_CHECK = "pitch_type IN ('abseil', 'jump', 'down_climb')"


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        "abseil_pitches", sa.Column("pitch_type", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "template_pitches", sa.Column("pitch_type", sa.String(length=50), nullable=True)
    )
    # NULL passes a CHECK constraint, so these permit the legacy "no type"
    # rows while keeping stored values aligned with VALID_PITCH_TYPES.
    op.create_check_constraint(
        "ck_abseil_pitches_pitch_type", "abseil_pitches", _PITCH_TYPE_CHECK
    )
    op.create_check_constraint(
        "ck_template_pitches_pitch_type", "template_pitches", _PITCH_TYPE_CHECK
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_constraint(
        "ck_template_pitches_pitch_type", "template_pitches", type_="check"
    )
    op.drop_constraint("ck_abseil_pitches_pitch_type", "abseil_pitches", type_="check")
    op.drop_column("template_pitches", "pitch_type")
    op.drop_column("abseil_pitches", "pitch_type")
