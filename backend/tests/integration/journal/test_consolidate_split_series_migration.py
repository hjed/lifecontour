"""Migration test for 0122 (fold split recurrences into one series).

Editing a Google recurring event with "this and following events" gives the
rest of the recurrence a new master id, ``<master>_R<start>``. Calendar sync
keyed a series on that id, so every split became a series of its own. 0122
folds each ``(user, calendar, root id)`` group into one survivor and records
every folded key as an alias of it, so a payload still carrying a split's own
id resolves to the survivor instead of re-creating the split.

The cases:

- a root series and two of its splits fold into the root series, keeping a
  member the user added by hand to a split;
- splits whose root series never synced fold into the earliest, which takes
  the root key and stays reachable through its old one;
- a root already merged into another series pulls its splits into that series,
  and an alias a split held from an earlier merge follows them;
- a manual series and an unsplit recurring series are left alone.

Runs against an isolated throwaway database so the shared session DB is
untouched.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.journal.adapters.sql.journal_series_repository import (
    SqlJournalSeriesRepository,
)

_PREVIOUS_REVISION = "0121"
_REVISION = "0122"

USER_ID = "user-split-series"
CALENDAR_ID = UUID("00000000-0000-4000-8000-000000000122")
ROOT = "4mjae2cn4uaccq7n41clrsjaso"
FIRST_SPLIT = f"{ROOT}_R20240115T231500"
SECOND_SPLIT = f"{ROOT}_R20240301T231500"
CREATED = datetime(2026, 9, 27, tzinfo=UTC)

ROOT_SERIES = UUID("00000000-0000-4000-8000-0000000000a0")
FIRST_SERIES = UUID("00000000-0000-4000-8000-0000000000a1")
SECOND_SERIES = UUID("00000000-0000-4000-8000-0000000000a2")
MANUAL_SERIES = UUID("00000000-0000-4000-8000-0000000000b0")
UNSPLIT_SERIES = UUID("00000000-0000-4000-8000-0000000000c0")

Statement = tuple[str, dict[str, object]]


async def _execute(url: str, statements: list[Statement]) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for statement, params in statements:
                await conn.execute(text(statement), params)
    finally:
        await engine.dispose()


async def _rows(url: str, statement: str) -> list[tuple[object, ...]]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(statement), {"user_id": USER_ID})
            return [tuple(row) for row in result]
    finally:
        await engine.dispose()


async def _series(url: str) -> dict[UUID, str | None]:
    """The user's series, id → recurrence key."""
    rows = await _rows(
        url,
        "SELECT id, recurring_event_id FROM journal_series WHERE user_id = :user_id",
    )
    return {UUID(str(row[0])): row[1] for row in rows}  # type: ignore[misc]


async def _members(url: str) -> dict[UUID, set[int]]:
    rows = await _rows(
        url,
        """
        SELECT m.series_id, m.journal_id
        FROM journal_series_members m
        JOIN journal_series s ON s.id = m.series_id
        WHERE s.user_id = :user_id
        """,
    )
    members: dict[UUID, set[int]] = {}
    for series_id, journal_id in rows:
        members.setdefault(UUID(str(series_id)), set()).add(int(journal_id))  # type: ignore[call-overload]
    return members


async def _aliases(url: str) -> dict[str, UUID]:
    """Alias recurrence key → the series it resolves to."""
    rows = await _rows(
        url,
        """
        SELECT recurring_event_id, series_id
        FROM journal_series_recurrence_aliases
        WHERE user_id = :user_id
        """,
    )
    return {str(key): UUID(str(series_id)) for key, series_id in rows}


def _calendar() -> list[Statement]:
    return [
        (
            """
            INSERT INTO calendars (id, user_id, name, color)
            VALUES (:calendar_id, :user_id, 'Work', '#ffffff')
            """,
            {"calendar_id": CALENDAR_ID, "user_id": USER_ID},
        )
    ]


def _journals(*journal_ids: int) -> list[Statement]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        (
            """
            INSERT INTO journals (id, user_id, title, content,
                                  event_date_range_start, event_date_range_end)
            VALUES (:journal_id, :user_id, 'Arcane Stand-Up', '', :start, :start)
            """,
            {
                "journal_id": journal_id,
                "user_id": USER_ID,
                "start": start + timedelta(days=journal_id),
            },
        )
        for journal_id in journal_ids
    ]


def _series_row(
    series_id: UUID,
    recurring_event_id: str | None,
    *,
    created_at: datetime = CREATED,
    name: str = "Arcane Stand-Up",
) -> list[Statement]:
    return [
        (
            """
            INSERT INTO journal_series
                (id, user_id, name, calendar_id, recurring_event_id,
                 created_at, updated_at)
            VALUES
                (:id, :user_id, :name, :calendar_id, :recurring_event_id,
                 :created_at, :created_at)
            """,
            {
                "id": series_id,
                "user_id": USER_ID,
                "name": name,
                "calendar_id": CALENDAR_ID if recurring_event_id else None,
                "recurring_event_id": recurring_event_id,
                "created_at": created_at,
            },
        )
    ]


def _member(series_id: UUID, journal_id: int) -> list[Statement]:
    return [
        (
            """
            INSERT INTO journal_series_members (series_id, journal_id)
            VALUES (:series_id, :journal_id)
            """,
            {"series_id": series_id, "journal_id": journal_id},
        )
    ]


def _alias(recurring_event_id: str, series_id: UUID) -> list[Statement]:
    return [
        (
            """
            INSERT INTO journal_series_recurrence_aliases
                (calendar_id, recurring_event_id, series_id, user_id)
            VALUES (:calendar_id, :recurring_event_id, :series_id, :user_id)
            """,
            {
                "calendar_id": CALENDAR_ID,
                "recurring_event_id": recurring_event_id,
                "series_id": series_id,
                "user_id": USER_ID,
            },
        )
    ]


@pytest.mark.integration
@pytest.mark.slow
class TestConsolidateSplitSeriesMigration:
    """0122 folds every split of a recurrence into one series."""

    async def test_splits_fold_into_the_root_series(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(
            url,
            _calendar()
            + _journals(1, 2, 3, 4, 5, 6)
            + _series_row(ROOT_SERIES, ROOT)
            + _series_row(FIRST_SERIES, FIRST_SPLIT)
            + _series_row(SECOND_SERIES, SECOND_SPLIT)
            + _series_row(MANUAL_SERIES, None, name="Physio")
            + _series_row(UNSPLIT_SERIES, "otherseries", name="Board Games")
            + _member(ROOT_SERIES, 1)
            + _member(FIRST_SERIES, 2)
            + _member(SECOND_SERIES, 3)
            # Added to a split by hand, and already in the root too.
            + _member(SECOND_SERIES, 1)
            + _member(MANUAL_SERIES, 4)
            + _member(MANUAL_SERIES, 2)
            + _member(UNSPLIT_SERIES, 5),
        )

        run_alembic(url, "upgrade", _REVISION)

        assert await _series(url) == {
            ROOT_SERIES: ROOT,
            MANUAL_SERIES: None,
            UNSPLIT_SERIES: "otherseries",
        }
        assert await _members(url) == {
            ROOT_SERIES: {1, 2, 3},
            MANUAL_SERIES: {2, 4},
            UNSPLIT_SERIES: {5},
        }
        assert await _aliases(url) == {
            FIRST_SPLIT: ROOT_SERIES,
            SECOND_SPLIT: ROOT_SERIES,
        }

    async def test_splits_without_a_root_series_fold_into_the_earliest(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(
            url,
            _calendar()
            + _journals(1, 2)
            + _series_row(SECOND_SERIES, SECOND_SPLIT, created_at=CREATED)
            + _series_row(
                FIRST_SERIES, FIRST_SPLIT, created_at=CREATED + timedelta(seconds=1)
            )
            + _member(FIRST_SERIES, 1)
            + _member(SECOND_SERIES, 2),
        )

        run_alembic(url, "upgrade", _REVISION)

        assert await _series(url) == {SECOND_SERIES: ROOT}
        assert await _members(url) == {SECOND_SERIES: {1, 2}}
        assert await _aliases(url) == {
            FIRST_SPLIT: SECOND_SERIES,
            SECOND_SPLIT: SECOND_SERIES,
        }

        # A sync payload from before the fix still names a split by its own
        # id; it must land in the survivor, not re-create the split.
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                repo = SqlJournalSeriesRepository(conn)
                for key in (FIRST_SPLIT, SECOND_SPLIT, ROOT):
                    series = await repo.get_or_create_by_recurrence(
                        user_id=USER_ID,
                        calendar_id=CALENDAR_ID,
                        recurring_event_id=key,
                        name="Arcane Stand-Up",
                    )
                    assert series.id == SECOND_SERIES
        finally:
            await engine.dispose()
        assert set(await _series(url)) == {SECOND_SERIES}

    async def test_a_root_merged_away_pulls_its_splits_after_it(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(
            url,
            _calendar()
            + _journals(1, 2, 3)
            + _series_row(MANUAL_SERIES, None, name="Stand-ups")
            + _series_row(FIRST_SERIES, FIRST_SPLIT)
            + _member(MANUAL_SERIES, 1)
            + _member(FIRST_SERIES, 2)
            + _member(FIRST_SERIES, 3)
            # The user merged the root into "Stand-ups", and the second split
            # into the first.
            + _alias(ROOT, MANUAL_SERIES)
            + _alias(SECOND_SPLIT, FIRST_SERIES),
        )

        run_alembic(url, "upgrade", _REVISION)

        assert await _series(url) == {MANUAL_SERIES: None}
        assert await _members(url) == {MANUAL_SERIES: {1, 2, 3}}
        assert await _aliases(url) == {
            ROOT: MANUAL_SERIES,
            FIRST_SPLIT: MANUAL_SERIES,
            SECOND_SPLIT: MANUAL_SERIES,
        }
