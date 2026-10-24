"""Migration round-trip test for 0142 (each user's own Strava calendar).

Every user's Strava activities were linked on one synthetic calendar, created
by the first sync and so owned by whoever synced first: no one else saw it in
their calendar list (#1856). 0142 moves each owner's rows, and the pending
events that would recreate the shared calendar, onto the owner's own calendar
and deletes the shared one. Its downgrade moves them back, refusing while two
owners link one activity.
"""

import json

import pytest
from core_shared.integration_constants import SyntheticCalendar, synthetic_calendar_id
from sqlalchemy.engine import URL

from tests.integration.migration_helpers import RunAlembic, execute, load_revision
from tests.integration.synthetic_calendar_migration_seeding import (
    event_calendars,
    link_calendars,
    rows,
    seed_calendar,
    seed_event,
    seed_import,
    seed_merged_alias,
)

migration = load_revision("0142_scope_strava_calendar_to_owner.py")

OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_OWNER = "1b2c3d4e-0000-4000-8000-fedcbafedcba"
SHARED = "00000000-0000-0000-0000-000000000001"
_SOURCE = "strava"

_PREVIOUS_REVISION = "0141"
_REVISION = "0142"


def _own(owner: str) -> str:
    return synthetic_calendar_id(SyntheticCalendar.STRAVA, owner)


async def _shared_calendar(url: str, owner: str) -> None:
    await seed_calendar(url, SHARED, owner, source=_SOURCE, name="Strava Activities")


async def _event(
    url: str, owner: str, *, relayed: bool = False, calendar_id: str = SHARED
) -> None:
    await seed_event(
        url,
        owner,
        source=_SOURCE,
        calendar_id=calendar_id,
        external_event_id="strava:30",
        relayed=relayed,
    )


async def _cancellation(url: str, owner: str, journal_id: int) -> None:
    """A deleted activity's event, which names its calendar only once."""
    await execute(
        url,
        """
        INSERT INTO outbox_events
            (event_id, event_type, aggregate_id, event_data,
             occurred_at, created_at, retry_count)
        VALUES (gen_random_uuid()::text, 'journal_event.cancelled', 0, :data,
                now(), now(), 0)
        """,
        {
            "data": json.dumps(
                {
                    "integration_source": _SOURCE,
                    "calendar_id": SHARED,
                    "journal_data": {"user_id": owner},
                    "external_event_id": "strava:9",
                    "sync_action": "cancelled",
                    "existing_journal_id": journal_id,
                }
            )
        },
    )


@pytest.mark.integration
@pytest.mark.slow
class TestScopeStravaCalendarToOwner:
    def test_the_migration_names_calendars_as_the_worker_does(self) -> None:
        assert migration.owner_calendar_id(OWNER) == _own(OWNER)

    def test_it_moves_the_calendar_the_old_worker_shared(self) -> None:
        from app.core.integrations.journal_outbox_event_processor import (
            LEGACY_SHARED_STRAVA_CALENDAR_ID,
        )

        assert (
            migration.SHARED_CALENDAR_ID == SHARED == LEGACY_SHARED_STRAVA_CALENDAR_ID
        )

    async def test_each_owners_rows_move_to_their_own_calendar(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _shared_calendar(url, OWNER)
        mine = await seed_import(url, OWNER, "strava:9", SHARED)
        await seed_import(url, OTHER_OWNER, "strava:10", SHARED)
        await seed_merged_alias(
            url, OWNER, mine, "8", source=_SOURCE, calendar_id=SHARED
        )
        await _event(url, OTHER_OWNER, relayed=False)
        await _event(url, OWNER, relayed=True)

        run_alembic(url, "upgrade", _REVISION)

        assert sorted(
            await rows(
                url,
                "SELECT CAST(id AS text), user_id, name, color, integration_source "
                "FROM calendars",
            )
        ) == sorted(
            [
                (_own(OWNER), OWNER, "Strava Activities", "#FC4C02", _SOURCE),
                (
                    _own(OTHER_OWNER),
                    OTHER_OWNER,
                    "Strava Activities",
                    "#FC4C02",
                    _SOURCE,
                ),
            ]
        )
        assert await link_calendars(url) == [
            (OTHER_OWNER, _own(OTHER_OWNER), _own(OTHER_OWNER)),
            (OWNER, _own(OWNER), _own(OWNER)),
        ]
        assert await rows(
            url, "SELECT CAST(calendar_id AS text) FROM journal_merged_aliases"
        ) == [(_own(OWNER),)]
        # A relayed event is history; only a pending one would still be applied.
        assert await event_calendars(url) == [
            (OTHER_OWNER, False, _own(OTHER_OWNER), _own(OTHER_OWNER)),
            (OWNER, True, SHARED, SHARED),
        ]

    async def test_a_link_the_new_worker_already_made_supersedes_the_shared_one(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The new worker can run before this migration does.

        The backend still on the old revision then applies its update of an
        imported activity on the user's own calendar, linking the journal there
        beside its shared-calendar link. Moving that link would collide with the
        newer one, so the newer one is kept.
        """
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _shared_calendar(url, OWNER)
        journal_id = await seed_import(url, OWNER, "strava:9", SHARED)
        await seed_calendar(
            url, _own(OWNER), OWNER, source=_SOURCE, name="Strava Activities"
        )
        await execute(
            url,
            """
            INSERT INTO journal_external_event_links
                (journal_id, calendar_id, external_event_id, sync_capability,
                 sync_status)
            VALUES (:journal_id, CAST(:calendar_id AS uuid), 'strava:9',
                    'bidirectional', 'synced')
            """,
            {"journal_id": journal_id, "calendar_id": _own(OWNER)},
        )

        run_alembic(url, "upgrade", _REVISION)

        assert await link_calendars(url) == [(OWNER, _own(OWNER), _own(OWNER))]
        assert await rows(url, "SELECT CAST(id AS text) FROM calendars") == [
            (_own(OWNER),)
        ]

    async def test_a_pending_cancellation_moves_with_its_owner(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _shared_calendar(url, OWNER)
        journal_id = await seed_import(url, OWNER, "strava:9", SHARED)
        await _cancellation(url, OWNER, journal_id)

        run_alembic(url, "upgrade", _REVISION)

        [(raw,)] = await rows(url, "SELECT event_data FROM outbox_events")
        data = json.loads(raw)
        assert data["calendar_id"] == _own(OWNER)
        assert "calendar_info_data" not in data
        assert data["existing_journal_id"] == journal_id

    async def test_downgrade_moves_everything_back(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _shared_calendar(url, OWNER)
        await seed_import(url, OWNER, "strava:9", SHARED)
        await seed_import(url, OTHER_OWNER, "strava:10", SHARED)
        run_alembic(url, "upgrade", _REVISION)

        run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert await rows(url, "SELECT CAST(id AS text), user_id FROM calendars") == [
            (SHARED, OTHER_OWNER)
        ]
        assert await link_calendars(url) == [
            (OTHER_OWNER, SHARED, SHARED),
            (OWNER, SHARED, SHARED),
        ]

    async def test_downgrade_returns_a_first_import_still_only_an_event(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """Its calendar is only created when the event is applied, so no
        calendar row leads the downgrade to it."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)
        await _event(url, OWNER, calendar_id=_own(OWNER))

        run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert await event_calendars(url) == [(OWNER, False, SHARED, SHARED)]

    async def test_downgrade_refuses_an_activity_two_owners_link(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """Two accounts connected to one Strava athlete each import the same
        activity on their own calendar, which one shared calendar cannot hold."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)
        for owner in (OWNER, OTHER_OWNER):
            await seed_calendar(
                url, _own(owner), owner, source=_SOURCE, name="Strava Activities"
            )
            await seed_import(url, owner, "strava:9", _own(owner))

        with pytest.raises(RuntimeError, match="strava:9"):
            run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert await rows(url, "SELECT count(*) FROM journal_external_event_links") == [
            (2,)
        ]
