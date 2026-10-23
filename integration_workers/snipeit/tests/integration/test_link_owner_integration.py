"""Integration tests: the Snipe-IT worker reads and changes only its user's links.

Snipe-IT ids are per instance, so two users' instances hand out the same asset
and maintenance ids, and a pair key names a journal id any user's row could
carry. Every statement keyed by an external id, and every update or delete, is
therefore keyed by the syncing user. Each test seeds another user's row for the
key the owner's operation uses and proves the operation neither sees nor
changes it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from snipeit_sync_service import (
    IMPORT_LINK_GRACE_SECONDS,
    GearUsagePair,
    _delete_maintenance_claim,
    _fetch_maintenance_claim,
    snipeit_maintenance_calendar_id,
)
from snipeit_sync_window import ListedRecord

from .test_checkin_sync_integration import _session_factory
from .test_maintenance_sync_integration import (
    _an_import_whose_journal_is_gone,
    _joined_session_factory,
    _listed,
    _push_rows,
    _queue_gone,
    _seed_claim,
    _seed_import_record,
    _seed_maintenance_journal,
    _seed_synced_asset,
    _snipeit_writes,
    _write_response,
)

# ``snipeit_sync_service`` (conftest) syncs for this user.
OWNER = "user-123"
OTHER_USER = "someone-else"
JOURNAL_ID = 4242
PAIR = GearUsagePair(journal_id=JOURNAL_ID, asset_id=42)


async def _seed_row(
    async_connection: AsyncConnection,
    *,
    source: str,
    external_id: str,
    user_id: str = OTHER_USER,
    internal_uuid: str | None = None,
    sync_status: str = "success",
    reference_data: str | None = None,
) -> None:
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata
                (user_id, integration_source, external_id, internal_uuid,
                 last_synced_at, version_hash, sync_status, error_message,
                 retry_count, reference_data, created_at, updated_at)
            VALUES
                (:user_id, :source, :external_id, :internal_uuid,
                 now(), 'theirs', :sync_status, NULL,
                 0, :reference_data, now(), now())
        """),
        {
            "user_id": user_id,
            "source": source,
            "external_id": external_id,
            "internal_uuid": internal_uuid,
            "sync_status": sync_status,
            "reference_data": reference_data,
        },
    )


async def _rows(async_connection: AsyncConnection) -> list[tuple[Any, ...]]:
    """Every link row as ``(user_id, source, external_id, status, error, hash)``."""
    result = await async_connection.execute(
        text("""
            SELECT user_id, integration_source, external_id, sync_status,
                   error_message, version_hash
            FROM sync_metadata
            ORDER BY integration_source, external_id, user_id
        """)
    )
    return [tuple(row) for row in result.fetchall()]


def _factory(async_connection: AsyncConnection) -> Any:
    return lambda: _session_factory(async_connection)


@pytest.mark.asyncio
class TestMaintenanceClaimsAreTheOwners:
    async def test_claim_helpers_ignore_another_users_claim(
        self, async_connection: AsyncConnection
    ) -> None:
        await _seed_row(
            async_connection,
            source="snipeit_maintenance_claim",
            external_id=str(JOURNAL_ID),
            sync_status="pending",
        )
        before = await _rows(async_connection)

        # Committed, as the worker's callers do: a delete left in an
        # uncommitted session would be rolled back and prove nothing.
        async with _session_factory(async_connection) as session:
            async with session.begin():
                claim = await _fetch_maintenance_claim(
                    session, JOURNAL_ID, user_id=OWNER
                )
                await _delete_maintenance_claim(session, JOURNAL_ID, user_id=OWNER)

        assert claim is None
        assert await _rows(async_connection) == before

    async def test_failing_a_claim_leaves_another_users_alone(
        self, snipeit_sync_service: Any, async_connection: AsyncConnection
    ) -> None:
        await _seed_row(
            async_connection,
            source="snipeit_maintenance_claim",
            external_id=str(JOURNAL_ID),
            sync_status="pending",
        )
        before = await _rows(async_connection)

        await snipeit_sync_service._fail_maintenance_claim(
            JOURNAL_ID, _factory(async_connection), "boom"
        )

        assert await _rows(async_connection) == before


@pytest.mark.asyncio
class TestMaintenanceRecordsAreTheOwners:
    async def test_a_record_on_another_users_asset_is_not_unsettled(
        self, snipeit_sync_service: Any, async_connection: AsyncConnection
    ) -> None:
        """Only an asset synced for this user makes a record its to settle."""
        await _seed_row(
            async_connection,
            source="snipeit",
            external_id="42",
            internal_uuid="00000000-0000-0000-0000-000000000042",
        )

        unsettled = await snipeit_sync_service.unsettled_maintenance_ids(
            [ListedRecord(7, None, 42)], _factory(async_connection)
        )

        assert unsettled == set()

    async def test_reconciling_never_considers_another_users_record(
        self, snipeit_sync_service: Any, async_connection: AsyncConnection
    ) -> None:
        """Another user's record missing from this user's listing is not
        looked up in this user's Snipe-IT, nor forgotten."""
        await _seed_row(
            async_connection,
            source="snipeit_maintenance",
            external_id="snipeit_maint:7",
        )
        before = await _rows(async_connection)

        deleted = await snipeit_sync_service.reconcile_deleted_maintenances(
            [], _factory(async_connection)
        )

        assert deleted == 0
        assert await _rows(async_connection) == before

    async def test_forgetting_a_record_leaves_another_users_row(
        self, snipeit_sync_service: Any, async_connection: AsyncConnection
    ) -> None:
        await _seed_row(
            async_connection,
            source="snipeit_maintenance",
            external_id="snipeit_maint:7",
        )
        before = await _rows(async_connection)

        forgotten = await snipeit_sync_service._forget_deleted_maintenance(
            "snipeit_maint:7", _factory(async_connection)
        )

        assert forgotten is False
        assert await _rows(async_connection) == before


@pytest.mark.asyncio
class TestGearUsagePairsAreTheOwners:
    async def _seed_other_users_pair(self, async_connection: AsyncConnection) -> None:
        await _seed_row(
            async_connection,
            source="snipeit_checkout",
            external_id=PAIR.checkout_external_id,
            internal_uuid=str(JOURNAL_ID),
            sync_status="pending",
            reference_data='{"recorded": true}',
        )
        await _seed_row(
            async_connection,
            source="snipeit_checkin",
            external_id=PAIR.checkin_external_id,
            internal_uuid=str(JOURNAL_ID),
            sync_status="pending",
        )

    async def test_unlocking_and_finalising_leave_another_users_pair(
        self, snipeit_sync_service: Any, async_connection: AsyncConnection
    ) -> None:
        await self._seed_other_users_pair(async_connection)
        before = await _rows(async_connection)
        factory = _factory(async_connection)

        await snipeit_sync_service._unlock_pending_checkout(PAIR, factory, "boom")
        await snipeit_sync_service._unlock_pending_checkin(
            JOURNAL_ID, PAIR.checkin_external_id, factory, "boom"
        )
        await snipeit_sync_service._finalize_checkin(
            JOURNAL_ID, PAIR.checkin_external_id, factory
        )

        assert await _rows(async_connection) == before

    async def test_forgetting_and_superseding_leave_another_users_pair(
        self, snipeit_sync_service: Any, async_connection: AsyncConnection
    ) -> None:
        await self._seed_other_users_pair(async_connection)
        await async_connection.execute(
            text(
                "UPDATE sync_metadata SET sync_status = 'success' "
                "WHERE integration_source = 'snipeit_checkout'"
            )
        )
        before = await _rows(async_connection)
        factory = _factory(async_connection)

        superseded = await snipeit_sync_service._supersede_checkout(
            PAIR,
            recorded_reference='{"recorded": true}',
            session_factory=factory,
            reason="moved",
        )
        await snipeit_sync_service._forget_pair(PAIR, factory)

        assert superseded is False
        assert await _rows(async_connection) == before

    async def test_a_checkout_is_never_paired_with_another_users_checkin(
        self, snipeit_sync_service: Any, async_connection: AsyncConnection
    ) -> None:
        await _seed_row(
            async_connection,
            source="snipeit_checkout",
            external_id=PAIR.checkout_external_id,
            user_id=OWNER,
            internal_uuid=str(JOURNAL_ID),
        )
        await _seed_row(
            async_connection,
            source="snipeit_checkin",
            external_id=PAIR.checkin_external_id,
            internal_uuid=str(JOURNAL_ID),
        )

        recorded = await snipeit_sync_service._recorded_checkouts(
            JOURNAL_ID, _factory(async_connection)
        )

        assert recorded[PAIR.asset_id].checkin_status is None


async def _seed_other_users_import(
    async_connection: AsyncConnection, *, maintenance_id: int
) -> int:
    """Another user's journal imported from their own Snipe-IT's record
    ``maintenance_id``, as the backend writes it: on their maintenance calendar,
    with their import row."""
    gear = await async_connection.execute(
        text("""
            INSERT INTO gear_items (name, user_id)
            VALUES ('Their rope', :user_id)
            RETURNING id
        """),
        {"user_id": OTHER_USER},
    )
    gear_item_id = str(gear.scalar_one())
    journal = await async_connection.execute(
        text("""
            INSERT INTO journals (title, content, user_id,
                event_date_range_start, event_date_range_end)
            VALUES ('Their maintenance', '', :user_id, '2026-09-11', '2026-09-11')
            RETURNING id
        """),
        {"user_id": OTHER_USER},
    )
    journal_id = int(journal.scalar_one())
    await async_connection.execute(
        text("""
            INSERT INTO journal_gear_maintenance_data
                (journal_id, gear_item_id, maintenance_type)
            VALUES (:journal_id, :gear_item_id, 'routine maintenance')
        """),
        {"journal_id": journal_id, "gear_item_id": gear_item_id},
    )
    calendar_id = snipeit_maintenance_calendar_id(OTHER_USER)
    await async_connection.execute(
        text("""
            INSERT INTO calendars (id, user_id, name, color, integration_source)
            VALUES (:calendar_id, :user_id, 'Snipe-IT Maintenance', '#808080',
                    'snipeit_maintenance')
            ON CONFLICT (id) DO NOTHING
        """),
        {"calendar_id": calendar_id, "user_id": OTHER_USER},
    )
    await async_connection.execute(
        text("""
            INSERT INTO journal_external_event_links
                (journal_id, calendar_id, external_event_id,
                 sync_capability, sync_status)
            VALUES (:journal_id, :calendar_id, :external_event_id,
                    'bidirectional', 'synced')
        """),
        {
            "journal_id": journal_id,
            "calendar_id": calendar_id,
            "external_event_id": f"snipeit_maint:{maintenance_id}",
        },
    )
    await _seed_row(
        async_connection,
        source="snipeit_maintenance",
        external_id=f"snipeit_maint:{maintenance_id}",
    )
    return journal_id


async def _journal_event_payloads(
    async_connection: AsyncConnection,
) -> list[tuple[str, dict[str, Any]]]:
    result = await async_connection.execute(
        text("""
            SELECT event_type, event_data FROM outbox_events
            WHERE event_type LIKE 'journal_event.%'
            ORDER BY id
        """)
    )
    return [(row.event_type, json.loads(row.event_data)) for row in result.fetchall()]


@pytest.mark.asyncio
class TestMaintenanceImportLinksAreTheOwners:
    """Each user's imports are linked on their own maintenance calendar, so
    another user's journal holding the same record id never stands in for
    this user's record."""

    def test_each_user_has_their_own_maintenance_calendar(self) -> None:
        assert snipeit_maintenance_calendar_id(OWNER) != (
            snipeit_maintenance_calendar_id(OTHER_USER)
        )
        assert snipeit_maintenance_calendar_id(OWNER) == (
            snipeit_maintenance_calendar_id(OWNER)
        )

    async def test_a_record_another_user_imported_is_imported_for_this_user(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """This user's earlier import of record 9 lost its journal; another
        user's journal for their record 9 is not it."""
        await _seed_synced_asset(async_connection, 51)
        await _seed_import_record(
            async_connection,
            maintenance_id=9,
            version_hash="old",
            age_seconds=IMPORT_LINK_GRACE_SECONDS + 60,
        )
        await _seed_other_users_import(async_connection, maintenance_id=9)
        mock_transport.add_response("/maintenances/9", json_data=_listed(9))

        result = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[9],
            session_factory=_joined_session_factory(async_connection),
        )

        assert result == {"synced": 1, "skipped": 0, "failed": 0}
        [(event_type, event_data)] = await _journal_event_payloads(async_connection)
        assert event_type == "journal_event.created"
        assert event_data.get("existing_journal_id") is None
        assert event_data["calendar_id"] == snipeit_maintenance_calendar_id(OWNER)
        assert event_data["journal_data"]["user_id"] == OWNER

    async def test_a_posted_record_another_user_holds_gets_this_journals_row(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        await _seed_other_users_import(async_connection, maintenance_id=9)
        mock_transport.add_response(
            "/maintenances", json_data=_write_response(9), method="POST"
        )

        await snipeit_sync_service.push_maintenance_create(
            journal_id=journal_id,
            session_factory=_joined_session_factory(async_connection),
        )

        assert await _push_rows(async_connection, journal_id) == ["snipeit_maint:9"]
        assert (OTHER_USER, "snipeit_maintenance", "snipeit_maint:9") in [
            row[:3] for row in await _rows(async_connection)
        ]

    async def test_a_claim_links_a_record_another_user_holds(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="Retire Harness"
        )
        await _seed_claim(async_connection, journal_id=journal_id, status="failed")
        await _seed_other_users_import(async_connection, maintenance_id=9)
        mock_transport.add_response("/maintenances/9", json_data=_listed(9))

        result = await snipeit_sync_service.sync_maintenance_batch(
            maintenance_ids=[9],
            session_factory=_joined_session_factory(async_connection),
        )

        assert result == {"synced": 0, "skipped": 1, "failed": 0}
        assert await _journal_event_payloads(async_connection) == []
        assert await _push_rows(async_connection, journal_id) == ["snipeit_maint:9"]

    async def test_another_users_journal_does_not_hold_this_users_record(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Deleting this user's imported journal deletes this user's record 9."""
        await _an_import_whose_journal_is_gone(
            async_connection, maintenance_id=9, age_seconds=0
        )
        await _seed_other_users_import(async_connection, maintenance_id=9)
        mock_transport.add_response(
            "/maintenances/9", json_data={"status": "success"}, method="DELETE"
        )

        deleted = await snipeit_sync_service.delete_maintenance_record(
            external_id="snipeit_maint:9",
            session_factory=_joined_session_factory(async_connection),
        )

        assert deleted is True
        assert _snipeit_writes(mock_transport) == ["DELETE /api/v1/maintenances/9"]
        assert [row[:3] for row in await _rows(async_connection)] == [
            ("user-123", "snipeit", "51"),
            (OTHER_USER, "snipeit_maintenance", "snipeit_maint:9"),
        ]

    async def test_another_users_journal_does_not_unsettle_this_users_import(
        self, snipeit_sync_service: Any, async_connection: AsyncConnection
    ) -> None:
        """Their journal is on their own gear, which is not this record's."""
        gear_item_id = await _seed_synced_asset(async_connection, 51)
        await _seed_maintenance_journal(
            async_connection, gear_item_id=gear_item_id, title="x", imported_from=9
        )
        await _seed_import_record(async_connection, maintenance_id=9, version_hash="h")
        await _seed_other_users_import(async_connection, maintenance_id=9)

        unsettled = await snipeit_sync_service.unsettled_maintenance_ids(
            [ListedRecord(9, None, 51)], _joined_session_factory(async_connection)
        )

        assert unsettled == set()

    async def test_another_users_journal_does_not_settle_this_users_import(
        self, snipeit_sync_service: Any, async_connection: AsyncConnection
    ) -> None:
        await _an_import_whose_journal_is_gone(
            async_connection, maintenance_id=9, age_seconds=0
        )
        await _seed_other_users_import(async_connection, maintenance_id=9)

        unsettled = await snipeit_sync_service.unsettled_maintenance_ids(
            [ListedRecord(9, None, 51)], _joined_session_factory(async_connection)
        )

        assert unsettled == {9}

    async def test_another_users_journal_does_not_keep_a_deleted_record(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Record 9 is gone from this user's Snipe-IT, so this user's row for it
        is forgotten; the other user's row and journal are left alone."""
        await _an_import_whose_journal_is_gone(
            async_connection, maintenance_id=9, age_seconds=0
        )
        await _seed_other_users_import(async_connection, maintenance_id=9)
        _queue_gone(mock_transport, 9)

        deleted = await snipeit_sync_service.reconcile_deleted_maintenances(
            set(), _joined_session_factory(async_connection)
        )

        assert deleted == 1
        assert [row[:3] for row in await _rows(async_connection)] == [
            ("user-123", "snipeit", "51"),
            (OTHER_USER, "snipeit_maintenance", "snipeit_maint:9"),
        ]
