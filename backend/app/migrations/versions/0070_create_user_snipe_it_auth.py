"""create user_snipe_it_auth table

Revision ID: 0070
Revises: 0069
Create Date: 2026-05-15 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create user_snipe_it_auth table for Snipe-IT OAuth token storage."""
    op.create_table(
        "user_snipe_it_auth",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column(
            "user_id",
            sa.String(length=50),
            nullable=False,
            comment="Site user identifier",
        ),
        sa.Column(
            "encrypted_access_token",
            sa.LargeBinary(),
            nullable=False,
            comment="Fernet-encrypted Snipe-IT OAuth access token",
        ),
        sa.Column(
            "encrypted_refresh_token",
            sa.LargeBinary(),
            nullable=False,
            comment="Fernet-encrypted Snipe-IT OAuth refresh token",
        ),
        sa.Column(
            "token_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Access token expiration timestamp",
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
        sa.UniqueConstraint("user_id", name="uq_user_snipe_it_auth_user_id"),
    )


def downgrade() -> None:
    """Drop user_snipe_it_auth table."""
    op.drop_table("user_snipe_it_auth")
