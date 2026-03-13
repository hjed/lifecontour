"""update integration check constraints

Revision ID: b62a2993cd42
Revises: 285cd30b6c39
Create Date: 2026-03-13 19:07:08.032674

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.drop_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        type_="check",
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        "integration_source IN ('google', 'immich', 'strava', 'firefly_iii')",
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        type_="check",
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        "integration_source IN ('google_contacts', 'immich', 'strava', 'firefly_iii')",
    )
