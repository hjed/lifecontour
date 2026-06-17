"""Extend sync_metadata into the canonical integration-link store

Revision ID: 0089
Revises: 0088
Create Date: 2026-06-17 00:00:00.000000

First step of consolidating integration entity links onto ``sync_metadata`` so
the overlapping ``external_references`` table can later be retired. Additive only
— no data is moved from ``external_references`` and no read/write path changes.

Adds three nullable columns:
- ``reference_data`` (Text/JSON) — link metadata previously held only by
  ``external_references`` (e.g. album display fields). Left NULL here.
- ``internal_entity_type`` / ``external_entity_type`` — explicit entity typing,
  backfilled for existing rows from ``integration_source`` so generic link
  queries no longer have to infer the entity kind from the source name.

Sources with no entity-type mapping (e.g. ``firefly_iii``) are left NULL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0089"
down_revision: str | None = "0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# integration_source -> (internal_entity_type, external_entity_type).
_ENTITY_TYPES_BY_SOURCE: dict[str, tuple[str, str]] = {
    "google": ("contact", "person"),
    "immich": ("contact", "person"),
    "immich_album": ("journal", "album"),
    "strava": ("journal", "activity"),
    "snipeit": ("gear_item", "hardware"),
    "snipeit_maintenance": ("journal", "maintenance"),
    "snipeit_checkout": ("journal", "checkout"),
}

_NEW_COLUMNS = ("reference_data", "internal_entity_type", "external_entity_type")


def upgrade() -> None:
    """Add the link-consolidation columns and backfill entity types."""
    op.add_column(
        "sync_metadata",
        sa.Column(
            "reference_data",
            sa.Text(),
            nullable=True,
            comment="Additional link metadata as JSON (e.g. album display fields)",
        ),
    )
    op.add_column(
        "sync_metadata",
        sa.Column(
            "internal_entity_type",
            sa.String(length=50),
            nullable=True,
            comment="Internal entity type (e.g. 'contact', 'journal', 'gear_item')",
        ),
    )
    op.add_column(
        "sync_metadata",
        sa.Column(
            "external_entity_type",
            sa.String(length=50),
            nullable=True,
            comment="External entity type (e.g. 'person', 'album', 'activity')",
        ),
    )

    for source, (internal_type, external_type) in _ENTITY_TYPES_BY_SOURCE.items():
        op.execute(
            sa.text(
                "UPDATE sync_metadata SET internal_entity_type = :internal_type, "
                "external_entity_type = :external_type "
                "WHERE integration_source = :source"
            ).bindparams(
                internal_type=internal_type,
                external_type=external_type,
                source=source,
            )
        )


def downgrade() -> None:
    """Drop the link-consolidation columns."""
    for column in _NEW_COLUMNS:
        op.drop_column("sync_metadata", column)
