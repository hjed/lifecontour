"""Fix user_google_auth table constraints for multiple accounts

Revision ID: 0005
Revises: 0004
Create Date: 2025-01-22 14:00:00.000000

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
    """Fix user_google_auth table to support multiple Google accounts per user."""

    # Drop the unique constraint on user_id to allow multiple Google accounts per user
    op.drop_constraint(
        "uq_user_google_auth_user_id", "user_google_auth", type_="unique"
    )

    # Add google_account_email field to distinguish between different Google accounts
    op.add_column(
        "user_google_auth",
        sa.Column(
            "google_account_email",
            sa.VARCHAR(length=255),
            nullable=True,  # Temporarily nullable for existing records
            comment="Email address of the Google account for identification",
        ),
    )

    # Add google_account_name field for better user experience
    op.add_column(
        "user_google_auth",
        sa.Column(
            "google_account_name",
            sa.VARCHAR(length=255),
            nullable=True,
            comment="Display name of the Google account",
        ),
    )

    # Update existing records to have a placeholder email (if any exist)
    # This is safe since we just created the table in the previous migration
    op.execute(
        "UPDATE user_google_auth SET google_account_email = 'unknown@example.com' WHERE google_account_email IS NULL"
    )

    # Now make google_account_email non-nullable
    op.alter_column(
        "user_google_auth",
        "google_account_email",
        nullable=False,
    )

    # Create a new unique constraint on (user_id, google_account_email)
    # This allows multiple Google accounts per user but prevents duplicate accounts
    op.create_unique_constraint(
        "uq_user_google_auth_user_account",
        "user_google_auth",
        ["user_id", "google_account_email"],
    )

    # Create index for efficient lookups by Google account email
    op.create_index(
        "idx_user_google_auth_google_email",
        "user_google_auth",
        ["google_account_email"],
    )

    # Create index for efficient lookups by user_id and email combination
    op.create_index(
        "idx_user_google_auth_user_email",
        "user_google_auth",
        ["user_id", "google_account_email"],
    )


def downgrade() -> None:
    """Revert user_google_auth table changes."""
    # Drop new indexes
    op.drop_index("idx_user_google_auth_user_email", table_name="user_google_auth")
    op.drop_index("idx_user_google_auth_google_email", table_name="user_google_auth")

    # Drop new unique constraint
    op.drop_constraint(
        "uq_user_google_auth_user_account", "user_google_auth", type_="unique"
    )

    # Drop new columns
    op.drop_column("user_google_auth", "google_account_name")
    op.drop_column("user_google_auth", "google_account_email")

    # Restore original unique constraint on user_id
    op.create_unique_constraint(
        "uq_user_google_auth_user_id",
        "user_google_auth",
        ["user_id"],
    )
