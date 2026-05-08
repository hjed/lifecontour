"""create outdoor training data table

Revision ID: 0067
Revises: 1a7db45da3ca
Create Date: 2026-05-08 19:54:06.947285

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0067"
down_revision: str | None = "1a7db45da3ca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "journal_outdoor_training_data",
        sa.Column("journal_id", sa.Integer(), nullable=False),
        sa.Column(
            "focus_areas", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
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
        sa.PrimaryKeyConstraint("journal_id"),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table("journal_outdoor_training_data")
