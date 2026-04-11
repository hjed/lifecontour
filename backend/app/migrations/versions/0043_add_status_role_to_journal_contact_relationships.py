"""Add status and role columns to journal_contact_relationships

Revision ID: 0043
Revises: 0042
Create Date: 2026-04-11 03:15:00.000000

Adds optional status (attendee RSVP/attendance state) and role (event role)
columns to journal_contact_relationships with CHECK constraints limiting
values to valid enum members. Both columns are nullable for backward
compatibility with existing relationships.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_STATUS_LENGTH = 20
MAX_ROLE_LENGTH = 20


def upgrade() -> None:
    """Add status and role columns with CHECK constraints."""
    op.add_column(
        "journal_contact_relationships",
        sa.Column(
            "status",
            sa.VARCHAR(length=MAX_STATUS_LENGTH),
            nullable=True,
            comment="Attendee status (ATTENDING, ATTENDED, MAYBE, NO_REPLY, DECLINED)",
        ),
    )
    op.add_column(
        "journal_contact_relationships",
        sa.Column(
            "role",
            sa.VARCHAR(length=MAX_ROLE_LENGTH),
            nullable=True,
            comment="Event role (ORGANISER, FACILITATOR_HELPER)",
        ),
    )
    op.create_check_constraint(
        "ck_journal_contact_relationships_status",
        "journal_contact_relationships",
        "status IN ('ATTENDING', 'ATTENDED', 'MAYBE', 'NO_REPLY', 'DECLINED')",
    )
    op.create_check_constraint(
        "ck_journal_contact_relationships_role",
        "journal_contact_relationships",
        "role IN ('ORGANISER', 'FACILITATOR_HELPER')",
    )


def downgrade() -> None:
    """Remove status and role columns and their CHECK constraints."""
    op.drop_constraint(
        "ck_journal_contact_relationships_role",
        "journal_contact_relationships",
        type_="check",
    )
    op.drop_constraint(
        "ck_journal_contact_relationships_status",
        "journal_contact_relationships",
        type_="check",
    )
    op.drop_column("journal_contact_relationships", "role")
    op.drop_column("journal_contact_relationships", "status")
