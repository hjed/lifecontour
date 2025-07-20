"""Add user_google_auth table for Google OAuth tokens

Revision ID: 0005
Revises: 0004
Create Date: 2024-12-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create user_google_auth table for storing encrypted Google OAuth tokens."""

    # Create user_google_auth table
    op.create_table(
        "user_google_auth",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.VARCHAR(length=50),
            nullable=False,
            comment="Site user identifier",
        ),
        sa.Column(
            "google_account_email",
            sa.VARCHAR(length=255),
            nullable=False,
            comment="Google account email address",
        ),
        sa.Column(
            "encrypted_access_token",
            sa.LargeBinary(),
            nullable=False,
            comment="Encrypted Google access token",
        ),
        sa.Column(
            "encrypted_refresh_token",
            sa.LargeBinary(),
            nullable=True,
            comment="Encrypted Google refresh token",
        ),
        sa.Column(
            "expires_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            comment="Access token expiration timestamp",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Record creation timestamp",
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Record last update timestamp",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "google_account_email", name="uq_user_google_account"
        ),
    )

    # Create indexes for performance
    op.create_index("idx_user_google_auth_user_id", "user_google_auth", ["user_id"])
    op.create_index(
        "idx_user_google_auth_email", "user_google_auth", ["google_account_email"]
    )


def downgrade() -> None:
    """Drop user_google_auth table."""

    # Drop indexes
    op.drop_index("idx_user_google_auth_email", table_name="user_google_auth")
    op.drop_index("idx_user_google_auth_user_id", table_name="user_google_auth")

    # Drop table
    op.drop_table("user_google_auth")
