"""Add needs_reauth column to user_google_auth

Revision ID: 0042
Revises: 0041
Create Date: 2026-04-11 00:42:00.000000

Adds a needs_reauth boolean flag to user_google_auth. The flag is set
by the Google worker when it detects an invalid_grant response (token
revoked or expired). It is cleared when the user re-authenticates via
the OAuth flow.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add needs_reauth column (default false) to user_google_auth."""
    op.add_column(
        "user_google_auth",
        sa.Column(
            "needs_reauth",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Set when refresh token is revoked; cleared on re-auth",
        ),
    )


def downgrade() -> None:
    """Remove needs_reauth column from user_google_auth."""
    op.drop_column("user_google_auth", "needs_reauth")
