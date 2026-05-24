"""Replace Snipe-IT OAuth token columns with encrypted API key.

Snipe-IT's OAuth mode does not function correctly. This migration
switches to API-key authentication by replacing the per-user
``encrypted_access_token`` / ``encrypted_refresh_token`` / ``token_expires_at``
columns with a single ``encrypted_api_key`` column.

Revision ID: 0078
Revises: 0077
Create Date: 2026-05-24 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0078"
down_revision: str | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace OAuth token columns with encrypted_api_key."""
    # Drop old OAuth columns
    op.drop_column("user_snipe_it_auth", "encrypted_access_token")
    op.drop_column("user_snipe_it_auth", "encrypted_refresh_token")
    op.drop_column("user_snipe_it_auth", "token_expires_at")

    # Add new API key column
    op.add_column(
        "user_snipe_it_auth",
        sa.Column(
            "encrypted_api_key",
            sa.LargeBinary(),
            nullable=False,
            server_default=sa.text("''::bytea"),
            comment="Fernet-encrypted Snipe-IT personal access token (API key)",
        ),
    )

    # Remove the server default after migration (existing rows get empty bytes)
    op.alter_column(
        "user_snipe_it_auth",
        "encrypted_api_key",
        server_default=None,
    )


def downgrade() -> None:
    """Restore OAuth token columns and drop encrypted_api_key."""
    op.drop_column("user_snipe_it_auth", "encrypted_api_key")

    op.add_column(
        "user_snipe_it_auth",
        sa.Column(
            "encrypted_access_token",
            sa.LargeBinary(),
            nullable=False,
            server_default=sa.text("''::bytea"),
            comment="Fernet-encrypted Snipe-IT OAuth access token",
        ),
    )
    op.add_column(
        "user_snipe_it_auth",
        sa.Column(
            "encrypted_refresh_token",
            sa.LargeBinary(),
            nullable=False,
            server_default=sa.text("''::bytea"),
            comment="Fernet-encrypted Snipe-IT OAuth refresh token",
        ),
    )
    op.add_column(
        "user_snipe_it_auth",
        sa.Column(
            "token_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Access token expiration timestamp",
        ),
    )
