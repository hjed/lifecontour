"""Integration tests for a journal that records several gear items.

A GEAR_USAGE journal lists many gear items; Snipe-IT gets one checkout and
check-in per (journal, asset) pair. These pin down that each item is synced on
its own, that an item added or removed later touches only its own pair, and
that syncing again writes nothing to Snipe-IT.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from snipeit_sync_service import (
    GearUsagePair,
    UnsyncedGearUsage,
    fetch_unsynced_gear_usage,
)

from .test_checkin_sync_integration import (
    _activity_row,
    _insert_gear_usage_journal,
    _posts,
    _queue_activity,
    _queue_checkout_and_checkin,
    _session_factory,
)

# Stored instants of a trip that is 8-9 March 2025 in Sydney (AEDT).
_PAST_START = "2025-03-07T13:00:00+00:00"
_PAST_END = "2025-03-08T13:00:00+00:00"
_FUTURE_START = "2099-06-01T00:00:00+00:00"
_FUTURE_END = "2099-06-02T00:00:00+00:00"


async def _add_gear_item(
    async_connection: AsyncConnection, journal_id: int, asset_id: str
) -> str:
    """List another Snipe-IT-synced gear item on ``journal_id``; return its id."""
    gear_item_id = str(
        (
            await async_connection.execute(
                text("""
                    INSERT INTO gear_items (name, user_id)
                    VALUES (:name, 'user-123')
                    RETURNING id
                """),
                {"name": f"Asset {asset_id}"},
            )
        ).scalar()
    )
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata
                (user_id, integration_source, external_id, internal_uuid,
                 last_synced_at, version_hash, sync_status,
                 error_message, retry_count, created_at, updated_at)
            VALUES
                ('user-123', 'snipeit', :asset_id, :gear_item_id,
                 now(), 'hash', 'success', NULL, 0, now(), now())
        """),
        {"asset_id": asset_id, "gear_item_id": gear_item_id},
    )
    await _list_gear_item(async_connection, journal_id, gear_item_id)
    return gear_item_id


async def _list_gear_item(
    async_connection: AsyncConnection, journal_id: int, gear_item_id: str
) -> None:
    await async_connection.execute(
        text("""
            INSERT INTO journal_gear_usage_data (journal_id)
            VALUES (:journal_id)
            ON CONFLICT (journal_id) DO NOTHING
        """),
        {"journal_id": journal_id},
    )
    await async_connection.execute(
        text("""
            INSERT INTO journal_gear_usage_items (journal_id, gear_item_id, position)
            SELECT :journal_id, :gear_item_id, count(*)
            FROM journal_gear_usage_items WHERE journal_id = :journal_id
        """),
        {"journal_id": journal_id, "gear_item_id": gear_item_id},
    )


async def _remove_gear_item(
    async_connection: AsyncConnection, journal_id: int, gear_item_id: str
) -> None:
    await async_connection.execute(
        text("""
            DELETE FROM journal_gear_usage_items
            WHERE journal_id = :journal_id AND gear_item_id = :gear_item_id
        """),
        {"journal_id": journal_id, "gear_item_id": gear_item_id},
    )


async def _trip(
    async_connection: AsyncConnection, *, past: bool, assets: tuple[str, ...]
) -> tuple[int, dict[str, str]]:
    """A GEAR_USAGE journal listing one gear item per asset; returns its gear ids."""
    journal_id = await _insert_gear_usage_journal(
        async_connection,
        start=_PAST_START if past else _FUTURE_START,
        end=_PAST_END if past else _FUTURE_END,
        asset_id=assets[0],
        user_timezone="Australia/Sydney",
    )
    first_gear = (
        await async_connection.execute(
            text(
                "SELECT gear_item_id FROM journal_gear_usage_items "
                "WHERE journal_id = :journal_id"
            ),
            {"journal_id": journal_id},
        )
    ).scalar()
    gear = {assets[0]: str(first_gear)}
    for asset_id in assets[1:]:
        gear[asset_id] = await _add_gear_item(async_connection, journal_id, asset_id)
    return journal_id, gear


def _queue_checkout(mock_transport: Any, asset_id: str) -> None:
    """Queue the asset read and checkout POST of one pair (no check-in)."""
    mock_transport.add_response(
        f"/hardware/{asset_id}",
        json_data={"id": int(asset_id), "asset_tag": f"T-{asset_id}"},
        method="GET",
    )
    mock_transport.add_response(
        f"/hardware/{asset_id}/checkout",
        json_data={"status": "success", "messages": "Checked out."},
        method="POST",
    )


async def _pairs(async_connection: AsyncConnection, journal_id: int) -> set[str]:
    """The external ids of every successful checkout/check-in row of a journal."""
    result = await async_connection.execute(
        text("""
            SELECT external_id FROM sync_metadata
            WHERE internal_uuid = :journal_id
              AND integration_source IN ('snipeit_checkout', 'snipeit_checkin')
              AND sync_status = 'success'
        """),
        {"journal_id": str(journal_id)},
    )
    return {row.external_id for row in result.fetchall()}


class TestSeveralGearItems:
    """Each gear item on a journal is its own Snipe-IT checkout."""

    @pytest.mark.asyncio
    async def test_each_item_is_checked_out_and_a_resync_writes_nothing(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id, _ = await _trip(
            async_connection, past=False, assets=("41", "42", "43")
        )
        for asset_id in ("41", "42", "43"):
            _queue_checkout(mock_transport, asset_id)
        factory = lambda: _session_factory(async_connection)  # noqa: E731

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id, session_factory=factory
        )

        assert _posts(mock_transport) == [
            "/api/v1/hardware/41/checkout",
            "/api/v1/hardware/42/checkout",
            "/api/v1/hardware/43/checkout",
        ]
        assert await _pairs(async_connection, journal_id) == {
            f"snipeit_checkout:{asset}:{journal_id}" for asset in ("41", "42", "43")
        }

        # The same event again, and an update event, change nothing.
        mock_transport.requests.clear()
        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id, session_factory=factory
        )
        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id, session_factory=factory
        )
        assert mock_transport.requests == []

    @pytest.mark.asyncio
    async def test_a_past_trip_checks_each_item_out_and_back_in(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id, _ = await _trip(async_connection, past=True, assets=("41", "42"))
        _queue_checkout_and_checkin(mock_transport, "41")
        _queue_checkout_and_checkin(mock_transport, "42")
        factory = lambda: _session_factory(async_connection)  # noqa: E731

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id, session_factory=factory
        )

        assert _posts(mock_transport) == [
            "/api/v1/hardware/41/checkout",
            "/api/v1/hardware/41/checkin",
            "/api/v1/hardware/42/checkout",
            "/api/v1/hardware/42/checkin",
        ]

        # Re-syncing, and the periodic sweep, find nothing left to do.
        mock_transport.requests.clear()
        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id, session_factory=factory
        )
        assert await fetch_unsynced_gear_usage(factory, "user-123") == []
        assert mock_transport.requests == []

    @pytest.mark.asyncio
    async def test_an_item_added_later_is_the_only_one_posted(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id, _ = await _trip(async_connection, past=False, assets=("41", "42"))
        _queue_checkout(mock_transport, "41")
        _queue_checkout(mock_transport, "42")
        factory = lambda: _session_factory(async_connection)  # noqa: E731
        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id, session_factory=factory
        )
        mock_transport.requests.clear()

        await _add_gear_item(async_connection, journal_id, "43")
        _queue_checkout(mock_transport, "43")
        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id, session_factory=factory
        )

        assert _posts(mock_transport) == ["/api/v1/hardware/43/checkout"]

    @pytest.mark.asyncio
    async def test_an_item_removed_while_out_is_returned_and_can_come_back(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id, gear = await _trip(
            async_connection, past=False, assets=("41", "42")
        )
        _queue_checkout(mock_transport, "41")
        _queue_checkout(mock_transport, "42")
        factory = lambda: _session_factory(async_connection)  # noqa: E731
        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id, session_factory=factory
        )
        mock_transport.requests.clear()

        await _remove_gear_item(async_connection, journal_id, gear["42"])
        mock_transport.add_response(
            "/hardware/42/checkin",
            json_data={"status": "success", "messages": "Checked in."},
            method="POST",
        )
        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id, session_factory=factory
        )

        assert _posts(mock_transport) == ["/api/v1/hardware/42/checkin"]
        # The removed pair is forgotten; the other item is untouched.
        assert await _pairs(async_connection, journal_id) == {
            f"snipeit_checkout:41:{journal_id}"
        }

        # Listing it again checks it out afresh.
        mock_transport.requests.clear()
        await _list_gear_item(async_connection, journal_id, gear["42"])
        _queue_checkout(mock_transport, "42")
        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id, session_factory=factory
        )
        assert _posts(mock_transport) == ["/api/v1/hardware/42/checkout"]

    @pytest.mark.asyncio
    async def test_a_removed_item_already_returned_stays_as_history(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id, gear = await _trip(async_connection, past=True, assets=("41", "42"))
        _queue_checkout_and_checkin(mock_transport, "41")
        _queue_checkout_and_checkin(mock_transport, "42")
        factory = lambda: _session_factory(async_connection)  # noqa: E731
        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id, session_factory=factory
        )
        recorded = await _pairs(async_connection, journal_id)
        mock_transport.requests.clear()

        await _remove_gear_item(async_connection, journal_id, gear["42"])
        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id, session_factory=factory
        )

        assert mock_transport.requests == []
        assert await _pairs(async_connection, journal_id) == recorded

    @pytest.mark.asyncio
    async def test_dropping_gear_usage_returns_every_item_still_out(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id, _ = await _trip(async_connection, past=False, assets=("41", "42"))
        _queue_checkout(mock_transport, "41")
        _queue_checkout(mock_transport, "42")
        factory = lambda: _session_factory(async_connection)  # noqa: E731
        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id, session_factory=factory
        )
        mock_transport.requests.clear()

        await async_connection.execute(
            text("DELETE FROM journal_gear_usage_data WHERE journal_id = :id"),
            {"id": journal_id},
        )
        for asset_id in ("41", "42"):
            mock_transport.add_response(
                f"/hardware/{asset_id}/checkin",
                json_data={"status": "success", "messages": "Checked in."},
                method="POST",
            )
        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id, session_factory=factory
        )

        assert sorted(_posts(mock_transport)) == [
            "/api/v1/hardware/41/checkin",
            "/api/v1/hardware/42/checkin",
        ]

    @pytest.mark.asyncio
    async def test_the_sweep_returns_each_overdue_item(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id, _ = await _trip(async_connection, past=True, assets=("41", "42"))
        for asset_id in ("41", "42"):
            await async_connection.execute(
                text("""
                    INSERT INTO sync_metadata
                        (user_id, integration_source, external_id, internal_uuid,
                         last_synced_at, version_hash, sync_status,
                         error_message, retry_count, created_at, updated_at)
                    VALUES
                        ('user-123', 'snipeit_checkout', :external_id, :journal_id,
                         now(), 'hash', 'success', NULL, 0, now(), now())
                """),
                {
                    "external_id": GearUsagePair(
                        journal_id, int(asset_id)
                    ).checkout_external_id,
                    "journal_id": str(journal_id),
                },
            )

        overdue = await fetch_unsynced_gear_usage(
            lambda: _session_factory(async_connection), "user-123"
        )

        assert overdue == [
            UnsyncedGearUsage(
                journal_id=journal_id,
                asset_id=asset_id,
                checkout_at=datetime.fromisoformat(_PAST_START),
            )
            for asset_id in (41, 42)
        ]


class TestFoldingAChildIntoItsParent:
    """The logbook import's child journals are folded into their trips by hand."""

    @pytest.mark.asyncio
    async def test_deleting_the_child_then_adding_its_item_writes_nothing(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """The parent links the child's recorded checkout and check-in.

        Deleting the child first releases its claims on those Snipe-IT entries;
        the parent's pair then links them instead of recording the trip twice.
        """
        factory = lambda: _session_factory(async_connection)  # noqa: E731
        child_id, gear = await _trip(async_connection, past=True, assets=("42",))
        _queue_activity(mock_transport, "checkout", _activity_row(100, "2025-03-08"))
        _queue_activity(
            mock_transport,
            "checkin",
            _activity_row(101, "2025-03-09", action_type="checkin from"),
        )
        await snipeit_sync_service.push_checkout_create(
            journal_id=child_id, session_factory=factory
        )
        assert _posts(mock_transport) == []
        parent_id = await _insert_gear_usage_journal(
            async_connection,
            start=_PAST_START,
            end=_PAST_END,
            asset_id="99",
        )
        await async_connection.execute(
            text("DELETE FROM journal_gear_usage_data WHERE journal_id = :id"),
            {"id": parent_id},
        )

        # 1. Delete the child: its pair is complete, so nothing is checked in.
        await async_connection.execute(
            text("DELETE FROM journals WHERE id = :id"), {"id": child_id}
        )
        assert not await snipeit_sync_service.push_checkin_create(
            GearUsagePair(child_id, 42),
            session_factory=factory,
            note="Gear usage journal deleted",
        )
        # 2. Add its gear item to the parent.
        await _list_gear_item(async_connection, parent_id, gear["42"])
        _queue_activity(mock_transport, "checkout", _activity_row(100, "2025-03-08"))
        _queue_activity(
            mock_transport,
            "checkin",
            _activity_row(101, "2025-03-09", action_type="checkin from"),
        )
        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=parent_id, session_factory=factory
        )

        assert _posts(mock_transport) == []
        assert await _pairs(async_connection, parent_id) == {
            f"snipeit_checkout:42:{parent_id}",
            f"snipeit_checkin:42:{parent_id}",
        }
