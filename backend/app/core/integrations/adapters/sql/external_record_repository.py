"""The inbound records a journal holds, read across every registered link store.

A merge compares what the source journal held before it started with what the
target holds once it is done; whatever is missing was lost on the way and is
kept as a merged alias. Reading both sides from ``JOURNAL_LINK_SOURCES`` is
what makes that generic: the merge never has to know which store an
integration links through, or why a particular link could not move.
"""

from __future__ import annotations

from core_shared.merged_alias_keys import merged_alias_key
from core_shared.repositories.merged_alias_repository import ExternalRecord
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.link_sources import (
    JOURNAL_LINK_SOURCES,
    AliasPolicy,
)


def external_records_sql() -> str:
    """One ``UNION ALL`` branch per ``INBOUND`` store, for ``:journal_id``."""
    branches = []
    for source_name, source in JOURNAL_LINK_SOURCES.items():
        for store in source.stores:
            if store.alias_policy is not AliasPolicy.INBOUND:
                continue
            conditions = [f"{store.journal_id_sql} = :journal_id"]
            if store.where_sql:
                conditions.append(store.where_sql)
            branches.append(
                f"SELECT '{source_name}' AS integration_source, "
                f"CAST({store.external_id_sql} AS VARCHAR) AS external_id, "
                f"CAST({store.calendar_id_sql or 'NULL'} AS UUID) AS calendar_id, "
                f"CAST({store.external_identity_sql or 'NULL'} AS VARCHAR) "
                "AS external_identity, "
                f"CAST({store.recurring_event_id_sql or 'NULL'} AS VARCHAR) "
                "AS recurring_event_id "
                f"FROM {store.from_sql} WHERE {' AND '.join(conditions)}"
            )
    return " UNION ALL ".join(branches)


class SqlExternalRecordRepository:
    """Reads a journal's inbound records from every registered store."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.conn = connection

    async def external_records_for_journal(
        self, journal_id: int
    ) -> list[ExternalRecord]:
        """Each inbound record once, however many stores name it.

        A Strava activity sits in ``sync_metadata`` and the fitness row; it is
        one record. Where stores disagree on the extras, the first one that
        has them wins.
        """
        result = await self.conn.execute(
            text(external_records_sql()), {"journal_id": journal_id}
        )
        records: dict[tuple[str, str], ExternalRecord] = {}
        for row in result.fetchall():
            key = merged_alias_key(row.integration_source, row.external_id or "")
            if key is None:
                continue
            identity = (key.integration_source, key.external_id)
            known = records.get(identity)
            records[identity] = ExternalRecord(
                integration_source=key.integration_source,
                external_id=key.external_id,
                calendar_id=(known and known.calendar_id) or row.calendar_id,
                external_identity=(known and known.external_identity)
                or row.external_identity,
                recurring_event_id=(known and known.recurring_event_id)
                or row.recurring_event_id,
            )
        return list(records.values())
