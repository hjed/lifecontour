"""give every integration link an owner: add sync_metadata.user_id

Revision ID: 0126
Revises: 0125
Create Date: 2026-10-08 00:00:00.000000

``sync_metadata`` is unique on ``(integration_source, external_id)`` across all
users, so one user's link can block, or be re-pointed by, another's. This
revision is the expand half of moving that key to the owner: it adds a nullable
``sync_metadata.user_id``, gives every existing link the owner of the entity it
points at, and creates the per-user unique index that every writer conflicts on
from this release. The global index stays until ``0127``; while both exist, a
write for an external id another owner already holds is refused by it.

The owner comes from the linked entity, by its type. Rows written before
``internal_entity_type`` existed, and every row the Snipe-IT worker writes,
carry no type, so it is derived from ``integration_source`` (``0089``'s mapping
plus the Snipe-IT sources added since). Snipe-IT stores a journal id as text in
``internal_uuid``.

A link still unowned after that — it names no entity, or one since deleted
(``sync_metadata`` has no foreign key) — is logged and given the site's one
user, derived by ``app.migrations.owner_derivation``. That refuses when the data
cannot choose, unless the operator names the owner:
``alembic -x sync_metadata_owner=<user_id> upgrade head``.

The column stays nullable here: ``0127`` assigns anything a not-yet-deployed
writer inserted without an owner, then requires it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migrations.owner_derivation import assign_unowned, derive_owner, log

# revision identifiers, used by Alembic.
revision: str = "0126"
down_revision: str | None = "0125"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LABEL = "0126"
_PER_USER_INDEX = "uq_sync_metadata_user_source_external"

# Every table that records a user at 0125 — a test pins this to the schema.
EVIDENCE_TABLES = (
    "contacts",
    "journals",
    "calendars",
    "gear_items",
    "journal_series",
    "activity_templates",
    "tasks",
    "outdoor_activity_dismissals",
    "journal_review_items",
    "strava_athlete_mappings",
    "user_google_auth",
    "user_google_integration",
    "user_immich_auth",
    "user_strava_auth",
    "user_snipe_it_auth",
    "snipeit_settings",
    "user_settings",
    "sync_jobs",
    "calendar_sync_tokens",
    "pending_entity_mappings",
    "contact_suggestion_ignores",
    "journal_daily_summaries",
    "field_history",
    "journal_series_recurrence_aliases",
)

# The linked entity's type when the row does not record one: 0089's mapping by
# source, plus the Snipe-IT sources added after it (whose rows the worker never
# types). ``firefly_iii`` links nothing.
_ENTITY_TYPE_BY_SOURCE = {
    "google": "contact",
    "immich": "contact",
    "immich_album": "journal",
    "strava": "journal",
    "snipeit": "gear_item",
    "snipeit_maintenance": "journal",
    "snipeit_checkout": "journal",
    "snipeit_checkin": "journal",
    "snipeit_maintenance_claim": "journal",
}

_ENTITY_TYPE_SQL = (
    "COALESCE(m.internal_entity_type, CASE m.integration_source {} END)".format(
        " ".join(
            f"WHEN '{source}' THEN '{entity_type}'"
            for source, entity_type in _ENTITY_TYPE_BY_SOURCE.items()
        )
    )
)

# A journal is named by ``internal_id`` or, for Snipe-IT, by its id as text in
# ``internal_uuid``. The CASE keeps the cast away from gear UUIDs and from digit
# strings too long for an integer.
_JOURNAL_ID_SQL = (
    "COALESCE(m.internal_id, CASE WHEN m.internal_uuid ~ '^[0-9]{1,9}$' "
    "THEN CAST(m.internal_uuid AS integer) END)"
)

# entity type -> (owning table, join predicate against sync_metadata ``m``).
_OWNER_JOINS = {
    "contact": ("contacts", "e.id = m.internal_id"),
    "journal": ("journals", f"e.id = {_JOURNAL_ID_SQL}"),
    "gear_item": ("gear_items", "CAST(e.id AS text) = m.internal_uuid"),
}


def _backfill_from_entities(connection: sa.Connection) -> None:
    """Give each link the owner of the entity it points at."""
    for entity_type, (table, predicate) in _OWNER_JOINS.items():
        result = connection.execute(
            sa.text(
                f"UPDATE sync_metadata m SET user_id = e.user_id FROM {table} e "  # noqa: S608 - literals above
                f"WHERE m.user_id IS NULL AND {_ENTITY_TYPE_SQL} = :entity_type "
                f"AND {predicate}"
            ),
            {"entity_type": entity_type},
        )
        log.info(
            "%s: %s links: %d given their %s's owner.",
            _LABEL,
            entity_type,
            result.rowcount,
            entity_type,
        )


def _assign_orphans(connection: sa.Connection) -> None:
    """Log every link no entity owns, then give them the site's one owner."""
    orphans = connection.execute(
        sa.text(
            "SELECT id, integration_source, external_id, internal_entity_type, "
            "internal_id, internal_uuid FROM sync_metadata "
            "WHERE user_id IS NULL ORDER BY id"
        )
    ).fetchall()
    if not orphans:
        log.info("%s: every link resolved to its entity's owner.", _LABEL)
        return

    for row in orphans:
        log.info(
            "%s: unresolved link id=%s source=%s external_id=%s "
            "entity_type=%s internal_id=%s internal_uuid=%s",
            _LABEL,
            row.id,
            row.integration_source,
            row.external_id,
            row.internal_entity_type,
            row.internal_id,
            row.internal_uuid,
        )
    owner = derive_owner(
        connection,
        evidence_tables=EVIDENCE_TABLES,
        label=_LABEL,
        override_name="sync_metadata_owner",
    )
    assign_unowned(connection, "sync_metadata", owner, _LABEL)


def upgrade() -> None:
    """Add the owner column, assign every link, and index the per-user key."""
    op.add_column("sync_metadata", sa.Column("user_id", sa.String(50), nullable=True))

    connection = op.get_bind()
    _backfill_from_entities(connection)
    _assign_orphans(connection)

    op.create_index(
        _PER_USER_INDEX,
        "sync_metadata",
        ["user_id", "integration_source", "external_id"],
        unique=True,
    )


def downgrade() -> None:
    """Drop the per-user index and the owner column."""
    op.drop_index(_PER_USER_INDEX, table_name="sync_metadata")
    op.drop_column("sync_metadata", "user_id")
