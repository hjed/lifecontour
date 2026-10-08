"""Integration tests: the Snipe-IT worker reads and changes only its user's links.

Snipe-IT ids are per instance, so two users' instances hand out the same asset
and maintenance ids, and a pair key names a journal id any user's row could
carry. Every statement keyed by an external id, and every update or delete, is
therefore keyed by the syncing user. Each test seeds another user's row for the
key the owner's operation uses and proves the operation neither sees nor
changes it.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from snipeit_sync_service import (
    GearUsagePair,
    _delete_maintenance_claim,
    _fetch_maintenance_claim,
)
from snipeit_sync_window import ListedRecord

from .test_checkin_sync_integration import _session_factory

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
