"""Backfill sync_metadata from external_references

Revision ID: 0091
Revises: 0090
Create Date: 2026-06-18 00:00:00.000000

Second step of consolidating integration entity links onto ``sync_metadata``.
After the dual-write change ships, this idempotent data migration backfills the
rows that predate dual-write so the canonical store is complete: for every
``external_references`` row it upserts the matching ``sync_metadata`` link,
copying ``reference_data`` and entity types.

``external_references`` allows duplicate ``(external_system, external_entity_id)``
rows but ``sync_metadata`` is ``UNIQUE(integration_source, external_id)``. When a
group has more than one candidate, a deterministic winner is chosen (prefer the
row whose internal id still exists, tie-break by lowest external_references id)
and the losers are logged to the temporary ``link_backfill_quarantine`` audit
table for Phase 5 reconciliation — no row is silently dropped.

Backfilled-only rows get ``version_hash = ''`` and ``last_synced_at`` at the epoch
so the next sync re-validates content and a contact with pending local edits
(``contacts.updated_at > sync_metadata.last_synced_at`` gates the outbound push)
is not mistakenly treated as already synced. Existing ``sync_metadata`` rows keep
their ``internal_id`` / ``version_hash`` / ``last_synced_at`` and only have NULL
``reference_data`` / entity types filled in.

The work is expressed as set-based SQL (a ranking CTE materialised into a temp
table, then two INSERTs) so it neither loads ``external_references`` into Python
nor issues a per-row existence query — it scales to large tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0091"
down_revision: str | None = "0090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CREATE_QUARANTINE = sa.text("""
    CREATE TABLE IF NOT EXISTS link_backfill_quarantine (
        id SERIAL PRIMARY KEY,
        integration_source VARCHAR(50) NOT NULL,
        external_id VARCHAR(255) NOT NULL,
        internal_id INTEGER,
        external_reference_id INTEGER NOT NULL UNIQUE,
        reason VARCHAR(255) NOT NULL,
        quarantined_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
""")

# Map each (external_system, external_entity_type) to its canonical
# integration_source + entity types + internal table, then rank candidates per
# (integration_source, external_id): a row whose internal id still exists wins
# over an orphan, tie-broken by the lowest external_references id. ``internal_exists``
# is resolved with LEFT JOINs (set-based) instead of a query per row.
_BUILD_RANKED = sa.text("""
    CREATE TEMP TABLE _link_backfill_ranked ON COMMIT DROP AS
    WITH mapped AS (
        SELECT
            er.id AS ext_ref_id,
            er.internal_entity_id,
            er.reference_data,
            er.external_entity_id AS external_id,
            m.integration_source,
            m.internal_entity_type,
            m.external_entity_type,
            m.internal_table
        FROM external_references er
        JOIN (VALUES
            ('immich', 'person', 'immich', 'contact', 'person', 'contacts'),
            ('immich', 'album', 'immich_album', 'journal', 'album', 'journals'),
            ('google', 'person', 'google', 'contact', 'person', 'contacts')
        ) AS m(ext_system, ext_type, integration_source,
               internal_entity_type, external_entity_type, internal_table)
          ON er.external_system = m.ext_system
         AND er.external_entity_type = m.ext_type
    ),
    resolved AS (
        SELECT
            mapped.*,
            CASE
                WHEN c.id IS NOT NULL OR j.id IS NOT NULL THEN 1 ELSE 0
            END AS internal_exists
        FROM mapped
        LEFT JOIN contacts c
            ON mapped.internal_table = 'contacts'
           AND c.id = mapped.internal_entity_id
        LEFT JOIN journals j
            ON mapped.internal_table = 'journals'
           AND j.id = mapped.internal_entity_id
    )
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY integration_source, external_id
            ORDER BY internal_exists DESC, ext_ref_id ASC
        ) AS rn
    FROM resolved
""")

# Winners: upsert the canonical link. New rows get version_hash='' and
# last_synced_at at the epoch so the next sync re-validates and a pending push is
# not suppressed; existing rows keep internal_id/version_hash/last_synced_at and
# only gain NULL reference_data / entity types via COALESCE.
_INSERT_WINNERS = sa.text("""
    INSERT INTO sync_metadata
        (internal_id, integration_source, external_id, last_synced_at,
         version_hash, sync_status, internal_entity_type, external_entity_type,
         reference_data, retry_count, created_at, updated_at)
    SELECT
        internal_entity_id, integration_source, external_id, TIMESTAMPTZ 'epoch',
        '', 'success', internal_entity_type, external_entity_type,
        reference_data, 0, now(), now()
    FROM _link_backfill_ranked
    WHERE rn = 1
    ON CONFLICT (integration_source, external_id) DO UPDATE SET
        internal_entity_type = COALESCE(
            sync_metadata.internal_entity_type, EXCLUDED.internal_entity_type),
        external_entity_type = COALESCE(
            sync_metadata.external_entity_type, EXCLUDED.external_entity_type),
        reference_data = COALESCE(
            sync_metadata.reference_data, EXCLUDED.reference_data),
        updated_at = now()
""")

_INSERT_LOSERS = sa.text("""
    INSERT INTO link_backfill_quarantine
        (integration_source, external_id, internal_id, external_reference_id, reason)
    SELECT
        integration_source, external_id, internal_entity_id, ext_ref_id,
        'duplicate_external_reference'
    FROM _link_backfill_ranked
    WHERE rn > 1
    ON CONFLICT (external_reference_id) DO NOTHING
""")


def upgrade() -> None:
    """Backfill sync_metadata links from external_references, idempotently."""
    op.execute(_CREATE_QUARANTINE)
    op.execute(_BUILD_RANKED)
    op.execute(_INSERT_WINNERS)
    op.execute(_INSERT_LOSERS)


def downgrade() -> None:
    """Drop the quarantine audit table.

    Backfilled ``sync_metadata`` rows are intentionally left in place — they are
    the canonical link records and removing them would re-open the gap.
    """
    op.execute(sa.text("DROP TABLE IF EXISTS link_backfill_quarantine"))
