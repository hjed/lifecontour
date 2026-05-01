"""add provenance source to contact history

Revision ID: ab4c2dc86432
Revises: 0052
Create Date: 2026-04-30 22:57:18.039670

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Add the column with a default value of 'system'
    op.add_column(
        "contact_field_history",
        sa.Column(
            "source", sa.String(length=50), nullable=False, server_default="system"
        ),
    )

    # Backfill based on existing changed_by column
    # For google sync
    op.execute(
        "UPDATE contact_field_history SET source = 'google_contacts' WHERE changed_by = 'google_sync';"
    )
    # For UI
    op.execute(
        "UPDATE contact_field_history SET source = 'ui' WHERE changed_by = 'ui';"
    )
    # For MCP
    op.execute(
        "UPDATE contact_field_history SET source = 'mcp' WHERE changed_by = 'mcp';"
    )
    # For Summary Regeneration
    op.execute(
        "UPDATE contact_field_history SET source = 'summary_regeneration' WHERE changed_by = 'summary_regeneration';"
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column("contact_field_history", "source")
