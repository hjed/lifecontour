"""The one way in to ``journal_merged_aliases``: record, move and find aliases.

A merge records each inbound record it absorbed but could not keep as a live
link (see ``JournalMergedAlias``); every inbound path — the integration
workers before emitting a create, the backend sync processors before writing
one — asks :meth:`MergedAliasRepository.find_alias` first, and leaves an
aliased record alone. That is what stops a sync undoing a merge.

Callers may name a record in their payload's terms (``'google'``,
``'strava:<id>'``); ``core_shared.merged_alias_keys`` maps them onto the link
store's names the merge recorded under.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from core_shared.merged_alias_keys import merged_alias_key


@dataclass(frozen=True)
class ExternalRecord:
    """An inbound record a journal holds, as a link store names it."""

    integration_source: str
    external_id: str
    calendar_id: UUID | None = None
    external_identity: str | None = None
    recurring_event_id: str | None = None


@dataclass(frozen=True)
class MergedAlias:
    """An absorbed record and the journal that now answers for it."""

    journal_id: int
    user_id: str
    integration_source: str
    external_id: str
    calendar_id: UUID | None
    external_identity: str | None
    recurring_event_id: str | None


_COLUMNS = (
    "journal_id, user_id, integration_source, external_id, calendar_id, "
    "external_identity, recurring_event_id"
)


class MergedAliasRepository:
    """Read and write merged aliases.

    Args:
        connection: An async connection (backend) or session (workers).
    """

    def __init__(self, connection: AsyncConnection | AsyncSession) -> None:
        self._conn = connection

    async def find_alias(
        self,
        *,
        user_id: str,
        payload_source: str | None,
        external_id: str,
        external_identity: str | None = None,
    ) -> MergedAlias | None:
        """The alias for this record of ``user_id``'s, if a merge absorbed it.

        Matched on the record's id first, then on its cross-calendar identity
        from **any** calendar — another calendar's copy of an absorbed event
        is the same event, and so is the event after it moved calendars.
        """
        key = merged_alias_key(payload_source, external_id)
        if key is None:
            return None
        result = await self._conn.execute(
            text(f"""
                SELECT {_COLUMNS}
                FROM journal_merged_aliases
                WHERE user_id = :user_id
                  AND integration_source = :integration_source
                  AND (external_id = :external_id
                       OR (CAST(:external_identity AS VARCHAR) IS NOT NULL
                           AND external_identity = :external_identity))
                ORDER BY (external_id = :external_id) DESC, id
                LIMIT 1
            """),
            {
                "user_id": user_id,
                "integration_source": key.integration_source,
                "external_id": key.external_id,
                "external_identity": external_identity,
            },
        )
        row = result.fetchone()
        return _to_alias(row) if row else None

    async def aliases_for_journal(self, journal_id: int) -> list[MergedAlias]:
        """Every alias a journal holds, oldest first."""
        result = await self._conn.execute(
            text(f"""
                SELECT {_COLUMNS}
                FROM journal_merged_aliases
                WHERE journal_id = :journal_id
                ORDER BY id
            """),
            {"journal_id": journal_id},
        )
        return [_to_alias(row) for row in result.fetchall()]

    async def record_aliases(
        self,
        *,
        journal_id: int,
        user_id: str,
        records: Sequence[ExternalRecord],
    ) -> None:
        """Make ``journal_id`` answer for ``records``.

        A record already aliased keeps the journal it has: an alias is only
        ever re-pointed by merging that journal, never by a second record.
        """
        for record in records:
            await self._conn.execute(
                text("""
                    INSERT INTO journal_merged_aliases
                        (journal_id, user_id, integration_source, external_id,
                         calendar_id, external_identity, recurring_event_id)
                    VALUES (:journal_id, :user_id, :integration_source,
                            :external_id, :calendar_id, :external_identity,
                            :recurring_event_id)
                    ON CONFLICT (user_id, integration_source, external_id)
                    DO NOTHING
                """),
                {
                    "journal_id": journal_id,
                    "user_id": user_id,
                    "integration_source": record.integration_source,
                    "external_id": record.external_id,
                    "calendar_id": record.calendar_id,
                    "external_identity": record.external_identity,
                    "recurring_event_id": record.recurring_event_id,
                },
            )

    async def repoint_aliases(
        self, *, source_journal_id: int, target_journal_id: int
    ) -> None:
        """Move a merged-away journal's aliases onto the journal absorbing it."""
        await self._conn.execute(
            text("""
                UPDATE journal_merged_aliases
                SET journal_id = :target_journal_id
                WHERE journal_id = :source_journal_id
            """),
            {
                "source_journal_id": source_journal_id,
                "target_journal_id": target_journal_id,
            },
        )


def _to_alias(row: Row[Any]) -> MergedAlias:
    return MergedAlias(
        journal_id=row.journal_id,
        user_id=row.user_id,
        integration_source=row.integration_source,
        external_id=row.external_id,
        calendar_id=row.calendar_id,
        external_identity=row.external_identity,
        recurring_event_id=row.recurring_event_id,
    )
