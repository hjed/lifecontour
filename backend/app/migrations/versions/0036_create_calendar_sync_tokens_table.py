"""Create calendar_sync_tokens table for per-calendar sync token storage

Revision ID: 0036
Revises: 0035
Create Date: 2026-03-16

Introduces a dedicated table to store Google Calendar sync tokens per-calendar
rather than per-account. Also stores webhook channel metadata for push
notification support.

Migrates existing per-account sync tokens from user_google_integration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create calendar_sync_tokens table and migrate existing tokens."""
    op.create_table(
        "calendar_sync_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.VARCHAR(length=50), nullable=False),
        sa.Column("google_account_email", sa.VARCHAR(length=255), nullable=False),
        sa.Column("google_calendar_id", sa.VARCHAR(length=255), nullable=False),
        sa.Column("sync_token", sa.VARCHAR(length=500), nullable=True),
        sa.Column(
            "last_synced_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        # Webhook channel metadata
        sa.Column(
            "channel_id",
            sa.VARCHAR(length=255),
            nullable=True,
            comment="Google push notification channel UUID",
        ),
        sa.Column(
            "channel_resource_id",
            sa.VARCHAR(length=255),
            nullable=True,
            comment="Resource ID from Google watch response",
        ),
        sa.Column(
            "channel_expiration",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="When the push notification channel expires",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "google_account_email",
            "google_calendar_id",
            name="uq_calendar_sync_tokens_user_account_calendar",
        ),
    )

    # Composite index for webhook channel lookup (queries by both columns)
    op.create_index(
        "ix_calendar_sync_tokens_channel_id",
        "calendar_sync_tokens",
        ["channel_id", "channel_resource_id"],
        unique=False,
    )

    # Index for user + account lookups
    op.create_index(
        "ix_calendar_sync_tokens_user_account",
        "calendar_sync_tokens",
        ["user_id", "google_account_email"],
        unique=False,
    )

    # Migrate existing per-account sync tokens to per-calendar rows.
    # We join user_google_integration (which has the old token) with calendars
    # (created in migration 0010) to create one row per synced calendar.
    # For accounts that have no calendar rows yet, COALESCE falls back to 'primary'.
    op.execute(
        sa.text("""
            INSERT INTO calendar_sync_tokens
                (user_id, google_account_email, google_calendar_id,
                 sync_token, created_at, updated_at)
            SELECT
                ugi.user_id,
                ugi.google_account_email,
                COALESCE(c.google_calendar_id, 'primary'),
                ugi.calendar_events_sync_token,
                NOW(),
                NOW()
            FROM user_google_integration ugi
            LEFT JOIN calendars c
                ON c.user_id = ugi.user_id
                AND c.google_calendar_id IS NOT NULL
                AND c.is_synced_to_google = true
            WHERE ugi.calendar_events_sync_token IS NOT NULL
            ON CONFLICT (user_id, google_account_email, google_calendar_id)
                DO NOTHING
        """)
    )


def downgrade() -> None:
    """Drop calendar_sync_tokens table."""
    op.drop_index(
        "ix_calendar_sync_tokens_user_account",
        table_name="calendar_sync_tokens",
    )
    op.drop_index(
        "ix_calendar_sync_tokens_channel_id",
        table_name="calendar_sync_tokens",
    )
    op.drop_table("calendar_sync_tokens")
