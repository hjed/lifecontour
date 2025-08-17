"""Add contact_relationships table

Revision ID: 0008
Revises: 0007
Create Date: 2025-08-16 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Create contact_relationships table
    op.create_table(
        "contact_relationships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("from_contact_id", sa.Integer(), nullable=False),
        sa.Column("to_contact_id", sa.Integer(), nullable=False),
        sa.Column("relationship_type", sa.VARCHAR(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "relationship_type IN ('partner', 'child', 'parent', 'sibling', 'friend', 'colleague', 'family', 'other')",
            name="ck_contact_relationships_relationship_type",
        ),
        sa.CheckConstraint(
            "from_contact_id != to_contact_id",
            name="ck_contact_relationships_no_self_reference",
        ),
        sa.ForeignKeyConstraint(
            ["from_contact_id"], ["contacts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["to_contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "from_contact_id",
            "to_contact_id",
            "relationship_type",
            name="uq_contact_relationships_unique_relationship",
        ),
    )

    # Create indexes for better query performance
    op.create_index(
        "ix_contact_relationships_from_contact_id",
        "contact_relationships",
        ["from_contact_id"],
    )
    op.create_index(
        "ix_contact_relationships_to_contact_id",
        "contact_relationships",
        ["to_contact_id"],
    )


def downgrade() -> None:
    """Downgrade database schema."""
    # Drop indexes
    op.drop_index(
        "ix_contact_relationships_to_contact_id", table_name="contact_relationships"
    )
    op.drop_index(
        "ix_contact_relationships_from_contact_id", table_name="contact_relationships"
    )

    # Drop table
    op.drop_table("contact_relationships")
