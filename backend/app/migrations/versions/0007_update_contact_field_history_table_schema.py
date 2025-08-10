"""Update contact_field_history table schema

Revision ID: 0007
Revises: 0006
Create Date: 2025-08-10 10:35:20.412382

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Add entity_type and entity_id columns to contact_field_history table
    op.add_column(
        "contact_field_history",
        sa.Column("entity_type", sa.VARCHAR(length=50), nullable=True),
    )
    op.add_column(
        "contact_field_history", sa.Column("entity_id", sa.Integer(), nullable=True)
    )

    # Migrate existing data: set entity_type='contact' and entity_id=contact_id
    op.execute("""
        UPDATE contact_field_history
        SET entity_type = 'contact', entity_id = contact_id
        WHERE entity_type IS NULL
    """)

    # Make the new columns non-nullable
    op.alter_column("contact_field_history", "entity_type", nullable=False)
    op.alter_column("contact_field_history", "entity_id", nullable=False)

    # Drop the old contact_id column since we now use entity_id
    op.drop_constraint(
        "contact_field_history_contact_id_fkey",
        "contact_field_history",
        type_="foreignkey",
    )
    op.drop_column("contact_field_history", "contact_id")


def downgrade() -> None:
    """Downgrade database schema."""
    # Add back contact_id column
    op.add_column(
        "contact_field_history", sa.Column("contact_id", sa.Integer(), nullable=True)
    )

    # Migrate data back: set contact_id from entity_id where entity_type='contact'
    op.execute("""
        UPDATE contact_field_history
        SET contact_id = entity_id
        WHERE entity_type = 'contact'
    """)

    # Make contact_id non-nullable and add foreign key
    op.alter_column("contact_field_history", "contact_id", nullable=False)
    op.create_foreign_key(
        "contact_field_history_contact_id_fkey",
        "contact_field_history",
        "contacts",
        ["contact_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Drop the new columns
    op.drop_column("contact_field_history", "entity_id")
    op.drop_column("contact_field_history", "entity_type")
