"""Migration round-trip test for 0138 (each user's own Snipe-IT maintenance calendar).

Every user's Snipe-IT imports were linked on one shared synthetic calendar, so
two users' instances handing out the same maintenance id collided (#1510).
0138 moves each owner's rows, and the pending events that would recreate the
shared calendar, onto the owner's own calendar and deletes the shared one. Its
downgrade moves them back, refusing while two owners hold one record id.
"""

import json
from typing import Any

import pytest
from core_shared.integration_constants import snipeit_maintenance_calendar_id
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import RunAlembic, execute, load_revision

migration = load_revision("0138_scope_snipeit_maintenance_calendar_to_owner.py")

OWNER = "9f1c1f0e-0000-4000-8000-abcdefabcdef"
OTHER_OWNER = "1b2c3d4e-0000-4000-8000-fedcbafedcba"
SHARED = migration.SHARED_CALENDAR_ID

_PREVIOUS_REVISION = "0137"
_REVISION = "0138"


async def _rows(url: str, sql: str) -> list[tuple[Any, ...]]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return [tuple(row) for row in (await conn.execute(text(sql))).fetchall()]
    finally:
        await engine.dispose()


async def _shared_calendar(url: str, owner: str) -> None:
    await execute(
        url,
        """
        INSERT INTO calendars (id, user_id, name, color, integration_source)
        VALUES (CAST(:id AS uuid), :owner, 'Snipeit_Maintenance Calendar',
                '#808080', 'snipeit_maintenance')
        ON CONFLICT (id) DO NOTHING
        """,
        {"id": SHARED, "owner": owner},
    )


async def _import(url: str, owner: str, external_id: str, calendar_id: str) -> int:
    """A journal imported from ``external_id``, linked on ``calendar_id``."""
    journal_id: int = await execute(
        url,
        """
        INSERT INTO journals (title, content, user_id,
            event_date_range_start, event_date_range_end)
        VALUES (:title, '', :owner, '2026-09-11', '2026-09-11')
        RETURNING id
        """,
        {"title": external_id, "owner": owner},
    )
    await execute(
        url,
        """
        INSERT INTO journal_external_event_links
            (journal_id, calendar_id, external_event_id, sync_capability, sync_status)
        VALUES (:journal_id, CAST(:calendar_id AS uuid), :external_id,
                'bidirectional', 'synced')
        """,
        {
            "journal_id": journal_id,
            "calendar_id": calendar_id,
            "external_id": external_id,
        },
    )
    await execute(
        url,
        """
        INSERT INTO journal_calendar_info (journal_id, calendar_id)
        VALUES (:journal_id, CAST(:calendar_id AS uuid))
        """,
        {"journal_id": journal_id, "calendar_id": calendar_id},
    )
    return journal_id


async def _merged_alias(
    url: str, owner: str, journal_id: int, external_id: str
) -> None:
    await execute(
        url,
        """
        INSERT INTO journal_merged_aliases
            (journal_id, user_id, integration_source, external_id, calendar_id)
        VALUES (:journal_id, :owner, 'snipeit_maintenance', :external_id,
                CAST(:calendar_id AS uuid))
        """,
        {
            "journal_id": journal_id,
            "owner": owner,
            "external_id": external_id,
            "calendar_id": SHARED,
        },
    )


async def _event(url: str, owner: str, *, relayed: bool) -> None:
    """A ``journal_event.created`` the worker enqueued on the shared calendar."""
    await execute(
        url,
        """
        INSERT INTO outbox_events
            (event_id, event_type, aggregate_id, event_data,
             occurred_at, created_at, retry_count, relayed_at)
        VALUES (gen_random_uuid()::text, 'journal_event.created', 0, :data,
                now(), now(), 0, CASE WHEN :relayed THEN now() END)
        """,
        {
            "data": json.dumps(
                {
                    "calendar_id": SHARED,
                    "calendar_info_data": {"calendar_id": SHARED},
                    "journal_data": {"user_id": owner},
                    "external_event_id": "snipeit_maint:30",
                }
            ),
            "relayed": relayed,
        },
    )


async def _event_calendars(url: str) -> list[tuple[Any, ...]]:
    """Each event's ``(owner, relayed, calendar_id, calendar_info calendar_id)``."""
    rows = await _rows(
        url,
        "SELECT event_data, relayed_at IS NOT NULL FROM outbox_events "
        "WHERE event_type = 'journal_event.created' ORDER BY id",
    )
    return [
        (
            data["journal_data"]["user_id"],
            relayed,
            data["calendar_id"],
            data["calendar_info_data"]["calendar_id"],
        )
        for data, relayed in ((json.loads(raw), relayed) for raw, relayed in rows)
    ]


@pytest.mark.integration
@pytest.mark.slow
class TestScopeSnipeItMaintenanceCalendarToOwner:
    def test_the_migration_names_calendars_as_the_worker_does(self) -> None:
        assert migration.owner_calendar_id(OWNER) == snipeit_maintenance_calendar_id(
            OWNER
        )

    async def test_each_owners_rows_move_to_their_own_calendar(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _shared_calendar(url, OWNER)
        mine = await _import(url, OWNER, "snipeit_maint:9", SHARED)
        await _import(url, OTHER_OWNER, "snipeit_maint:10", SHARED)
        await _merged_alias(url, OWNER, mine, "snipeit_maint:8")
        await _event(url, OTHER_OWNER, relayed=False)
        await _event(url, OWNER, relayed=True)

        run_alembic(url, "upgrade", _REVISION)

        mine_id = snipeit_maintenance_calendar_id(OWNER)
        theirs_id = snipeit_maintenance_calendar_id(OTHER_OWNER)
        assert sorted(
            await _rows(
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
        assert await _rows(
            url,
            "SELECT j.user_id, CAST(l.calendar_id AS text), CAST(i.calendar_id AS text) "
            "FROM journal_external_event_links l "
            "JOIN journals j ON j.id = l.journal_id "
            "JOIN journal_calendar_info i ON i.journal_id = j.id ORDER BY j.user_id",
        ) == [(OTHER_OWNER, theirs_id, theirs_id), (OWNER, mine_id, mine_id)]
        assert await _rows(
            url, "SELECT CAST(calendar_id AS text) FROM journal_merged_aliases"
        ) == [(mine_id,)]
        # A relayed event is history; only a pending one would still be applied.
        assert await _event_calendars(url) == [
            (OTHER_OWNER, False, theirs_id, theirs_id),
            (OWNER, True, SHARED, SHARED),
        ]

    async def test_downgrade_moves_everything_back(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _shared_calendar(url, OWNER)
        await _import(url, OWNER, "snipeit_maint:9", SHARED)
        run_alembic(url, "upgrade", _REVISION)

        run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert await _rows(url, "SELECT CAST(id AS text), user_id FROM calendars") == [
            (SHARED, OWNER)
        ]
        assert await _rows(
            url,
            "SELECT CAST(calendar_id AS text), external_event_id "
            "FROM journal_external_event_links",
        ) == [(SHARED, "snipeit_maint:9")]

    async def test_downgrade_refuses_a_record_id_two_owners_link(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _shared_calendar(url, OWNER)
        await _import(url, OWNER, "snipeit_maint:9", SHARED)
        run_alembic(url, "upgrade", _REVISION)
        await execute(
            url,
            """
            INSERT INTO calendars (id, user_id, name, color, integration_source)
            VALUES (CAST(:id AS uuid), :owner, 'Snipe-IT Maintenance', '#808080',
                    'snipeit_maintenance')
            """,
            {"id": snipeit_maintenance_calendar_id(OTHER_OWNER), "owner": OTHER_OWNER},
        )
        await _import(
            url,
            OTHER_OWNER,
            "snipeit_maint:9",
            snipeit_maintenance_calendar_id(OTHER_OWNER),
        )

        with pytest.raises(RuntimeError, match="snipeit_maint:9"):
            run_alembic(url, "downgrade", _PREVIOUS_REVISION)

        assert await _rows(
            url, "SELECT count(*) FROM journal_external_event_links"
        ) == [(2,)]
