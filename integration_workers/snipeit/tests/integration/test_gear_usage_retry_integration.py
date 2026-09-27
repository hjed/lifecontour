"""Integration tests for gear usage pushes that fail part-way and are retried.

A usage journal's checkout and check-in are two Snipe-IT writes. When the
second one fails (typically a 429 during a burst of imports), the event is
redelivered, and the retry must finish the pair rather than stop at the
checkout it already recorded: an asset left checked out makes every later
checkout of it fail.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from core_shared.stream_client import StreamEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from snipeit_api_client import SnipeItAPIClient, SnipeItAPIError
from snipeit_rate_limiter import SnipeItRateLimitError
from snipeit_sync_service import (
    IN_FLIGHT_LOCK_SECONDS,
    TERMINAL_ERROR_PREFIX,
    SnipeItSyncService,
    UnsyncedGearUsage,
    fetch_unsynced_gear_usage,
)
from stream_consumer_tasks import SnipeItWorkerStreamConsumer

from .test_checkin_sync_integration import (
    _insert_gear_usage_journal,
    _posts,
    _queue_asset_dates,
    _session_factory,
    _sync_statuses,
    _usage_of_the_same_gear,
)
from .test_gear_usage_pairs_integration import _remove_gear_item, _trip

# Stored instants of a trip that is 8-9 March 2025 in Sydney (AEDT).
_PAST_START = "2025-03-07T13:00:00+00:00"
_PAST_END = "2025-03-08T13:00:00+00:00"
_CHECKIN_POST = "/api/v1/hardware/42/checkin"


def _sync_service_factory(mock_transport: Any) -> Any:
    """Build a fresh sync service per event, as the worker does.

    The handler closes the service's client when it is done, so each event
    needs its own client over the shared in-memory transport.
    """

    def create(**_: Any) -> SnipeItSyncService:
        client = SnipeItAPIClient(
            client=httpx.AsyncClient(
                transport=mock_transport,
                base_url="https://snipeit.example.com/api/v1/",
            )
        )
        return SnipeItSyncService(
            api_client=client, user_id="user-123", snipeit_user_id="5"
        )

    return create


async def _configure_snipeit(async_connection: AsyncConnection) -> None:
    await async_connection.execute(
        text("""
            INSERT INTO snipeit_settings
                (user_id, base_url, snipeit_user_id, webhook_token,
                 created_at, updated_at)
            VALUES ('user-123', 'https://snipeit.example.com', 5, 'token-1571',
                    now(), now())
        """)
    )


def _journal_created(journal_id: int) -> StreamEvent:
    return StreamEvent(
        message_id="1571-0",
        event_id="journal-created-1571",
        event_type="JournalCreated",
        aggregate_id=journal_id,
        event_data={"journal_id": journal_id, "user_id": "user-123"},
        occurred_at="2026-09-22T23:00:00Z",
    )


class TestRedeliveredGearUsageCreate:
    @pytest.mark.asyncio
    async def test_a_redelivered_create_finishes_a_check_in_that_was_rate_limited(
        self,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _insert_gear_usage_journal(
            async_connection,
            start=_PAST_START,
            end=_PAST_END,
            user_timezone="Australia/Sydney",
        )
        await _configure_snipeit(async_connection)
        _queue_asset_dates(mock_transport)
        mock_transport.add_response(
            "/hardware/42/checkout",
            json_data={"status": "success", "messages": "Checked out."},
            method="POST",
        )
        for _ in range(3):
            mock_transport.add_response(
                "/hardware/42/checkin",
                status_code=429,
                headers={"Retry-After": "0"},
                method="POST",
            )
        consumer = SnipeItWorkerStreamConsumer(
            stream_client=AsyncMock(),
            session_factory=lambda: _session_factory(async_connection),
        )

        with (
            patch("worker._get_auth_data", return_value={"mock": "auth"}),
            patch(
                "worker._create_sync_service",
                side_effect=_sync_service_factory(mock_transport),
            ),
        ):
            with pytest.raises(SnipeItRateLimitError):
                await consumer._handle_event(_journal_created(journal_id))
            assert await _sync_statuses(async_connection, journal_id) == {
                "snipeit_checkout": "success",
                "snipeit_checkin": "failed",
            }

            # Snipe-IT has calmed down by the time the event is redelivered.
            mock_transport.responses = [
                queued
                for queued in mock_transport.responses
                if "/checkin" not in queued[0]
            ]
            mock_transport.add_response(
                "/hardware/42/checkin",
                json_data={"status": "success", "messages": "Checked in."},
                method="POST",
            )
            mock_transport.requests.clear()
            await consumer._handle_event(_journal_created(journal_id))

        assert _posts(mock_transport) == [_CHECKIN_POST]
        assert await _sync_statuses(async_connection, journal_id) == {
            "snipeit_checkout": "success",
            "snipeit_checkin": "success",
        }


async def _checkout_error(async_connection: AsyncConnection, journal_id: int) -> str:
    result = await async_connection.execute(
        text("""
            SELECT error_message FROM sync_metadata
            WHERE integration_source = 'snipeit_checkout'
              AND internal_uuid = :journal_id
              AND sync_status = 'failed'
        """),
        {"journal_id": str(journal_id)},
    )
    return str(result.scalar_one())


class TestTerminalCheckoutFailures:
    """A checkout that cannot succeed by retrying is marked so the sweep skips it.

    The row stays ``failed``: an edit to the journal still retries it.
    """

    @pytest.mark.asyncio
    async def test_a_check_in_before_its_checkout_is_terminal(
        self,
        snipeit_sync_service: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _insert_gear_usage_journal(
            async_connection, start=_PAST_START, end=_PAST_END
        )
        await async_connection.execute(
            text("""
                UPDATE journal_gear_usage_items
                SET checkout_date = :end, checkin_date = :start
                WHERE journal_id = :id
            """),
            {
                "id": journal_id,
                "start": datetime.fromisoformat(_PAST_START),
                "end": datetime.fromisoformat(_PAST_END),
            },
        )

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert (await _checkout_error(async_connection, journal_id)).startswith(
            TERMINAL_ERROR_PREFIX
        )

    @pytest.mark.asyncio
    async def test_an_asset_snipeit_does_not_have_is_terminal(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _insert_gear_usage_journal(
            async_connection, start=_PAST_START, end=_PAST_END
        )
        mock_transport.add_response("/hardware/42", status_code=404, method="GET")

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert await _checkout_error(async_connection, journal_id) == (
            f"{TERMINAL_ERROR_PREFIX} API 404"
        )

    @pytest.mark.asyncio
    async def test_a_server_error_is_left_for_a_retry(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _insert_gear_usage_journal(
            async_connection, start=_PAST_START, end=_PAST_END
        )
        mock_transport.add_response("/hardware/42", status_code=503, method="GET")

        with pytest.raises(SnipeItAPIError):
            await snipeit_sync_service.reconcile_gear_usage(
                journal_id=journal_id,
                session_factory=lambda: _session_factory(async_connection),
            )

        assert not (await _checkout_error(async_connection, journal_id)).startswith(
            TERMINAL_ERROR_PREFIX
        )


async def _checkout_row(
    async_connection: AsyncConnection,
    *,
    asset_id: str,
    journal_id: int,
    sync_status: str,
    error_message: str | None = None,
    age_seconds: int = 0,
) -> None:
    """Record a pair's checkout row as a push attempt left it."""
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata
                (integration_source, external_id, internal_uuid,
                 last_synced_at, version_hash, sync_status,
                 error_message, retry_count, created_at, updated_at)
            VALUES
                ('snipeit_checkout', :external_id, :journal_id,
                 now(), 'hash', :sync_status, :error_message, 0,
                 now() - make_interval(secs => :age), now() - make_interval(secs => :age))
        """),
        {
            "external_id": f"snipeit_checkout:{asset_id}:{journal_id}",
            "journal_id": str(journal_id),
            "sync_status": sync_status,
            "error_message": error_message,
            "age": age_seconds,
        },
    )


async def _checked_in(
    async_connection: AsyncConnection, *, asset_id: str, journal_id: int
) -> None:
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata
                (integration_source, external_id, internal_uuid,
                 last_synced_at, version_hash, sync_status,
                 error_message, retry_count, created_at, updated_at)
            VALUES
                ('snipeit_checkin', :external_id, :journal_id,
                 now(), 'CHECKED_IN', 'success', NULL, 0, now(), now())
        """),
        {
            "external_id": f"snipeit_checkin:{asset_id}:{journal_id}",
            "journal_id": str(journal_id),
        },
    )


async def _usage(
    async_connection: AsyncConnection,
    asset_id: str,
    *,
    start: str = _PAST_START,
    end: str = _PAST_END,
) -> int:
    return await _insert_gear_usage_journal(
        async_connection, start=start, end=end, asset_id=asset_id
    )


class TestFetchUnsyncedGearUsage:
    """The sweep's selection: every pair a push left unfinished, and nothing else."""

    @staticmethod
    async def _fetch(async_connection: AsyncConnection) -> list[UnsyncedGearUsage]:
        return await fetch_unsynced_gear_usage(
            lambda: _session_factory(async_connection), "user-123"
        )

    @pytest.mark.asyncio
    async def test_selects_failed_abandoned_superseded_and_overdue_pairs(
        self, async_connection: AsyncConnection
    ) -> None:
        failed = await _usage(async_connection, "41")
        await _checkout_row(
            async_connection,
            asset_id="41",
            journal_id=failed,
            sync_status="failed",
            error_message="Snipe-IT API rate limited (429).",
        )
        abandoned = await _usage(async_connection, "42")
        await _checkout_row(
            async_connection,
            asset_id="42",
            journal_id=abandoned,
            sync_status="pending",
            age_seconds=IN_FLIGHT_LOCK_SECONDS + 1,
        )
        superseded = await _usage(async_connection, "43")
        await _checkout_row(
            async_connection,
            asset_id="43",
            journal_id=superseded,
            sync_status="failed",
            error_message="Superseded: checkout date changed",
        )
        overdue = await _usage(async_connection, "44")
        await _checkout_row(
            async_connection, asset_id="44", journal_id=overdue, sync_status="success"
        )

        assert [
            (u.journal_id, u.asset_id) for u in await self._fetch(async_connection)
        ] == [(failed, 41), (abandoned, 42), (superseded, 43), (overdue, 44)]

    @pytest.mark.asyncio
    async def test_leaves_out_what_a_sweep_cannot_or_need_not_fix(
        self, async_connection: AsyncConnection
    ) -> None:
        in_flight = await _usage(async_connection, "41")
        await _checkout_row(
            async_connection, asset_id="41", journal_id=in_flight, sync_status="pending"
        )
        terminal = await _usage(async_connection, "42")
        await _checkout_row(
            async_connection,
            asset_id="42",
            journal_id=terminal,
            sync_status="failed",
            error_message=f"{TERMINAL_ERROR_PREFIX} API 404",
        )
        synced = await _usage(async_connection, "43")
        await _checkout_row(
            async_connection, asset_id="43", journal_id=synced, sync_status="success"
        )
        await _checked_in(async_connection, asset_id="43", journal_id=synced)
        still_in_use = await _usage(
            async_connection,
            "44",
            start="2099-06-01T00:00:00+00:00",
            end="2099-06-02T00:00:00+00:00",
        )
        await _checkout_row(
            async_connection,
            asset_id="44",
            journal_id=still_in_use,
            sync_status="success",
        )
        never_attempted = await _usage(async_connection, "45")
        others = await _usage(async_connection, "46")
        await async_connection.execute(
            text("UPDATE journals SET user_id = 'someone-else' WHERE id = :id"),
            {"id": others},
        )
        await _checkout_row(
            async_connection, asset_id="46", journal_id=others, sync_status="failed"
        )

        assert never_attempted
        assert await self._fetch(async_connection) == []

    @pytest.mark.asyncio
    async def test_selects_a_pair_whose_item_the_journal_no_longer_lists(
        self, async_connection: AsyncConnection
    ) -> None:
        """A failed attempt may still have checked the asset out; only a
        reconcile of the pair returns it."""
        journal_id = await _usage(async_connection, "41")
        await _checkout_row(
            async_connection, asset_id="41", journal_id=journal_id, sync_status="failed"
        )
        await async_connection.execute(
            text("DELETE FROM journal_gear_usage_items WHERE journal_id = :id"),
            {"id": journal_id},
        )

        assert [
            (u.journal_id, u.asset_id) for u in await self._fetch(async_connection)
        ] == [(journal_id, 41)]

    @pytest.mark.asyncio
    async def test_orders_each_assets_pairs_oldest_first(
        self, async_connection: AsyncConnection
    ) -> None:
        """An asset's earlier usage must be returned before its later one is taken."""
        later = await _usage(
            async_connection,
            "42",
            start="2025-03-10T13:00:00+00:00",
            end="2025-03-11T13:00:00+00:00",
        )
        other_asset = await _usage(async_connection, "41")
        earlier = await _usage_of_the_same_gear(
            async_connection, later, start=_PAST_START, end=_PAST_END
        )
        for asset_id, journal_id in (
            ("42", later),
            ("41", other_asset),
            ("42", earlier),
        ):
            await _checkout_row(
                async_connection,
                asset_id=asset_id,
                journal_id=journal_id,
                sync_status="failed",
            )

        assert [
            (u.asset_id, u.journal_id) for u in await self._fetch(async_connection)
        ] == [(41, other_asset), (42, earlier), (42, later)]


class TestSweepRecoversLostPushes:
    @pytest.mark.asyncio
    async def test_a_lost_check_in_and_the_checkout_it_blocked_are_both_recorded(
        self,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """The ticket's cascade: J1's check-in was lost, so J2's checkout of the
        same asset failed. One sweep returns the asset for J1, then records J2."""
        from worker import periodic_checkin_all_snipeit_accounts

        first = await _usage(async_connection, "42")
        second = await _usage_of_the_same_gear(
            async_connection,
            first,
            start="2025-03-10T13:00:00+00:00",
            end="2025-03-11T13:00:00+00:00",
        )
        await _configure_snipeit(async_connection)
        await _checkout_row(
            async_connection, asset_id="42", journal_id=first, sync_status="success"
        )
        await _checkout_row(
            async_connection,
            asset_id="42",
            journal_id=second,
            sync_status="failed",
            error_message="Snipe-IT POST /hardware/42/checkout failed: not available",
        )
        for _ in range(2):
            _queue_asset_dates(mock_transport)
            mock_transport.add_response(
                "/hardware/42/checkin",
                json_data={"status": "success", "messages": "Checked in."},
                method="POST",
            )
        mock_transport.add_response(
            "/hardware/42/checkout",
            json_data={"status": "success", "messages": "Checked out."},
            method="POST",
        )

        with (
            patch("worker._get_auth_data", return_value={"mock": "auth"}),
            patch(
                "worker._create_sync_service",
                side_effect=_sync_service_factory(mock_transport),
            ),
        ):
            result = await periodic_checkin_all_snipeit_accounts(
                {"session_factory": lambda: _session_factory(async_connection)}
            )

        assert result == {"accounts_found": 1, "reconciled": 2}
        assert _posts(mock_transport) == [
            "/api/v1/hardware/42/checkin",
            "/api/v1/hardware/42/checkout",
            "/api/v1/hardware/42/checkin",
        ]
        for journal_id in (first, second):
            assert await _sync_statuses(async_connection, journal_id) == {
                "snipeit_checkout": "success",
                "snipeit_checkin": "success",
            }


class TestReconcilingOneRemovedPair:
    @pytest.mark.asyncio
    async def test_releases_that_pair_and_leaves_the_journals_other_items_alone(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """The sweep reconciles pair by pair, so releasing a removed item must
        not push the journal's other items as well."""
        journal_id, gear = await _trip(async_connection, past=True, assets=("41", "42"))
        await _remove_gear_item(async_connection, journal_id, gear["41"])
        await _checkout_row(
            async_connection, asset_id="41", journal_id=journal_id, sync_status="failed"
        )
        # The failed attempt never reached Snipe-IT: the asset is not out.
        mock_transport.add_response(
            "/hardware/41",
            json_data={"id": 41, "asset_tag": "T-41", "assigned_to": None},
            method="GET",
        )

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
            asset_id=41,
        )

        assert [r.url.path for r in mock_transport.requests] == ["/api/v1/hardware/41"]
        remaining = await async_connection.execute(
            text("""
                SELECT external_id FROM sync_metadata
                WHERE internal_uuid = :journal_id
                  AND integration_source IN ('snipeit_checkout', 'snipeit_checkin')
            """),
            {"journal_id": str(journal_id)},
        )
        assert remaining.fetchall() == []
