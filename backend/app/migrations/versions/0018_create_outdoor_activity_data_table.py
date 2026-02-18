"""Create journal_outdoor_activity_data table for OUTDOOR_ACTIVITY type

Revision ID: 0018
Revises: 0017
Create Date: 2026-02-18 12:00:00.000000

This migration creates the journal_outdoor_activity_data table for ITER4.5-003.

Type detection: A journal has the OUTDOOR_ACTIVITY type if a row exists in the
journal_outdoor_activity_data table for that journal_id.

OUTDOOR_ACTIVITY requires the FITNESS type (automatically resolved by the
service layer's type dependency system).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Constants from journal domain
MAX_ACTIVITY_TYPE_LENGTH = 100
MAX_WEATHER_CONDITIONS_LENGTH = 200
MAX_ROLE_LENGTH = 100
MAX_PARTICIPANT_NOTES_LENGTH = 2000


def upgrade() -> None:
    """Create journal_outdoor_activity_data table."""
    op.create_table(
        "journal_outdoor_activity_data",
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey("journals.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
            comment="FK to journals - PK ensures one-to-one relationship",
        ),
        sa.Column(
            "activity_type",
            sa.VARCHAR(length=MAX_ACTIVITY_TYPE_LENGTH),
            nullable=True,
            comment="Type of outdoor activity (e.g. Hiking, Camping)",
        ),
        sa.Column(
            "weather_conditions",
            sa.VARCHAR(length=MAX_WEATHER_CONDITIONS_LENGTH),
            nullable=True,
            comment="Description of weather conditions during the activity",
        ),
        sa.Column(
            "role",
            sa.VARCHAR(length=MAX_ROLE_LENGTH),
            nullable=True,
            comment="Participant's role in the activity",
        ),
        sa.Column(
            "in_leadership_role",
            sa.Boolean(),
            nullable=True,
            comment="Whether the participant was in a leadership role",
        ),
        sa.Column(
            "participant_notes",
            sa.VARCHAR(length=MAX_PARTICIPANT_NOTES_LENGTH),
            nullable=True,
            comment="Notes about other participants",
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


def downgrade() -> None:
    """Drop journal_outdoor_activity_data table."""
    op.drop_table("journal_outdoor_activity_data")
