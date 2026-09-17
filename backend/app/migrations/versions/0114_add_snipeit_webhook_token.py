"""add webhook_token to snipeit_settings

Revision ID: 0114
Revises: 0113
Create Date: 2026-09-16 12:00:00.000000

Snipe-IT webhooks have no signing secret, so the inbound webhook is
authenticated by a per-user secret in its URL. Each existing settings row is
backfilled with its own random token, which also changes that user's webhook
URL: the tokenless URL configured in Snipe-IT stops working and must be copied
again from the integration's Webhook URL dialog.
"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0114"
down_revision: str | None = "0113"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the token, give every existing row its own, then require it."""
    op.add_column(
        "snipeit_settings",
        sa.Column(
            "webhook_token",
            sa.String(length=64),
            nullable=True,
            comment="Secret in the Snipe-IT webhook URL identifying this user",
        ),
    )

    connection = op.get_bind()
    user_ids = connection.execute(
        sa.text("SELECT user_id FROM snipeit_settings")
    ).scalars()
    for user_id in user_ids.all():
        connection.execute(
            sa.text(
                "UPDATE snipeit_settings SET webhook_token = :token "
                "WHERE user_id = :user_id"
            ),
            {"token": secrets.token_urlsafe(32), "user_id": user_id},
        )

    op.alter_column("snipeit_settings", "webhook_token", nullable=False)
    op.create_unique_constraint(
        "uq_snipeit_settings_webhook_token", "snipeit_settings", ["webhook_token"]
    )


def downgrade() -> None:
    """Drop the token; the webhook then has no per-user secret to check."""
    op.drop_constraint(
        "uq_snipeit_settings_webhook_token", "snipeit_settings", type_="unique"
    )
    op.drop_column("snipeit_settings", "webhook_token")
