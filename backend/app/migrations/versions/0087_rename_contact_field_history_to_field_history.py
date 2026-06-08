"""rename contact_field_history to field_history and add projection idempotency

Generalises the contact-specific history table into the entity-agnostic
``field_history`` table shared by contacts and journals. Adds a nullable
``event_id`` column plus a unique index on
``(event_id, entity_type, entity_id, field_name)`` so the event-driven history
projection can write idempotently (re-delivered events never duplicate rows).
``rename_table`` is a metadata-only operation, so all existing rows are preserved
and keep ``event_id = NULL``.

Revision ID: 0087
Revises: 0086
Create Date: 2026-06-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0087"
down_revision: str | None = "0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNIQUE_INDEX = "ux_field_history_event_dedup"


def upgrade() -> None:
    """Upgrade database schema."""
    # 1. Rename the table (preserves all existing rows).
    op.rename_table("contact_field_history", "field_history")

    # 2. Add the nullable event_id used by the history projection.
    op.add_column(
        "field_history",
        sa.Column("event_id", sa.String(), nullable=True),
    )

    # 3. Idempotency guard for the projection. NULL event_ids (e.g. the synchronous
    #    contact dual-write) are treated as distinct by PostgreSQL, so they are never
    #    deduplicated; only projected rows carrying an event_id are deduped.
    op.create_index(
        _UNIQUE_INDEX,
        "field_history",
        ["event_id", "entity_type", "entity_id", "field_name"],
        unique=True,
    )

    # 4. Keep remaining index names consistent with the new table name.
    op.execute(
        "ALTER INDEX idx_contact_field_history_field_name "
        "RENAME TO idx_field_history_field_name"
    )
    op.execute(
        "ALTER INDEX idx_contact_field_history_created_at "
        "RENAME TO idx_field_history_created_at"
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.execute(
        "ALTER INDEX idx_field_history_created_at "
        "RENAME TO idx_contact_field_history_created_at"
    )
    op.execute(
        "ALTER INDEX idx_field_history_field_name "
        "RENAME TO idx_contact_field_history_field_name"
    )
    op.drop_index(_UNIQUE_INDEX, table_name="field_history")
    op.drop_column("field_history", "event_id")
    op.rename_table("field_history", "contact_field_history")
