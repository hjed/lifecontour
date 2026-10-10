"""Give every unowned ``sync_metadata`` link an owner, for a migration.

A link's owner is the owner of the entity it points at, found by its type.
Rows written before ``internal_entity_type`` existed, and every row the Snipe-IT
worker writes, carry no type, so it is derived from ``integration_source``
(``0089``'s mapping plus the Snipe-IT sources added since). Snipe-IT stores a
journal id as text in ``internal_uuid``.

A link still unowned after that — it names no entity, or one since deleted
(``sync_metadata`` has no foreign key) — is logged and given the site's one
user, derived by :mod:`app.migrations.owner_derivation`. That refuses when the
data cannot choose, unless the operator names the owner:
``alembic -x sync_metadata_owner=<user_id> upgrade head``.

Shared by ``0126`` (which added the column) and ``0128`` (which assigns what a
not-yet-deployed writer left unowned, then requires the owner). Treat its
behaviour as frozen once a revision depends on it: change it only by adding,
never by redefining.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from app.migrations.owner_derivation import assign_unowned, derive_owner, log

OVERRIDE_NAME = "sync_metadata_owner"

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


def _backfill_from_entities(connection: sa.Connection, label: str) -> None:
    """Give each unowned link the owner of the entity it points at."""
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
            label,
            entity_type,
            result.rowcount,
            entity_type,
        )


def _assign_orphans(
    connection: sa.Connection, label: str, evidence_tables: Sequence[str]
) -> None:
    """Log every link no entity owns, then give them the site's one owner."""
    orphans = connection.execute(
        sa.text(
            "SELECT id, integration_source, external_id, internal_entity_type, "
            "internal_id, internal_uuid FROM sync_metadata "
            "WHERE user_id IS NULL ORDER BY id"
        )
    ).fetchall()
    if not orphans:
        log.info("%s: every link resolved to its entity's owner.", label)
        return

    for row in orphans:
        log.info(
            "%s: unresolved link id=%s source=%s external_id=%s "
            "entity_type=%s internal_id=%s internal_uuid=%s",
            label,
            row.id,
            row.integration_source,
            row.external_id,
            row.internal_entity_type,
            row.internal_id,
            row.internal_uuid,
        )
    owner = derive_owner(
        connection,
        evidence_tables=evidence_tables,
        label=label,
        override_name=OVERRIDE_NAME,
    )
    assign_unowned(connection, "sync_metadata", owner, label)


def assign_link_owners(
    connection: sa.Connection, *, label: str, evidence_tables: Sequence[str]
) -> None:
    """Give every link whose ``user_id`` is NULL its entity's owner, or the
    site's one owner when no entity owns it.

    ``label`` prefixes every log line (the revision number); ``evidence_tables``
    is the calling revision's literal tuple of tables recording a user.
    """
    _backfill_from_entities(connection, label)
    _assign_orphans(connection, label, evidence_tables)
