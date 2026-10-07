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
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.infrastructure.database_metadata import metadata

# Contacts table
contacts_table = Table(
    "contacts",
    metadata,
    Column("id", Integer, primary_key=True),
    # The owner. Nullable until every writer stamps one (migration 0124).
    Column("user_id", String(50), nullable=True),
    Column("first_name", String(100), nullable=False),
    Column("last_name", String(100), nullable=True),
    Column("middle_name", String(100), nullable=True),
    Column("nick_name", String(100), nullable=True),
    Column("company", String(200), nullable=True),
    Column("job_title", String(200), nullable=True),
    Column("photo_url", String(500), nullable=True),
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

Index("idx_contacts_user_id", contacts_table.c.user_id)

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
    Column("is_archived", Boolean, server_default=text("false"), nullable=False),
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
    CheckConstraint(
        "NOT (is_primary AND is_archived)",
        name="ck_contact_methods_archived_not_primary",
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
    Column("is_archived", Boolean, server_default=text("false"), nullable=False),
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
        "NOT (is_primary AND is_archived)",
        name="ck_contact_addresses_archived_not_primary",
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
    CheckConstraint(
        "name ~ '^[a-zA-Z0-9_&-]+(/[a-zA-Z0-9_&-]+)*$'", name="ck_tags_name_format"
    ),
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

# Entity-agnostic field history table (shared by contacts, journals and tasks).
field_history_table = Table(
    "field_history",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("entity_type", String(50), nullable=False),
    Column("entity_id", Integer, nullable=False),
    Column("field_name", String(100), nullable=False),
    Column("old_value", Text, nullable=True),
    Column("new_value", Text, nullable=True),
    Column("changed_by", String(100), nullable=True),
    Column("source", String(50), nullable=False, server_default=text("'system'")),
    Column("event_id", String, nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    ),
    # Who owns the entity this row describes. Nullable and deliberately
    # half-populated: journal and contact history reads authorise by loading the
    # aggregate, so their rows carry nothing here. **Task rows do**, because a
    # task is hard-deleted and its history has to stay both readable and
    # owner-scoped once there is no ``tasks`` row left to ask. Not the same as
    # ``changed_by``, which records who acted.
    Column("user_id", String(50), nullable=True),
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
        nullable=True,
    ),
    Column("relationship_type", String(20), nullable=False),
    Column("to_user", Boolean, server_default=text("false"), nullable=False),
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
        "(to_user = true AND to_contact_id IS NULL) OR (to_user = false AND to_contact_id IS NOT NULL)",
        name="ck_contact_relationships_target_consistency",
    ),
    CheckConstraint(
        "to_user = true OR from_contact_id != to_contact_id",
        name="ck_contact_relationships_no_self_reference",
    ),
    # Unique constraints are partial indexes defined below
)

Index(
    "uq_contact_relationships_contact_target",
    contact_relationships_table.c.from_contact_id,
    contact_relationships_table.c.to_contact_id,
    contact_relationships_table.c.relationship_type,
    unique=True,
    postgresql_where=contact_relationships_table.c.to_user.is_(False),
)

Index(
    "uq_contact_relationships_user_target",
    contact_relationships_table.c.from_contact_id,
    contact_relationships_table.c.relationship_type,
    unique=True,
    postgresql_where=contact_relationships_table.c.to_user.is_(True),
)

# Custom date types table
custom_date_types_table = Table(
    "custom_date_types",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False, unique=True),
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

# Contact important dates table
contact_important_dates_table = Table(
    "contact_important_dates",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "contact_id",
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("date_type", String(30), nullable=False),
    Column("precision", String(10), nullable=False),
    Column("year", Integer, nullable=True),
    Column("month", Integer, nullable=True),
    Column("day", Integer, nullable=True),
    Column(
        "custom_date_type_id",
        Integer,
        ForeignKey("custom_date_types.id"),
        nullable=True,
    ),
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
        "date_type IN ('birthday', 'marriage_anniversary', 'work_anniversary', 'first_met', 'custom')",
        name="ck_important_dates_date_type",
    ),
    CheckConstraint(
        "precision IN ('full', 'day_month', 'year')",
        name="ck_important_dates_precision",
    ),
    CheckConstraint(
        "month IS NULL OR (month >= 1 AND month <= 12)",
        name="ck_important_dates_month",
    ),
    CheckConstraint(
        "day IS NULL OR (day >= 1 AND day <= 31)",
        name="ck_important_dates_day",
    ),
    CheckConstraint(
        "precision != 'full' OR (year IS NOT NULL AND month IS NOT NULL AND day IS NOT NULL)",
        name="ck_important_dates_full_precision",
    ),
    CheckConstraint(
        "precision != 'day_month' OR (year IS NULL AND month IS NOT NULL AND day IS NOT NULL)",
        name="ck_important_dates_day_month_precision",
    ),
    CheckConstraint(
        "precision != 'year' OR (year IS NOT NULL AND month IS NULL AND day IS NULL)",
        name="ck_important_dates_year_precision",
    ),
    CheckConstraint(
        "date_type != 'custom' OR custom_date_type_id IS NOT NULL",
        name="ck_important_dates_custom_type_id",
    ),
    CheckConstraint(
        "date_type = 'custom' OR custom_date_type_id IS NULL",
        name="ck_important_dates_non_custom_type_id",
    ),
)

Index(
    "uq_contact_birthday",
    contact_important_dates_table.c.contact_id,
    unique=True,
    postgresql_where=(contact_important_dates_table.c.date_type == "birthday"),
)

# Contact summaries table (AI-generated interaction summaries)
contact_summaries_table = Table(
    "contact_summaries",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "contact_id",
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("summary_text", Text, nullable=True),
    Column(
        "follow_up_suggestions",
        JSONB,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    ),
    Column("status", String(30), server_default=text("'pending'"), nullable=False),
    Column("is_disabled", Boolean, server_default=text("false"), nullable=False),
    # Why generation is disabled: 'user' (sticky) or 'low_activity' (an
    # auto-pause re-evaluated on refresh). NULL exactly when enabled.
    Column("disabled_reason", String(30), nullable=True),
    Column("is_user_override", Boolean, server_default=text("false"), nullable=False),
    Column("user_override_text", Text, nullable=True),
    Column("generated_at", DateTime(timezone=True), nullable=True),
    # Rolling-debounce marker for buffered summary refreshes: timestamp of the
    # most recent automated refresh request, cleared when the sweeper dispatches
    # generation. NULL means no refresh is pending.
    Column("refresh_requested_at", DateTime(timezone=True), nullable=True),
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
        "status IN ('pending', 'generating', 'generated', 'failed', 'disabled')",
        name="ck_contact_summaries_status",
    ),
    CheckConstraint(
        "disabled_reason IN ('user', 'low_activity')",
        name="ck_contact_summaries_disabled_reason",
    ),
    CheckConstraint(
        "is_disabled = (disabled_reason IS NOT NULL)",
        name="ck_contact_summaries_disabled_reason_matches_flag",
    ),
)
