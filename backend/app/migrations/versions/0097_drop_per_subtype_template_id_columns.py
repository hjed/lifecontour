"""drop per-subtype template_id columns

Revision ID: 0097
Revises: 0096
Create Date: 2026-07-06

ITER16-001 Phase 5 — retire the per-subtype ``template_id`` columns.

Cleanup data-layer change. Migration 0094 consolidated the template reference
onto ``journal_abseiling_data.template_id`` and backfilled it from the per-subtype
columns; Phases 2–4 moved all reads/writes to the consolidated column. This drops
the now-unused ``template_id`` columns (and their FKs) from:

  - ``journal_canyoning_data``
  - ``journal_climbing_data``
  - ``journal_caving_data``

``op.drop_column`` cascades the dependent FK constraint in PostgreSQL, so the
columns and their foreign keys are removed together.

Downgrade re-adds each column as a nullable UUID FK to ``activity_templates``
(``ON DELETE SET NULL``) and re-backfills it from the consolidated
``journal_abseiling_data.template_id`` for journals carrying that subtype, so the
round-trip is reversible and non-destructive.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0097"
down_revision: str | None = "0096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUBTYPE_TABLES = (
    "journal_canyoning_data",
    "journal_climbing_data",
    "journal_caving_data",
)


def upgrade() -> None:
    """Upgrade database schema — drop the per-subtype template_id columns."""
    for table in _SUBTYPE_TABLES:
        # Dropping the column cascades its FK constraint in PostgreSQL.
        op.drop_column(table, "template_id")


def downgrade() -> None:
    """Downgrade database schema — restore the columns and re-backfill.

    Re-adds each per-subtype ``template_id`` FK and repopulates it from the
    consolidated ``journal_abseiling_data.template_id`` (the source of truth),
    so no data is lost across an upgrade/downgrade round-trip.
    """
    for table in _SUBTYPE_TABLES:
        op.add_column(
            table,
            sa.Column(
                "template_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("activity_templates.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.execute(
            f"""
            UPDATE {table} AS sub
            SET template_id = a.template_id
            FROM journal_abseiling_data AS a
            WHERE a.journal_id = sub.journal_id
              AND a.template_id IS NOT NULL
            """  # noqa: S608 — table name is from a fixed internal allowlist
        )
