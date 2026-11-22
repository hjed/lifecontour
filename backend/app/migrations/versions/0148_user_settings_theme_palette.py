"""add user_settings.theme_palette

Revision ID: 0148
Revises: 0147
Create Date: 2026-11-22 00:00:00.000000

``theme_palette`` is the colour palette the user picked for the app (e.g.
``emerald``). NULL means "not chosen", which renders the default palette, so
existing rows need no backfill. Stored as a plain string rather than a Postgres
enum so a new palette needs no migration; the API validates the value.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0148"
down_revision: str | None = "0147"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("theme_palette", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "theme_palette")
