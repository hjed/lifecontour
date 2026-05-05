"""create gear maintenance data table

Revision ID: 0065
Revises: 0064
Create Date: 2026-05-05 19:44:16.111678

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0065"
down_revision: str | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "journal_gear_maintenance_data",
        sa.Column("journal_id", sa.Integer(), nullable=False),
        sa.Column("gear_item_id", sa.Uuid(), nullable=False),
        sa.Column("maintenance_type", sa.String(length=100), nullable=False),
        sa.Column(
            "activity_types", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("retirement_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["gear_item_id"], ["gear_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("journal_id"),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table("journal_gear_maintenance_data")
