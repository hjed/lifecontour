"""Migration round-trip test for 0138 (each user's own Snipe-IT maintenance calendar).

Every user's Snipe-IT imports were linked on one shared synthetic calendar, so
two users' instances handing out the same maintenance id collided (#1510).
0138 moves each owner's rows, and the pending events that would recreate the
shared calendar, onto the owner's own calendar and deletes the shared one. Its
downgrade moves them back, refusing while two owners hold one record id.
"""

import pytest
from core_shared.integration_constants import SyntheticCalendar, synthetic_calendar_id
from sqlalchemy.engine import URL

from tests.integration.migration_helpers import RunAlembic, execute, load_revision
from tests.integration.synthetic_calendar_migration_seeding import (
    event_calendars,
    event_targets,
    link_calendars,
    rows,
    seed_calendar,
    seed_event,
    seed_import,
    seed_merged_alias,
)

migration = load_revision("0138_scope_snipeit_maintenance_calendar_to_owner.py")

OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_OWNER = "1b2c3d4e-0000-4000-8000-fedcbafedcba"
SHARED = migration.SHARED_CALENDAR_ID
_SOURCE = "snipeit_maintenance"

_PREVIOUS_REVISION = "0137"
_REVISION = "0138"


async def _shared_calendar(url: str, owner: str) -> None:
    await seed_calendar(
        url, SHARED, owner, source=_SOURCE, name="Snipeit_Maintenance Calendar"
    )


async def _merged_alias(
    url: str, owner: str, journal_id: int, external_id: str
) -> None:
    await seed_merged_alias(
        url, owner, journal_id, external_id, source=_SOURCE, calendar_id=SHARED
    )


async def _event(
    url: str,
    owner: str,
    *,
    relayed: bool = False,
    existing_journal_id: int | None = None,
    calendar_id: str = SHARED,
) -> None:
    await seed_event(
        url,
        owner,
        source=_SOURCE,
        calendar_id=calendar_id,
        external_event_id="snipeit_maint:30",
        relayed=relayed,
        existing_journal_id=existing_journal_id,
    )


@pytest.mark.integration
@pytest.mark.slow
class TestScopeSnipeItMaintenanceCalendarToOwner:
    def test_the_migration_names_calendars_as_the_worker_does(self) -> None:
        assert migration.owner_calendar_id(OWNER) == synthetic_calendar_id(
            SyntheticCalendar.SNIPEIT_MAINTENANCE, OWNER
        )

    async def test_each_owners_rows_move_to_their_own_calendar(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _shared_calendar(url, OWNER)
        mine = await seed_import(url, OWNER, "snipeit_maint:9", SHARED)
        await seed_import(url, OTHER_OWNER, "snipeit_maint:10", SHARED)
        await _merged_alias(url, OWNER, mine, "snipeit_maint:8")
        await _event(url, OTHER_OWNER, relayed=False)
        await _event(url, OWNER, relayed=True)

        run_alembic(url, "upgrade", _REVISION)

        mine_id = synthetic_calendar_id(SyntheticCalendar.SNIPEIT_MAINTENANCE, OWNER)
        theirs_id = synthetic_calendar_id(
            SyntheticCalendar.SNIPEIT_MAINTENANCE, OTHER_OWNER
        )
        assert sorted(
            await rows(
                url,
                "SELECT CAST(id AS text), user_id, name, integration_source "
                "FROM calendars",
            )
        ) == sorted(
            [
                (mine_id, OWNER, "Snipe-IT Maintenance", "snipeit_maintenance"),
                (theirs_id, OTHER_OWNER, "Snipe-IT Maintenance", "snipeit_maintenance"),
            ]
        )
        assert await link_calendars(url) == [
            (OTHER_OWNER, theirs_id, theirs_id),
            (OWNER, mine_id, mine_id),
        ]
        assert await rows(
            url, "SELECT CAST(calendar_id AS text) FROM journal_merged_aliases"
        ) == [(mine_id,)]
        # A relayed event is history; only a pending one would still be applied.
        assert await event_calendars(url) == [
            (OTHER_OWNER, False, theirs_id, theirs_id),
            (OWNER, True, SHARED, SHARED),
        ]

    async def test_a_pending_update_of_another_owners_journal_becomes_a_create(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The old worker found another user's link for this user's record and
        queued an update of their journal; moving its calendar alone would
        still aim it at that journal."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _shared_calendar(url, OWNER)
        theirs = await seed_import(url, OWNER, "snipeit_maint:30", SHARED)
        mine = await seed_import(url, OTHER_OWNER, "snipeit_maint:31", SHARED)
        await _event(url, OTHER_OWNER, existing_journal_id=theirs)
        await _event(url, OTHER_OWNER, existing_journal_id=mine)

        run_alembic(url, "upgrade", _REVISION)

        assert await event_targets(url) == [
            (OTHER_OWNER, "journal_event.created", "created", None),
            (OTHER_OWNER, "journal_event.updated", "updated", mine),
        ]

    async def test_downgrade_moves_everything_back(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _shared_calendar(url, OWNER)
        await seed_import(url, OWNER, "snipeit_maint:9", SHARED)
        run_alembic(url, "upgrade", _REVISION)

        run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert await rows(url, "SELECT CAST(id AS text), user_id FROM calendars") == [
            (SHARED, OWNER)
        ]
        assert await rows(
            url,
            "SELECT CAST(calendar_id AS text), external_event_id "
            "FROM journal_external_event_links",
        ) == [(SHARED, "snipeit_maint:9")]

    async def test_downgrade_returns_a_first_import_still_only_an_event(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """Its calendar is only created when the event is applied, so no
        calendar row leads the downgrade to it."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)
        await _event(
            url,
            OWNER,
            calendar_id=synthetic_calendar_id(
                SyntheticCalendar.SNIPEIT_MAINTENANCE, OWNER
            ),
        )

        run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert await event_calendars(url) == [(OWNER, False, SHARED, SHARED)]

    async def test_downgrade_refuses_a_record_id_two_owners_link(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _shared_calendar(url, OWNER)
        await seed_import(url, OWNER, "snipeit_maint:9", SHARED)
        run_alembic(url, "upgrade", _REVISION)
        await execute(
            url,
            """
            INSERT INTO calendars (id, user_id, name, color, integration_source)
            VALUES (CAST(:id AS uuid), :owner, 'Snipe-IT Maintenance', '#808080',
                    'snipeit_maintenance')
            """,
            {
                "id": synthetic_calendar_id(
                    SyntheticCalendar.SNIPEIT_MAINTENANCE, OTHER_OWNER
                ),
                "owner": OTHER_OWNER,
            },
        )
        await seed_import(
            url,
            OTHER_OWNER,
            "snipeit_maint:9",
            synthetic_calendar_id(SyntheticCalendar.SNIPEIT_MAINTENANCE, OTHER_OWNER),
        )

        with pytest.raises(RuntimeError, match="snipeit_maint:9"):
            run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert await rows(url, "SELECT count(*) FROM journal_external_event_links") == [
            (2,)
        ]
