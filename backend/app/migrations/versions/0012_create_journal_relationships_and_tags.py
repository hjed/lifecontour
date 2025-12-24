"""Create ITER4-004 journal relationships and tags tables

Revision ID: 0012
Revises: 0011
Create Date: 2025-12-19 12:00:00.000000

This migration creates the supporting tables for ITER4-004:
- journal_tags: Hierarchical tag system for journals
- journal_tag_assignments: Assignment of tags to journals
- journal_contact_relationships: Relationships between journals and contacts

Relationship types: PARTICIPANT, INVITEE, MENTION, ABOUT
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Create journal_tags table
    op.create_table(
        "journal_tags",
        sa.Column(
            "id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("color", sa.String(7), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["parent_id"], ["journal_tags.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_journal_tags_name"),
    )

    # Create journal_tag_assignments table
    op.create_table(
        "journal_tag_assignments",
        sa.Column("journal_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["journal_tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("journal_id", "tag_id"),
    )

    # Create journal_contact_relationships table
    op.create_table(
        "journal_contact_relationships",
        sa.Column("journal_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("relationship_type", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "relationship_type IN ('PARTICIPANT', 'INVITEE', 'MENTION', 'ABOUT')",
            name="ck_journal_contact_relationships_type",
        ),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("journal_id", "contact_id", "relationship_type"),
    )

    # Create indexes for better query performance
    op.create_index(
        "ix_journal_tags_parent_id",
        "journal_tags",
        ["parent_id"],
    )
    op.create_index(
        "ix_journal_tag_assignments_tag_id",
        "journal_tag_assignments",
        ["tag_id"],
    )
    op.create_index(
        "ix_journal_contact_relationships_contact_id",
        "journal_contact_relationships",
        ["contact_id"],
    )
    op.create_index(
        "ix_journal_contact_relationships_type",
        "journal_contact_relationships",
        ["relationship_type"],
    )


def downgrade() -> None:
    """Downgrade database schema."""
    # Drop indexes
    op.drop_index("ix_journal_contact_relationships_type")
    op.drop_index("ix_journal_contact_relationships_contact_id")
    op.drop_index("ix_journal_tag_assignments_tag_id")
    op.drop_index("ix_journal_tags_parent_id")

    # Drop tables
    op.drop_table("journal_contact_relationships")
    op.drop_table("journal_tag_assignments")
    op.drop_table("journal_tags")
