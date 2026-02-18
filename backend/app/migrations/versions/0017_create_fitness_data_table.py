"""Create journal_fitness_data table for FITNESS type

Revision ID: 0017
Revises: 0016
Create Date: 2026-02-17 08:30:00.000000

This migration creates the journal_fitness_data table for ITER4.5-002:
- journal_fitness_data: FITNESS type data (fitness activity tracking)

Type detection: A journal has the FITNESS type if a row exists in the
journal_fitness_data table for that journal_id.

The FITNESS type is a base type with no dependencies, supporting all fitness
and outdoor activities including running, cycling, hiking, swimming, etc.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Constants from journal domain
MAX_STRAVA_ACTIVITY_ID_LENGTH = 255


def upgrade() -> None:
    """Create journal_fitness_data table."""

    # Create journal_fitness_data table (FITNESS type)
    op.create_table(
        "journal_fitness_data",
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey("journals.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
            comment="FK to journals - PK ensures one-to-one relationship",
        ),
        sa.Column(
            "heart_rate_avg",
            sa.Integer(),
            nullable=True,
            comment="Average heart rate in BPM",
        ),
        sa.Column(
            "heart_rate_max",
            sa.Integer(),
            nullable=True,
            comment="Maximum heart rate in BPM",
        ),
        sa.Column(
            "distance",
            sa.Integer(),
            nullable=True,
            comment="Distance in meters",
        ),
        sa.Column(
            "elevation_gain",
            sa.Integer(),
            nullable=True,
            comment="Elevation gain in meters",
        ),
        sa.Column(
            "elevation_loss",
            sa.Integer(),
            nullable=True,
            comment="Elevation loss in meters",
        ),
        sa.Column(
            "duration",
            sa.Integer(),
            nullable=True,
            comment="Duration in seconds",
        ),
        sa.Column(
            "calories",
            sa.Integer(),
            nullable=True,
            comment="Calories burned",
        ),
        sa.Column(
            "gpx_track_data",
            sa.TEXT(),
            nullable=True,
            comment="GPX track data as XML text",
        ),
        sa.Column(
            "strava_activity_id",
            sa.VARCHAR(length=MAX_STRAVA_ACTIVITY_ID_LENGTH),
            nullable=True,
            comment="Strava activity ID for integration (Iteration 5)",
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

    # Add check constraints for positive values
    op.create_check_constraint(
        "ck_fitness_heart_rate_avg_positive",
        "journal_fitness_data",
        "heart_rate_avg IS NULL OR heart_rate_avg >= 0",
    )
    op.create_check_constraint(
        "ck_fitness_heart_rate_max_positive",
        "journal_fitness_data",
        "heart_rate_max IS NULL OR heart_rate_max >= 0",
    )
    op.create_check_constraint(
        "ck_fitness_distance_positive",
        "journal_fitness_data",
        "distance IS NULL OR distance >= 0",
    )
    op.create_check_constraint(
        "ck_fitness_elevation_gain_positive",
        "journal_fitness_data",
        "elevation_gain IS NULL OR elevation_gain >= 0",
    )
    op.create_check_constraint(
        "ck_fitness_elevation_loss_positive",
        "journal_fitness_data",
        "elevation_loss IS NULL OR elevation_loss >= 0",
    )
    op.create_check_constraint(
        "ck_fitness_duration_positive",
        "journal_fitness_data",
        "duration IS NULL OR duration >= 0",
    )
    op.create_check_constraint(
        "ck_fitness_calories_positive",
        "journal_fitness_data",
        "calories IS NULL OR calories >= 0",
    )


def downgrade() -> None:
    """Drop journal_fitness_data table."""
    op.drop_table("journal_fitness_data")
