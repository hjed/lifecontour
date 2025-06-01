"""Create contacts domain tables

Revision ID: 0002
Revises: 0001
Create Date: 2024-06-01 23:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create contacts domain tables."""

    # Create contacts table
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.VARCHAR(length=100), nullable=False),
        sa.Column("last_name", sa.VARCHAR(length=100), nullable=True),
        sa.Column("middle_name", sa.VARCHAR(length=100), nullable=True),
        sa.Column("nick_name", sa.VARCHAR(length=100), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )

    # Create contact_methods table
    op.create_table(
        "contact_methods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("method_type", sa.VARCHAR(length=20), nullable=False),
        sa.Column("value", sa.TEXT(), nullable=False),
        sa.Column("label", sa.VARCHAR(length=50), nullable=True),
        sa.Column(
            "is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
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
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "method_type IN ('email', 'phone')", name="ck_contact_methods_method_type"
        ),
    )

    # Create contact_addresses table
    op.create_table(
        "contact_addresses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.VARCHAR(length=50), nullable=True),
        sa.Column("street_line_1", sa.VARCHAR(length=255), nullable=False),
        sa.Column("street_line_2", sa.VARCHAR(length=255), nullable=True),
        sa.Column("locality", sa.VARCHAR(length=100), nullable=True),
        sa.Column("region", sa.VARCHAR(length=100), nullable=True),
        sa.Column("postal_code", sa.VARCHAR(length=20), nullable=True),
        sa.Column("country_code", sa.VARCHAR(length=2), nullable=False),
        sa.Column(
            "is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
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
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create contact_notes table
    op.create_table(
        "contact_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.TEXT(), nullable=False),
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
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create tags table
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.VARCHAR(length=100), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("color", sa.VARCHAR(length=7), nullable=True),
        sa.Column("description", sa.TEXT(), nullable=True),
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
        sa.ForeignKeyConstraint(["parent_id"], ["tags.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.CheckConstraint("name ~ '^[a-zA-Z0-9_&-]+$'", name="ck_tags_name_format"),
    )

    # Create contact_tags table (many-to-many)
    op.create_table(
        "contact_tags",
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("contact_id", "tag_id"),
    )

    # Create contact_field_history table
    op.create_table(
        "contact_field_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("field_name", sa.VARCHAR(length=100), nullable=False),
        sa.Column("old_value", sa.TEXT(), nullable=True),
        sa.Column("new_value", sa.TEXT(), nullable=True),
        sa.Column("changed_by", sa.VARCHAR(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create contact_edit_event table
    op.create_table(
        "contact_edit_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.VARCHAR(length=50), nullable=False),
        sa.Column("event_data", sa.TEXT(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for performance
    # Contact indexes
    op.create_index("idx_contacts_first_name", "contacts", ["first_name"])
    op.create_index("idx_contacts_last_name", "contacts", ["last_name"])
    op.create_index("idx_contacts_created_at", "contacts", ["created_at"])

    # Contact methods indexes
    op.create_index("idx_contact_methods_contact_id", "contact_methods", ["contact_id"])
    op.create_index(
        "idx_contact_methods_type_value", "contact_methods", ["method_type", "value"]
    )
    op.create_index(
        "idx_contact_methods_primary", "contact_methods", ["contact_id", "is_primary"]
    )

    # Contact addresses indexes
    op.create_index(
        "idx_contact_addresses_contact_id", "contact_addresses", ["contact_id"]
    )
    op.create_index(
        "idx_contact_addresses_primary",
        "contact_addresses",
        ["contact_id", "is_primary"],
    )

    # Contact notes indexes
    op.create_index("idx_contact_notes_contact_id", "contact_notes", ["contact_id"])
    op.create_index("idx_contact_notes_created_at", "contact_notes", ["created_at"])

    # Tags indexes
    op.create_index("idx_tags_name", "tags", ["name"])
    op.create_index("idx_tags_parent_id", "tags", ["parent_id"])

    # Contact tags indexes
    op.create_index("idx_contact_tags_contact_id", "contact_tags", ["contact_id"])
    op.create_index("idx_contact_tags_tag_id", "contact_tags", ["tag_id"])

    # Contact field history indexes
    op.create_index(
        "idx_contact_field_history_contact_id", "contact_field_history", ["contact_id"]
    )
    op.create_index(
        "idx_contact_field_history_field_name", "contact_field_history", ["field_name"]
    )
    op.create_index(
        "idx_contact_field_history_created_at", "contact_field_history", ["created_at"]
    )

    # Contact edit event indexes
    op.create_index(
        "idx_contact_edit_event_contact_id", "contact_edit_event", ["contact_id"]
    )
    op.create_index("idx_contact_edit_event_type", "contact_edit_event", ["event_type"])
    op.create_index(
        "idx_contact_edit_event_created_at", "contact_edit_event", ["created_at"]
    )


def downgrade() -> None:
    """Drop contacts domain tables."""
    # Drop indexes first
    op.drop_index("idx_contact_edit_event_created_at", table_name="contact_edit_event")
    op.drop_index("idx_contact_edit_event_type", table_name="contact_edit_event")
    op.drop_index("idx_contact_edit_event_contact_id", table_name="contact_edit_event")

    op.drop_index(
        "idx_contact_field_history_created_at", table_name="contact_field_history"
    )
    op.drop_index(
        "idx_contact_field_history_field_name", table_name="contact_field_history"
    )
    op.drop_index(
        "idx_contact_field_history_contact_id", table_name="contact_field_history"
    )

    op.drop_index("idx_contact_tags_tag_id", table_name="contact_tags")
    op.drop_index("idx_contact_tags_contact_id", table_name="contact_tags")

    op.drop_index("idx_tags_parent_id", table_name="tags")
    op.drop_index("idx_tags_name", table_name="tags")

    op.drop_index("idx_contact_notes_created_at", table_name="contact_notes")
    op.drop_index("idx_contact_notes_contact_id", table_name="contact_notes")

    op.drop_index("idx_contact_addresses_primary", table_name="contact_addresses")
    op.drop_index("idx_contact_addresses_contact_id", table_name="contact_addresses")

    op.drop_index("idx_contact_methods_primary", table_name="contact_methods")
    op.drop_index("idx_contact_methods_type_value", table_name="contact_methods")
    op.drop_index("idx_contact_methods_contact_id", table_name="contact_methods")

    op.drop_index("idx_contacts_created_at", table_name="contacts")
    op.drop_index("idx_contacts_last_name", table_name="contacts")
    op.drop_index("idx_contacts_first_name", table_name="contacts")

    # Drop tables
    op.drop_table("contact_edit_event")
    op.drop_table("contact_field_history")
    op.drop_table("contact_tags")
    op.drop_table("tags")
    op.drop_table("contact_notes")
    op.drop_table("contact_addresses")
    op.drop_table("contact_methods")
    op.drop_table("contacts")
