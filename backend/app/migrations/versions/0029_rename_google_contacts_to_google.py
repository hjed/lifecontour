"""Rename google_contacts to google in sync metadata

Revision ID: 285cd30b6c39
Revises: 0028
Create Date: 2026-03-13 07:40:20.805231

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.drop_constraint(
        "ck_sync_metadata_integration_source", "sync_metadata", type_="check"
    )
    op.execute(
        "UPDATE sync_metadata SET integration_source = 'google' WHERE integration_source = 'google_contacts'"
    )
    op.execute(
        "UPDATE external_references SET external_system = 'google' WHERE external_system = 'google_contacts'"
    )
    op.execute(
        "UPDATE sync_jobs SET integration_source = 'google' WHERE integration_source = 'google_contacts'"
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        "integration_source IN ('google', 'immich', 'strava', 'firefly_iii')",
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_constraint(
        "ck_sync_metadata_integration_source", "sync_metadata", type_="check"
    )
    op.execute(
        "UPDATE sync_metadata SET integration_source = 'google_contacts' WHERE integration_source = 'google'"
    )
    op.execute(
        "UPDATE external_references SET external_system = 'google_contacts' WHERE external_system = 'google'"
    )
    op.execute(
        "UPDATE sync_jobs SET integration_source = 'google_contacts' WHERE integration_source = 'google'"
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        "integration_source IN ('google_contacts', 'immich', 'strava', 'firefly_iii')",
    )
