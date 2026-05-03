"""add strava_webhook_verify_token to user_strava_auth

Revision ID: 0059
Revises: 0058
Create Date: 2026-05-03 00:25:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add strava_webhook_verify_token column to user_strava_auth."""
    op.add_column(
        "user_strava_auth",
        sa.Column(
            "strava_webhook_verify_token",
            sa.String(length=100),
            nullable=True,
            comment="Token used to verify Strava webhook subscription handshake",
        ),
    )


def downgrade() -> None:
    """Remove strava_webhook_verify_token column from user_strava_auth."""
    op.drop_column("user_strava_auth", "strava_webhook_verify_token")
