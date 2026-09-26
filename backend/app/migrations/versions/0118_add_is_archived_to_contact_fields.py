"""add is_archived to contact methods and addresses

Revision ID: 0118
Revises: 0117
Create Date: 2026-09-26 12:00:00.000000

An archived email, phone or address is one the person no longer uses. It is
kept for matching and reference, never synced out to a provider, and can never
be the primary value - enforced here as well as on the entity.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0118"
down_revision: str | None = "0117"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("contact_methods", "contact_addresses")


def upgrade() -> None:
    """Upgrade database schema."""
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "is_archived",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
        )
        op.create_check_constraint(
            f"ck_{table}_archived_not_primary",
            table,
            "NOT (is_primary AND is_archived)",
        )


def downgrade() -> None:
    """Downgrade database schema."""
    for table in _TABLES:
        op.drop_constraint(f"ck_{table}_archived_not_primary", table, type_="check")
        op.drop_column(table, "is_archived")
