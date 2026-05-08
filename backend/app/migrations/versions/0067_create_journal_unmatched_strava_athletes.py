"""create journal unmatched strava athletes table

Revision ID: 0067
Revises: 0066
Create Date: 2026-05-08 08:58:14.618547

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0067"
down_revision: str | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "journal_unmatched_strava_athletes",
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey("journals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("strava_athlete_id", sa.String(length=255), nullable=False),
        sa.Column("strava_athlete_name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("journal_id", "strava_athlete_id"),
    )
    op.create_index(
        "ix_journal_unmatched_strava_athletes_strava_athlete_id",
        "journal_unmatched_strava_athletes",
        ["strava_athlete_id"],
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index(
        "ix_journal_unmatched_strava_athletes_strava_athlete_id",
        table_name="journal_unmatched_strava_athletes",
    )
    op.drop_table("journal_unmatched_strava_athletes")
