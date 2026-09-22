"""create contact suggestion ignores table

Revision ID: 0117
Revises: 0116
Create Date: 2026-09-22 12:00:00.000000

A user's persistent list of participant emails they do not want suggested as
contacts. A row's presence hides the email from that user's suggestions;
``provenance`` records where the ignore came from (UI / MCP).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0117"
down_revision: str | None = "0116"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "contact_suggestion_ignores",
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "email"),
        sa.CheckConstraint(
            "email = lower(email)",
            name="ck_contact_suggestion_ignores_lower_email",
        ),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_table("contact_suggestion_ignores")
