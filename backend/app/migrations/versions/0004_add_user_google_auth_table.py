"""Add user_google_auth table for Google OAuth credentials

Revision ID: 0004
Revises: 0003
Create Date: 2025-01-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create user_google_auth table for storing encrypted Google OAuth credentials."""

    # Create user_google_auth table
    op.create_table(
        "user_google_auth",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.VARCHAR(length=255),
            nullable=False,
            comment="User ID from the main application's authentication system",
        ),
        sa.Column(
            "access_token_encrypted",
            sa.LargeBinary(),
            nullable=False,
            comment="Fernet-encrypted Google OAuth access token",
        ),
        sa.Column(
            "refresh_token_encrypted",
            sa.LargeBinary(),
            nullable=False,
            comment="Fernet-encrypted Google OAuth refresh token",
        ),
        sa.Column(
            "expires_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            comment="When the access token expires (UTC)",
        ),
        sa.Column(
            "scope",
            sa.VARCHAR(length=500),
            nullable=False,
            comment="OAuth scopes granted for this token",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="When this auth record was created",
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="When this auth record was last updated",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_google_auth_user_id"),
    )

    # Create indexes for performance
    op.create_index("idx_user_google_auth_user_id", "user_google_auth", ["user_id"])
    op.create_index(
        "idx_user_google_auth_expires_at", "user_google_auth", ["expires_at"]
    )


def downgrade() -> None:
    """Drop user_google_auth table."""
    # Drop indexes first
    op.drop_index("idx_user_google_auth_expires_at", table_name="user_google_auth")
    op.drop_index("idx_user_google_auth_user_id", table_name="user_google_auth")

    # Drop table
    op.drop_table("user_google_auth")
