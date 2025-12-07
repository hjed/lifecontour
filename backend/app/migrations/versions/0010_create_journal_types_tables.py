"""Create journal types tables (calendars, calendar_info, mood_data)

Revision ID: 0010
Revises: 0009
Create Date: 2024-12-07 14:00:00.000000

This migration creates the supporting tables for ITER4-002 journal types:
- calendars: Calendar entities for organizing journals
- journal_calendar_info: EVENT type data (calendar-specific info)
- journal_mood_data: MOOD_RATING type data (mood and energy tracking)

Type detection: A journal has a type if a row exists in the corresponding
type table (e.g., EVENT type if journal_calendar_info row exists).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Constants from journal domain
MAX_CALENDAR_NAME_LENGTH = 100
MAX_CALENDAR_COLOR_LENGTH = 7  # #RRGGBB
MAX_GOOGLE_CALENDAR_ID_LENGTH = 255
MAX_LOCATION_LENGTH = 500
MAX_MOOD_LABEL_LENGTH = 50
MIN_MOOD_VALUE = 1
MAX_MOOD_VALUE = 10
MIN_ENERGY_LEVEL = 1
MAX_ENERGY_LEVEL = 10


def upgrade() -> None:
    """Create calendars, journal_calendar_info, and journal_mood_data tables."""

    # Create calendars table
    op.create_table(
        "calendars",
        sa.Column(
            "id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "user_id",
            sa.VARCHAR(length=50),
            nullable=False,
            comment="User identifier (FK to users when table exists)",
        ),
        sa.Column(
            "name",
            sa.VARCHAR(length=MAX_CALENDAR_NAME_LENGTH),
            nullable=False,
            comment="Calendar display name",
        ),
        sa.Column(
            "color",
            sa.VARCHAR(length=MAX_CALENDAR_COLOR_LENGTH),
            nullable=False,
            comment="Hex color for display (#RRGGBB format)",
        ),
        sa.Column(
            "description",
            sa.TEXT(),
            nullable=True,
            comment="Optional calendar description",
        ),
        sa.Column(
            "is_synced_to_google",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Whether to sync events to Google Calendar",
        ),
        sa.Column(
            "google_calendar_id",
            sa.VARCHAR(length=MAX_GOOGLE_CALENDAR_ID_LENGTH),
            nullable=True,
            comment="Google Calendar ID for sync",
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
        sa.PrimaryKeyConstraint("id"),
    )

    # Indexes for calendars table
    op.create_index("idx_calendars_user_id", "calendars", ["user_id"])
    op.create_index(
        "idx_calendars_google_sync",
        "calendars",
        ["user_id", "is_synced_to_google"],
        postgresql_where=sa.text("is_synced_to_google = true"),
    )

    # Create journal_calendar_info table (EVENT type)
    op.create_table(
        "journal_calendar_info",
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey("journals.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
            comment="FK to journals - PK ensures one-to-one relationship",
        ),
        sa.Column(
            "calendar_id",
            sa.UUID(),
            sa.ForeignKey("calendars.id", ondelete="CASCADE"),
            nullable=False,
            comment="Required calendar reference",
        ),
        sa.Column(
            "start_time",
            sa.TIME(),
            nullable=True,
            comment="Start time (null for all-day events)",
        ),
        sa.Column(
            "end_time",
            sa.TIME(),
            nullable=True,
            comment="End time (null for all-day events)",
        ),
        sa.Column(
            "is_all_day",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Whether this is an all-day event",
        ),
        sa.Column(
            "location",
            sa.VARCHAR(length=MAX_LOCATION_LENGTH),
            nullable=True,
            comment="Optional event location",
        ),
        sa.Column(
            "sync_invitees",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Whether to sync invitees to Google Calendar",
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
        sa.PrimaryKeyConstraint("journal_id"),
    )

    # Indexes for journal_calendar_info table
    op.create_index(
        "idx_journal_calendar_info_calendar_id",
        "journal_calendar_info",
        ["calendar_id"],
    )

    # Create journal_mood_data table (MOOD_RATING type)
    op.create_table(
        "journal_mood_data",
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey("journals.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
            comment="FK to journals - PK ensures one-to-one relationship",
        ),
        sa.Column(
            "mood_value",
            sa.Integer(),
            nullable=True,
            comment=f"Mood rating ({MIN_MOOD_VALUE}-{MAX_MOOD_VALUE} scale)",
        ),
        sa.Column(
            "mood_label",
            sa.VARCHAR(length=MAX_MOOD_LABEL_LENGTH),
            nullable=True,
            comment="Text description of mood (e.g., happy, anxious)",
        ),
        sa.Column(
            "energy_level",
            sa.Integer(),
            nullable=True,
            comment=f"Energy rating ({MIN_ENERGY_LEVEL}-{MAX_ENERGY_LEVEL} scale)",
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
        sa.PrimaryKeyConstraint("journal_id"),
        # Check constraints for valid ranges
        sa.CheckConstraint(
            f"mood_value IS NULL OR (mood_value >= {MIN_MOOD_VALUE} AND mood_value <= {MAX_MOOD_VALUE})",
            name="ck_journal_mood_data_mood_value_range",
        ),
        sa.CheckConstraint(
            f"energy_level IS NULL OR (energy_level >= {MIN_ENERGY_LEVEL} AND energy_level <= {MAX_ENERGY_LEVEL})",
            name="ck_journal_mood_data_energy_level_range",
        ),
    )


def downgrade() -> None:
    """Drop journal types tables."""

    # Drop journal_mood_data table
    op.drop_table("journal_mood_data")

    # Drop journal_calendar_info table (drop index first)
    op.drop_index(
        "idx_journal_calendar_info_calendar_id", table_name="journal_calendar_info"
    )
    op.drop_table("journal_calendar_info")

    # Drop calendars table (drop indexes first)
    op.drop_index("idx_calendars_google_sync", table_name="calendars")
    op.drop_index("idx_calendars_user_id", table_name="calendars")
    op.drop_table("calendars")
