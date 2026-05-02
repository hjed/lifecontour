"""create user_strava_auth table

Revision ID: 0057
Revises: 0056
Create Date: 2026-05-02 18:52:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create user_strava_auth table for Strava OAuth token storage."""
    op.create_table(
        "user_strava_auth",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column(
            "user_id",
            sa.String(length=50),
            nullable=False,
            comment="Site user identifier",
        ),
        sa.Column(
            "athlete_id",
            sa.BigInteger(),
            nullable=False,
            comment="Strava athlete numeric ID",
        ),
        sa.Column(
            "encrypted_access_token",
            sa.LargeBinary(),
            nullable=False,
            comment="Fernet-encrypted Strava OAuth access token",
        ),
        sa.Column(
            "encrypted_refresh_token",
            sa.LargeBinary(),
            nullable=False,
            comment="Fernet-encrypted Strava OAuth refresh token",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Access token expiration timestamp",
        ),
        sa.Column(
            "strava_webhook_subscription_id",
            sa.Integer(),
            nullable=True,
            comment="Strava push subscription ID (set after webhook registration)",
        ),
        sa.Column(
            "needs_reauth",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Set when refresh token is revoked; cleared on re-auth",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_strava_auth_user_id"),
    )
    op.create_index(
        "ix_user_strava_auth_athlete_id",
        "user_strava_auth",
        ["athlete_id"],
    )


def downgrade() -> None:
    """Drop user_strava_auth table."""
    op.drop_index("ix_user_strava_auth_athlete_id", table_name="user_strava_auth")
    op.drop_table("user_strava_auth")
