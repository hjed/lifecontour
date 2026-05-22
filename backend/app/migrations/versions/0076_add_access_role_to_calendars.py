"""add access_role to calendars table

Revision ID: 0076
Revises: 0075
Create Date: 2026-05-22 20:00:00.000000

Adds an access_role column to the calendars table to track the user's
permission level for each Google Calendar (owner, writer, reader,
freeBusyReader). This enables the system to skip outbound sync for
read-only calendars.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0076"
down_revision: str | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_ACCESS_ROLE_LENGTH = 50


def upgrade() -> None:
    """Add access_role column to calendars table."""
    op.add_column(
        "calendars",
        sa.Column(
            "access_role",
            sa.VARCHAR(length=MAX_ACCESS_ROLE_LENGTH),
            nullable=True,
            comment="Google Calendar access role (owner, writer, reader, freeBusyReader)",
        ),
    )


def downgrade() -> None:
    """Remove access_role column from calendars table."""
    op.drop_column("calendars", "access_role")
