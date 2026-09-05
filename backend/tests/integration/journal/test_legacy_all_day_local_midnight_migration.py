"""Migration round-trip test for 0109 (legacy all-day events to local midnight).

``journals.event_date_range_start/end`` hold the UTC instant of *local*
midnight. Before #1385 the Google inbound sync stored an imported all-day
event at **UTC** midnight of the Google date and recorded no zone on
``journal_calendar_info``, so for a negative-offset user those rows read a day
early in the calendar view and pushed back to Google a day early. 0109 moves
them onto the convention and records the zone they are anchored in.

The interesting part is *which* rows it claims. Every case below is a row that
matches some of the predicates but not all, plus the two it should move:

- a negative-offset user's row (the reported bug) and a positive-offset user's
  row (which read correctly before the fix and still has to move);
- a multi-day row spanning a DST change, where the two bounds take *different*
  offsets — the thing a fixed-delta shift would get wrong;
- an app-created row already at local midnight whose zone was cleared, a timed
  row, and an outbound-only link, none of which may be touched;
- a user with no ``user_settings`` row, repaired as UTC, and one whose
  configured zone PostgreSQL cannot resolve, left alone.

Runs against an isolated throwaway database so the shared session DB is
untouched.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

_PREVIOUS_REVISION = "0108"
_REVISION = "0109"

NY_USER = "user-new-york"
SYDNEY_USER = "user-sydney"
UNSET_USER = "user-without-settings"
BAD_ZONE_USER = "user-with-unresolvable-zone"

NEW_YORK = "America/New_York"
SYDNEY = "Australia/Sydney"

# 5 September 2026 as the legacy sync stored it: UTC midnight, no zone.
UTC_MIDNIGHT = datetime(2026, 9, 5, tzinfo=UTC)
# The same calendar date as local midnight in each zone.
NY_MIDNIGHT = datetime(2026, 9, 5, 4, tzinfo=UTC)
SYDNEY_MIDNIGHT = datetime(2026, 9, 4, 14, tzinfo=UTC)


async def _execute(url: str, statements: list[tuple[str, dict[str, object]]]) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for statement, params in statements:
                await conn.execute(text(statement), params)
    finally:
        await engine.dispose()


async def _event(url: str, journal_id: int) -> tuple[datetime, datetime, str | None]:
    """Return ``(start, end, jci.timezone)`` for a seeded journal."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        """
                        SELECT j.event_date_range_start AS start,
                               j.event_date_range_end AS "end",
                               jci.timezone AS timezone
                        FROM journals j
                        JOIN journal_calendar_info jci ON jci.journal_id = j.id
                        WHERE j.id = :journal_id
                        """
                    ),
                    {"journal_id": journal_id},
                )
            ).one()
            timezone = None if row.timezone is None else str(row.timezone)
            return row.start, row.end, timezone
    finally:
        await engine.dispose()


def _settings(user_id: str, timezone: str) -> list[tuple[str, dict[str, object]]]:
    return [
        (
            "INSERT INTO user_settings (user_id, timezone) VALUES (:user_id, :timezone)",
            {"user_id": user_id, "timezone": timezone},
        )
    ]


def _seed_event(
    *,
    journal_id: int,
    user_id: str,
    start: datetime,
    end: datetime,
    is_all_day: bool = True,
    timezone: str | None = None,
    sync_capability: str = "bidirectional",
) -> list[tuple[str, dict[str, object]]]:
    """One journal with calendar info and an external link, on its own calendar.

    Each journal gets its own calendar so the links' composite primary key
    cannot collide between the cases seeded into a single test.
    """
    calendar_id = f"00000000-0000-4000-8000-{journal_id:012d}"
    return [
        (
            """
            INSERT INTO calendars (id, user_id, name, color)
            VALUES (CAST(:calendar_id AS uuid), :user_id, :name, '#ffffff')
            """,
            {
                "calendar_id": calendar_id,
                "user_id": user_id,
                "name": f"Seeded calendar {journal_id}",
            },
        ),
        (
            """
            INSERT INTO journals (id, user_id, title, content,
                                  event_date_range_start, event_date_range_end)
            VALUES (:journal_id, :user_id, :title, '', :start, :end)
            """,
            {
                "journal_id": journal_id,
                "user_id": user_id,
                "title": f"Seeded event {journal_id}",
                "start": start,
                "end": end,
            },
        ),
        (
            """
            INSERT INTO journal_calendar_info (journal_id, calendar_id,
                                               is_all_day, timezone)
            VALUES (:journal_id, CAST(:calendar_id AS uuid), :is_all_day, :timezone)
            """,
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "is_all_day": is_all_day,
                "timezone": timezone,
            },
        ),
        (
            """
            INSERT INTO journal_external_event_links (journal_id, calendar_id,
                                                      external_event_id,
                                                      sync_capability, sync_status)
            VALUES (:journal_id, CAST(:calendar_id AS uuid), :external_event_id,
                    :sync_capability, 'synced')
            """,
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "external_event_id": f"google-event-{journal_id}",
                "sync_capability": sync_capability,
            },
        ),
    ]


@pytest.mark.integration
@pytest.mark.slow
class TestLegacyAllDayLocalMidnightMigration:
    """0109 re-anchors legacy imported all-day events onto local midnight."""

    async def test_moves_a_negative_offset_users_row_onto_local_midnight(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """The reported bug: New York read UTC midnight as the previous day."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(
            url,
            _settings(NY_USER, NEW_YORK)
            + _seed_event(
                journal_id=1,
                user_id=NY_USER,
                start=UTC_MIDNIGHT,
                end=UTC_MIDNIGHT,
            ),
        )

        run_alembic(url, "upgrade", _REVISION)

        assert await _event(url, 1) == (NY_MIDNIGHT, NY_MIDNIGHT, NEW_YORK)

    async def test_moves_a_positive_offset_users_row_too(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """Sydney read the legacy instant on the right day and still has to move.

        Leaving it would keep two spellings of the same all-day event in the
        database, one of which the frontend groups by the browser's clock.
        """
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(
            url,
            _settings(SYDNEY_USER, SYDNEY)
            + _seed_event(
                journal_id=2,
                user_id=SYDNEY_USER,
                start=UTC_MIDNIGHT,
                end=UTC_MIDNIGHT,
            ),
        )

        run_alembic(url, "upgrade", _REVISION)

        assert await _event(url, 2) == (SYDNEY_MIDNIGHT, SYDNEY_MIDNIGHT, SYDNEY)

    async def test_multi_day_row_across_a_dst_change_lands_on_both_midnights(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """31 Oct to 2 Nov in New York: the clocks go back between the bounds.

        The two bounds therefore take *different* offsets — -04:00 and -05:00 —
        so a fixed-delta shift would put the end an hour off midnight. Each
        bound is re-anchored from its own local date instead.
        """
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(
            url,
            _settings(NY_USER, NEW_YORK)
            + _seed_event(
                journal_id=3,
                user_id=NY_USER,
                start=datetime(2026, 10, 31, tzinfo=UTC),
                end=datetime(2026, 11, 2, tzinfo=UTC),
            ),
        )

        run_alembic(url, "upgrade", _REVISION)

        start, end, timezone = await _event(url, 3)
        assert start == datetime(2026, 10, 31, 4, tzinfo=UTC)
        assert end == datetime(2026, 11, 2, 5, tzinfo=UTC)
        assert timezone == NEW_YORK
        assert start <= end, "the ck_journals_event_date_range_valid CHECK survives"

    async def test_a_row_already_at_local_midnight_is_left_alone(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """An app-created all-day row whose zone was cleared is not legacy.

        It matches every predicate the issue names — all-day, no zone, a
        bidirectional link — but its instant is already local midnight, so
        moving it would push it a day out.
        """
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(
            url,
            _settings(NY_USER, NEW_YORK)
            + _seed_event(
                journal_id=4,
                user_id=NY_USER,
                start=NY_MIDNIGHT,
                end=NY_MIDNIGHT,
            ),
        )

        run_alembic(url, "upgrade", _REVISION)

        assert await _event(url, 4) == (NY_MIDNIGHT, NY_MIDNIGHT, None)

    async def test_a_timed_row_is_left_alone(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """A timed event's instants are the event, not a date to be re-read."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(
            url,
            _settings(NY_USER, NEW_YORK)
            + _seed_event(
                journal_id=5,
                user_id=NY_USER,
                start=UTC_MIDNIGHT,
                end=UTC_MIDNIGHT,
                is_all_day=False,
            ),
        )

        run_alembic(url, "upgrade", _REVISION)

        assert await _event(url, 5) == (UTC_MIDNIGHT, UTC_MIDNIGHT, None)

    async def test_an_outbound_only_link_is_left_alone(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """Outbound-only means the journal was written here, not imported."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(
            url,
            _settings(NY_USER, NEW_YORK)
            + _seed_event(
                journal_id=6,
                user_id=NY_USER,
                start=UTC_MIDNIGHT,
                end=UTC_MIDNIGHT,
                sync_capability="outbound",
            ),
        )

        run_alembic(url, "upgrade", _REVISION)

        assert await _event(url, 6) == (UTC_MIDNIGHT, UTC_MIDNIGHT, None)

    async def test_a_row_whose_calendar_info_records_a_zone_is_left_alone(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """A row synced since #1385 states its anchor and is already correct."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(
            url,
            _settings(NY_USER, NEW_YORK)
            + _seed_event(
                journal_id=7,
                user_id=NY_USER,
                start=UTC_MIDNIGHT,
                end=UTC_MIDNIGHT,
                timezone="UTC",
            ),
        )

        run_alembic(url, "upgrade", _REVISION)

        assert await _event(url, 7) == (UTC_MIDNIGHT, UTC_MIDNIGHT, "UTC")

    async def test_a_user_with_no_settings_row_is_repaired_as_utc(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """UTC is the zone the app itself falls back to, so the move is a no-op.

        Recording it still matters: without a zone the row inherits whatever
        the user configures *later*, and would read a day early the moment
        that is a negative offset.
        """
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(
            url,
            _seed_event(
                journal_id=8,
                user_id=UNSET_USER,
                start=UTC_MIDNIGHT,
                end=UTC_MIDNIGHT,
            ),
        )

        run_alembic(url, "upgrade", _REVISION)

        assert await _event(url, 8) == (UTC_MIDNIGHT, UTC_MIDNIGHT, "UTC")

    async def test_an_unresolvable_configured_zone_leaves_the_row_alone(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """``AT TIME ZONE`` raises on a name PostgreSQL does not know.

        Writing one onto the row would abort every read that resolves the
        column, so such a row keeps the instants and the NULL it has today.
        """
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(
            url,
            _settings(BAD_ZONE_USER, "Not/AZone")
            + _seed_event(
                journal_id=9,
                user_id=BAD_ZONE_USER,
                start=UTC_MIDNIGHT,
                end=UTC_MIDNIGHT,
            ),
        )

        run_alembic(url, "upgrade", _REVISION)

        assert await _event(url, 9) == (UTC_MIDNIGHT, UTC_MIDNIGHT, None)

    async def test_every_case_together_touches_only_the_legacy_rows(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """One database holding all of the above, migrated in a single pass."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(
            url,
            _settings(NY_USER, NEW_YORK)
            + _settings(SYDNEY_USER, SYDNEY)
            + _settings(BAD_ZONE_USER, "Not/AZone")
            + _seed_event(
                journal_id=11, user_id=NY_USER, start=UTC_MIDNIGHT, end=UTC_MIDNIGHT
            )
            + _seed_event(
                journal_id=12, user_id=SYDNEY_USER, start=UTC_MIDNIGHT, end=UTC_MIDNIGHT
            )
            + _seed_event(
                journal_id=13, user_id=NY_USER, start=NY_MIDNIGHT, end=NY_MIDNIGHT
            )
            + _seed_event(
                journal_id=14,
                user_id=NY_USER,
                start=UTC_MIDNIGHT,
                end=UTC_MIDNIGHT,
                is_all_day=False,
            )
            + _seed_event(
                journal_id=15,
                user_id=BAD_ZONE_USER,
                start=UTC_MIDNIGHT,
                end=UTC_MIDNIGHT,
            ),
        )

        run_alembic(url, "upgrade", _REVISION)

        assert await _event(url, 11) == (NY_MIDNIGHT, NY_MIDNIGHT, NEW_YORK)
        assert await _event(url, 12) == (SYDNEY_MIDNIGHT, SYDNEY_MIDNIGHT, SYDNEY)
        assert await _event(url, 13) == (NY_MIDNIGHT, NY_MIDNIGHT, None)
        assert await _event(url, 14) == (UTC_MIDNIGHT, UTC_MIDNIGHT, None)
        assert await _event(url, 15) == (UTC_MIDNIGHT, UTC_MIDNIGHT, None)

    async def test_empty_database_upgrades_and_downgrades(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        """A fresh install has nothing to repair, and the revision reverses."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)
        run_alembic(url, "downgrade", _PREVIOUS_REVISION)
        run_alembic(url, "upgrade", _REVISION)
