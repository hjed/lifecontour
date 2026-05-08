"""create_strava_athlete_mappings_table

Revision ID: 0066
Revises: 0065
Create Date: 2026-05-06 23:02:19.426555

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0066"
down_revision: str | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "strava_athlete_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("strava_athlete_id", sa.String(length=255), nullable=False),
        sa.Column("strava_athlete_name", sa.String(length=255), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "strava_athlete_id",
            name="uq_strava_athlete_mappings_user_athlete",
        ),
    )
    op.create_index(
        op.f("ix_strava_athlete_mappings_user_id"),
        "strava_athlete_mappings",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index(
        op.f("ix_strava_athlete_mappings_user_id"), table_name="strava_athlete_mappings"
    )
    op.drop_table("strava_athlete_mappings")
