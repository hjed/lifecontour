"""Add is_favourite field to contacts table

Revision ID: 0004
Revises: 0003
Create Date: 2024-06-15 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add is_favourite field to contacts table."""
    # Add is_favourite column with default value of False
    op.add_column(
        "contacts",
        sa.Column("is_favourite", sa.Boolean(), server_default="false", nullable=False),
    )

    # Create index for efficient filtering by favourite status
    op.create_index(
        "ix_contacts_is_favourite", "contacts", ["is_favourite"], unique=False
    )


def downgrade() -> None:
    """Remove is_favourite field from contacts table."""
    # Drop the index first
    op.drop_index("ix_contacts_is_favourite", table_name="contacts")

    # Then drop the column
    op.drop_column("contacts", "is_favourite")
