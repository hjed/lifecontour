"""Drop journal_photo_album_data table and allow immich_album sync source

Revision ID: 0086
Revises: 0085
Create Date: 2026-06-07 00:00:00.000000

ITER11-004 Phase 1: The ``journal_photo_album_data`` table and ``PhotoAlbumData``
entity were Iteration 4 scaffolding that duplicated integration state already
handled by ``sync_metadata`` and ``external_references``. PHOTO_ALBUM type
detection now derives from a ``sync_metadata`` row with
``integration_source='immich_album'`` instead of a row in this table.

This migration:
- Drops the ``journal_photo_album_data`` table (not used in production).
- Adds ``immich_album`` to the ``sync_metadata.integration_source`` check
  constraint so album sync metadata can be persisted.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0086"
down_revision: str | None = "0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Allowed integration sources after this migration (adds 'immich_album').
_SOURCES_WITH_ALBUM = (
    "integration_source IN ('google', 'immich', 'immich_album', 'strava', "
    "'firefly_iii', 'snipeit', 'snipeit_maintenance', 'snipeit_checkout')"
)
_SOURCES_WITHOUT_ALBUM = (
    "integration_source IN ('google', 'immich', 'strava', "
    "'firefly_iii', 'snipeit', 'snipeit_maintenance', 'snipeit_checkout')"
)

_MAX_IMMICH_ALBUM_ID_LENGTH = 255


def upgrade() -> None:
    """Drop the photo album data table and allow the immich_album source."""
    op.drop_table("journal_photo_album_data")

    op.drop_constraint(
        "ck_sync_metadata_integration_source", "sync_metadata", type_="check"
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        _SOURCES_WITH_ALBUM,
    )


def downgrade() -> None:
    """Recreate the photo album data table and revert the source constraint."""
    # Remove any album sync metadata before reverting the constraint.
    op.execute("DELETE FROM sync_metadata WHERE integration_source = 'immich_album'")

    op.drop_constraint(
        "ck_sync_metadata_integration_source", "sync_metadata", type_="check"
    )
    op.create_check_constraint(
        "ck_sync_metadata_integration_source",
        "sync_metadata",
        _SOURCES_WITHOUT_ALBUM,
    )

    op.create_table(
        "journal_photo_album_data",
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey("journals.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
            comment="Reference to the parent journal entry",
        ),
        sa.Column(
            "immich_album_id",
            sa.VARCHAR(length=_MAX_IMMICH_ALBUM_ID_LENGTH),
            nullable=False,
            comment="Immich album identifier for photo integration",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
