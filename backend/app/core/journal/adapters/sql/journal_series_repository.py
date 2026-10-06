"""SQL implementation of JournalSeriesRepository."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.journal_series import JournalSeries
from app.core.journal.models.repositories import JournalSeriesRepository

_SERIES_COLUMNS = (
    "id, user_id, name, description, calendar_id, recurring_event_id, "
    "created_at, updated_at"
)

_QUALIFIED_SERIES_COLUMNS = (
    "s.id, s.user_id, s.name, s.description, s.calendar_id, "
    "s.recurring_event_id, s.created_at, s.updated_at"
)


def _row_to_series(row: Any) -> JournalSeries:
    return JournalSeries(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        description=row.description,
        calendar_id=row.calendar_id,
        recurring_event_id=row.recurring_event_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlJournalSeriesRepository(JournalSeriesRepository):
    """SQL implementation of the journal series repository."""

    def __init__(self, conn: AsyncConnection):
        """Initialize with database connection."""
        self.conn = conn

    async def find_by_id(self, series_id: UUID, user_id: str) -> JournalSeries | None:
        """Find a series by ID, scoped to the owning user."""
        query = text(
            f"""
            SELECT {_SERIES_COLUMNS}
            FROM journal_series
            WHERE id = :series_id AND user_id = :user_id
            """
        )
        result = await self.conn.execute(
            query, {"series_id": series_id, "user_id": user_id}
        )
        row = result.fetchone()
        return _row_to_series(row) if row else None

    async def find_all(self, user_id: str) -> list[JournalSeries]:
        """Get all series for a user, ordered by name."""
        query = text(
            f"""
            SELECT {_SERIES_COLUMNS}
            FROM journal_series
            WHERE user_id = :user_id
            ORDER BY name
            """
        )
        result = await self.conn.execute(query, {"user_id": user_id})
        return [_row_to_series(row) for row in result.fetchall()]

    async def save(self, series: JournalSeries) -> JournalSeries:
        """Save a series (insert when id is None, update otherwise)."""
        if series.id is None:
            query = text(
                """
                INSERT INTO journal_series
                    (user_id, name, description, calendar_id, recurring_event_id)
                VALUES
                    (:user_id, :name, :description, :calendar_id, :recurring_event_id)
                RETURNING id, created_at, updated_at
                """
            )
            result = await self.conn.execute(
                query,
                {
                    "user_id": series.user_id,
                    "name": series.name,
                    "description": series.description,
                    "calendar_id": series.calendar_id,
                    "recurring_event_id": series.recurring_event_id,
                },
            )
            row = result.fetchone()
            if row is not None:
                series.id = row.id
                series.created_at = row.created_at
                series.updated_at = row.updated_at
        else:
            query = text(
                """
                UPDATE journal_series
                SET name = :name, description = :description, updated_at = now()
                WHERE id = :id AND user_id = :user_id
                RETURNING updated_at
                """
            )
            result = await self.conn.execute(
                query,
                {
                    "id": series.id,
                    "user_id": series.user_id,
                    "name": series.name,
                    "description": series.description,
                },
            )
            row = result.fetchone()
            if row is not None:
                series.updated_at = row.updated_at

        return series

    async def delete(self, series_id: UUID, user_id: str) -> None:
        """Delete a series; memberships cascade, member journals are untouched."""
        query = text(
            """
            DELETE FROM journal_series
            WHERE id = :series_id AND user_id = :user_id
            """
        )
        await self.conn.execute(query, {"series_id": series_id, "user_id": user_id})

    async def get_or_create_by_recurrence(
        self,
        user_id: str,
        calendar_id: UUID,
        recurring_event_id: str,
        name: str,
        split_recurring_event_id: str | None = None,
    ) -> JournalSeries:
        """Get or atomically create the series for a recurring calendar event.

        A recurrence merged into another series resolves through its alias.
        Otherwise relies on the partial unique index on
        (calendar_id, recurring_event_id): INSERT ... ON CONFLICT DO NOTHING
        followed by a SELECT is race-safe and never renames an existing series.

        A split recurrence's own id is checked for an alias first: a split the
        user merged into another series keeps following that merge.

        The per-key advisory lock orders this against ``alias_recurrences``:
        without it a sync could read "no alias", the merge could commit and
        free the unique key, and the INSERT would re-create the merged series.
        Both keys are locked in the order ``alias_recurrences`` uses, so the
        two cannot deadlock.
        """
        lookup_keys = [
            key for key in (split_recurring_event_id, recurring_event_id) if key
        ]
        for lock_calendar_id, key in sorted(
            {(calendar_id, key) for key in lookup_keys}, key=str
        ):
            await self._lock_recurrence(lock_calendar_id, key)
        for key in lookup_keys:
            aliased = await self._find_by_alias(user_id, calendar_id, key)
            if aliased is not None:
                return aliased

        insert_query = text(
            """
            INSERT INTO journal_series
                (user_id, name, calendar_id, recurring_event_id)
            VALUES
                (:user_id, :name, :calendar_id, :recurring_event_id)
            ON CONFLICT (calendar_id, recurring_event_id)
                WHERE recurring_event_id IS NOT NULL
                DO NOTHING
            """
        )
        await self.conn.execute(
            insert_query,
            {
                "user_id": user_id,
                "name": name,
                "calendar_id": calendar_id,
                "recurring_event_id": recurring_event_id,
            },
        )
        select_query = text(
            f"""
            SELECT {_SERIES_COLUMNS}
            FROM journal_series
            WHERE calendar_id = :calendar_id
              AND recurring_event_id = :recurring_event_id
              AND user_id = :user_id
            """
        )
        result = await self.conn.execute(
            select_query,
            {
                "calendar_id": calendar_id,
                "recurring_event_id": recurring_event_id,
                "user_id": user_id,
            },
        )
        row = result.fetchone()
        if row is None:  # pragma: no cover - defensive; the insert guarantees a row
            raise RuntimeError(
                "journal_series get_or_create failed for "
                f"calendar={calendar_id} recurring_event_id={recurring_event_id}"
            )
        return _row_to_series(row)

    async def lock_for_merge(
        self, series_ids: Sequence[UUID], user_id: str
    ) -> set[UUID]:
        """Lock the user's series rows a merge reads and writes, until commit.

        Rows are locked in id order so two merges sharing a series cannot
        deadlock. Without this, merging A into B and B into C at the same time
        lets the second read B before the first commits, then delete B,
        cascading away the alias and members the first moved into it.
        """
        result = await self.conn.execute(
            text(
                """
                SELECT id FROM journal_series
                WHERE id = ANY(:series_ids) AND user_id = :user_id
                ORDER BY id
                FOR UPDATE
                """
            ),
            {"series_ids": list(series_ids), "user_id": user_id},
        )
        return {row.id for row in result}

    async def alias_recurrences(
        self, absorbed: JournalSeries, into_series_id: UUID
    ) -> None:
        """Point ``absorbed``'s recurrences at ``into_series_id`` before a merge.

        Existing aliases are re-pointed so merge chains collapse onto the
        latest survivor. A manual series, or one whose calendar was deleted,
        has no recurrence key of its own to alias.

        Every key ``absorbed`` answers for (its own and each it inherited) is
        locked first, in a fixed order so two merges cannot deadlock, and held
        until the transaction ends. A sync for any of them then either
        committed its membership before this (so moving the members carries
        it) or waits and resolves to the survivor. Call it **before** moving
        the members: a sync let through between the move and the delete would
        add a journal the delete then drops.
        """
        inherited = await self.conn.execute(
            text(
                """
                SELECT calendar_id, recurring_event_id
                FROM journal_series_recurrence_aliases
                WHERE series_id = :absorbed_id
                """
            ),
            {"absorbed_id": absorbed.id},
        )
        keys = {(row.calendar_id, row.recurring_event_id) for row in inherited}
        if absorbed.calendar_id is not None and absorbed.recurring_event_id:
            keys.add((absorbed.calendar_id, absorbed.recurring_event_id))
        for calendar_id, recurring_event_id in sorted(keys, key=str):
            await self._lock_recurrence(calendar_id, recurring_event_id)

        await self.conn.execute(
            text(
                """
                UPDATE journal_series_recurrence_aliases
                SET series_id = :into_series_id
                WHERE series_id = :absorbed_id
                """
            ),
            {"into_series_id": into_series_id, "absorbed_id": absorbed.id},
        )
        if absorbed.calendar_id is None or absorbed.recurring_event_id is None:
            return
        await self.conn.execute(
            text(
                """
                INSERT INTO journal_series_recurrence_aliases
                    (calendar_id, recurring_event_id, series_id, user_id)
                VALUES
                    (:calendar_id, :recurring_event_id, :series_id, :user_id)
                ON CONFLICT (calendar_id, recurring_event_id)
                    DO UPDATE SET series_id = EXCLUDED.series_id
                """
            ),
            {
                "calendar_id": absorbed.calendar_id,
                "recurring_event_id": absorbed.recurring_event_id,
                "series_id": into_series_id,
                "user_id": absorbed.user_id,
            },
        )

    async def move_members(self, from_series_id: UUID, to_series_id: UUID) -> None:
        """Move every member of one series into another (shared members dedupe)."""
        await self.conn.execute(
            text(
                """
                WITH moved AS (
                    DELETE FROM journal_series_members
                    WHERE series_id = :from_series_id
                    RETURNING journal_id
                )
                INSERT INTO journal_series_members (series_id, journal_id)
                SELECT :to_series_id, journal_id FROM moved
                ON CONFLICT (series_id, journal_id) DO NOTHING
                """
            ),
            {"from_series_id": from_series_id, "to_series_id": to_series_id},
        )

    async def _lock_recurrence(
        self, calendar_id: UUID, recurring_event_id: str
    ) -> None:
        """Serialise work on one recurrence key until the transaction ends."""
        await self.conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"journal_series_recurrence:{calendar_id}:{recurring_event_id}"},
        )

    async def _find_by_alias(
        self, user_id: str, calendar_id: UUID, recurring_event_id: str
    ) -> JournalSeries | None:
        result = await self.conn.execute(
            text(
                f"""
                SELECT {_QUALIFIED_SERIES_COLUMNS}
                FROM journal_series_recurrence_aliases a
                JOIN journal_series s ON s.id = a.series_id
                WHERE a.calendar_id = :calendar_id
                  AND a.recurring_event_id = :recurring_event_id
                  AND s.user_id = :user_id
                """
            ),
            {
                "calendar_id": calendar_id,
                "recurring_event_id": recurring_event_id,
                "user_id": user_id,
            },
        )
        row = result.fetchone()
        return _row_to_series(row) if row else None

    async def add_member(self, series_id: UUID, journal_id: int) -> None:
        """Add a journal to a series (no-op if already a member)."""
        query = text(
            """
            INSERT INTO journal_series_members (series_id, journal_id)
            VALUES (:series_id, :journal_id)
            ON CONFLICT (series_id, journal_id) DO NOTHING
            """
        )
        await self.conn.execute(
            query, {"series_id": series_id, "journal_id": journal_id}
        )

    async def remove_member(self, series_id: UUID, journal_id: int) -> None:
        """Remove a journal from a series (no-op if not a member)."""
        query = text(
            """
            DELETE FROM journal_series_members
            WHERE series_id = :series_id AND journal_id = :journal_id
            """
        )
        await self.conn.execute(
            query, {"series_id": series_id, "journal_id": journal_id}
        )

    async def get_member_journal_ids(self, series_id: UUID) -> list[int]:
        """Get the journal IDs belonging to a series."""
        query = text(
            """
            SELECT m.journal_id
            FROM journal_series_members m
            JOIN journals j ON j.id = m.journal_id
            WHERE m.series_id = :series_id
            ORDER BY j.event_date_range_start, m.journal_id
            """
        )
        result = await self.conn.execute(query, {"series_id": series_id})
        return [row.journal_id for row in result.fetchall()]

    async def get_series_for_journal(
        self, journal_id: int, user_id: str
    ) -> list[JournalSeries]:
        """Get all series a journal belongs to, scoped to the owning user."""
        query = text(
            f"""
            SELECT {_QUALIFIED_SERIES_COLUMNS}
            FROM journal_series s
            JOIN journal_series_members m ON m.series_id = s.id
            WHERE m.journal_id = :journal_id AND s.user_id = :user_id
            ORDER BY s.name
            """
        )
        result = await self.conn.execute(
            query, {"journal_id": journal_id, "user_id": user_id}
        )
        return [_row_to_series(row) for row in result.fetchall()]

    async def get_series_names_for_journal_ids(
        self, journal_ids: list[int], user_id: str
    ) -> dict[int, list[str]]:
        """Bulk-fetch series names per journal (journals without series omitted)."""
        if not journal_ids:
            return {}
        query = text(
            """
            SELECT m.journal_id, s.name
            FROM journal_series_members m
            JOIN journal_series s ON s.id = m.series_id
            WHERE m.journal_id = ANY(:journal_ids) AND s.user_id = :user_id
            ORDER BY m.journal_id, s.name
            """
        )
        result = await self.conn.execute(
            query, {"journal_ids": journal_ids, "user_id": user_id}
        )
        names: dict[int, list[str]] = {}
        for row in result.fetchall():
            names.setdefault(row.journal_id, []).append(row.name)
        return names
