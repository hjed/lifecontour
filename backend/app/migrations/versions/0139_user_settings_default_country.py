"""add user_settings.default_country; make timezone nullable

Revision ID: 0139
Revises: 0138
Create Date: 2026-10-20 00:00:00.000000

``default_country`` (ISO 3166-1 alpha-2) fills in addresses imported without a
country (#1820). A user can set it without ever choosing a timezone, so the
row it creates must not claim they chose UTC: ``timezone`` becomes nullable,
NULL meaning "not chosen" exactly as a missing row already does (#1401), and
loses its ``'UTC'`` server default. Existing rows keep their timezone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0139"
down_revision: str | None = "0138"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("default_country", sa.String(length=2), nullable=True),
    )
    op.alter_column(
        "user_settings",
        "timezone",
        existing_type=sa.String(length=64),
        nullable=True,
        server_default=None,
    )


def downgrade() -> None:
    op.execute("UPDATE user_settings SET timezone = 'UTC' WHERE timezone IS NULL")
    op.alter_column(
        "user_settings",
        "timezone",
        existing_type=sa.String(length=64),
        nullable=False,
        server_default="UTC",
    )
    op.drop_column("user_settings", "default_country")
