"""Add indoor flag to journal_climbing_data and allow top_rope climbing type

Revision ID: 0090
Revises: 0089
Create Date: 2026-06-17 00:00:00.000000

Two related changes to journal_climbing_data:

- Adds a non-nullable ``indoor`` boolean (default FALSE). Indoor is a separate
  flag rather than a climbing_type value because a climb of any style can be
  indoor or outdoor. Existing rows backfill to FALSE.
- Widens the ``ck_climbing_type_valid`` CHECK constraint to also permit
  ``top_rope`` alongside sport/trad/bouldering.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0090"
down_revision: str | None = "0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "journal_climbing_data"
_TYPE_CHECK = "ck_climbing_type_valid"


def upgrade() -> None:
    """Add indoor column and widen climbing_type CHECK to include top_rope."""
    op.add_column(
        _TABLE,
        sa.Column(
            "indoor",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Whether the climb was indoors (independent of climbing_type)",
        ),
    )

    op.drop_constraint(_TYPE_CHECK, _TABLE, type_="check")
    op.create_check_constraint(
        _TYPE_CHECK,
        _TABLE,
        "climbing_type IS NULL OR "
        "climbing_type IN ('sport', 'trad', 'bouldering', 'top_rope')",
    )


def downgrade() -> None:
    """Restore the original climbing_type CHECK and drop the indoor column."""
    op.drop_constraint(_TYPE_CHECK, _TABLE, type_="check")

    # Rows created with the new top_rope value would violate the stricter
    # original CHECK; null them out before re-adding it so the downgrade
    # doesn't fail on existing data.
    op.execute(
        f"UPDATE {_TABLE} SET climbing_type = NULL WHERE climbing_type = 'top_rope'"
    )

    op.create_check_constraint(
        _TYPE_CHECK,
        _TABLE,
        "climbing_type IS NULL OR climbing_type IN ('sport', 'trad', 'bouldering')",
    )

    op.drop_column(_TABLE, "indoor")
