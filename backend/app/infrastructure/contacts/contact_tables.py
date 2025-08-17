"""
Contact domain table definitions for SQLAlchemy.

Defines the database tables for the contacts domain using SQLAlchemy Core.
These tables are registered with the metadata for migration and ORM usage.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)

from app.infrastructure.database_metadata import metadata

# Contacts table
contacts_table = Table(
    "contacts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("first_name", String(100), nullable=False),
    Column("last_name", String(100), nullable=True),
    Column("middle_name", String(100), nullable=True),
    Column("nick_name", String(100), nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
)

# Contact methods table (email, phone, etc.)
contact_methods_table = Table(
    "contact_methods",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "contact_id",
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("method_type", String(20), nullable=False),
    Column("value", Text, nullable=False),
    Column("label", String(50), nullable=True),
    Column("is_primary", Boolean, server_default=text("false"), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
    CheckConstraint(
        "method_type IN ('email', 'phone')", name="ck_contact_methods_method_type"
    ),
)

# Contact addresses table
contact_addresses_table = Table(
    "contact_addresses",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "contact_id",
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("label", String(50), nullable=True),
    Column("street_line_1", String(255), nullable=False),
    Column("street_line_2", String(255), nullable=True),
    Column("locality", String(100), nullable=True),
    Column("region", String(100), nullable=True),
    Column("postal_code", String(20), nullable=True),
    Column("country_code", String(2), nullable=False),
    Column("is_primary", Boolean, server_default=text("false"), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
)

# Contact notes table
contact_notes_table = Table(
    "contact_notes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "contact_id",
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("content", Text, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
)

# Tags table
tags_table = Table(
    "tags",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
    Column(
        "parent_id", Integer, ForeignKey("tags.id", ondelete="SET NULL"), nullable=True
    ),
    Column("color", String(7), nullable=True),
    Column("description", Text, nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
    UniqueConstraint("name"),
    CheckConstraint("name ~ '^[a-zA-Z0-9_&-]+$'", name="ck_tags_name_format"),
)

# Contact tags table (many-to-many)
contact_tags_table = Table(
    "contact_tags",
    metadata,
    Column(
        "contact_id",
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
)

# Contact field history table
contact_field_history_table = Table(
    "contact_field_history",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "contact_id",
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("field_name", String(100), nullable=False),
    Column("old_value", Text, nullable=True),
    Column("new_value", Text, nullable=True),
    Column("changed_by", String(100), nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
)

# Contact edit event table
contact_edit_event_table = Table(
    "contact_edit_event",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "contact_id",
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("event_type", String(50), nullable=False),
    Column("event_data", Text, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
)

# Contact relationships table
contact_relationships_table = Table(
    "contact_relationships",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "from_contact_id",
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "to_contact_id",
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("relationship_type", String(20), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
    CheckConstraint(
        "relationship_type IN ('partner', 'child', 'parent', 'sibling', 'friend', 'colleague', 'family', 'other')",
        name="ck_contact_relationships_relationship_type",
    ),
    CheckConstraint(
        "from_contact_id != to_contact_id",
        name="ck_contact_relationships_no_self_reference",
    ),
    UniqueConstraint(
        "from_contact_id",
        "to_contact_id",
        "relationship_type",
        name="uq_contact_relationships_unique_relationship",
    ),
)
