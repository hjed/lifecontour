"""Integration tests for an asset-date restore that failed after its check-in.

After a posted check-in the worker PATCHes the asset's last checkout and last
check-in back to the usage's own dates. That PATCH cannot be retried by failing
the push (that would post the check-in again), so a transient failure is kept
on the check-in's sync row and retried by the next reconcile of the pair — the
periodic sweep or the next update of the journal.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from snipeit_rate_limiter import SnipeItRateLimitError
from snipeit_sync_service import UnsyncedGearUsage, fetch_unsynced_gear_usage

from .test_checkin_sync_integration import (
    _insert_recorded_sync_row,
    _posts,
    _session_factory,
    _snipeit_datetime_object,
    _sydney_trip,
    _sync_statuses,
)
from .test_gear_usage_retry_integration import (
    _configure_snipeit,
    _sync_service_factory,
)

# The restore a usage of 8-9 March 2025 in Sydney makes on an asset with no
# earlier dates: its own local checkout and check-in times.
_RESTORE = {
    "last_checkout": "2025-03-08 00:00:00",
    "last_checkin": "2025-03-09 00:00:00",
}
# The restore failed at 11:00 on 4 November 2026 in Sydney (AEDT).
_FAILED_AT = "2026-11-04T00:00:00+00:00"
_PATCH_OK = {
    "status": "success",
    "messages": "Updated.",
    "payload": {"id": 42, "asset_tag": "T-42"},
}
_PATCH_REJECTED = {"status": "error", "messages": {"last_checkin": ["Invalid."]}}


def _session(async_connection: AsyncConnection) -> Any:
    return lambda: _session_factory(async_connection)


async def _checkin_reference(
    async_connection: AsyncConnection, journal_id: int
) -> dict[str, Any]:
    result = await async_connection.execute(
        text("""
            SELECT reference_data FROM sync_metadata
            WHERE integration_source = 'snipeit_checkin'
              AND internal_uuid = :journal_id
        """),
        {"journal_id": str(journal_id)},
    )
    row = result.fetchone()
    assert row is not None
    reference: dict[str, Any] = json.loads(row.reference_data)
    return reference


def _patches(mock_transport: Any) -> list[dict[str, Any]]:
    return [
        json.loads(r.content)
        for r in mock_transport.requests
        if r.method == "PATCH" and r.url.path == "/api/v1/hardware/42"
    ]


def _queue_asset_read(
    mock_transport: Any,
    *,
    last_checkout: str | None = None,
    last_checkin: str | None = None,
) -> None:
    mock_transport.add_response(
        "/hardware/42",
        json_data={
            "id": 42,
            "asset_tag": "T-42",
            "last_checkout": _snipeit_datetime_object(last_checkout),
            "last_checkin": _snipeit_datetime_object(last_checkin),
        },
        method="GET",
    )


def _queue_patch(
    mock_transport: Any, *, status_code: int = 200, json_data: object = _PATCH_OK
) -> None:
    mock_transport.add_response(
        "/hardware/42",
        status_code=status_code,
        json_data=json_data,
        headers={"Retry-After": "0"} if status_code == 429 else None,
        method="PATCH",
    )


def _fail_patches_with(
    mock_transport: Any, monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    serve = mock_transport.handle_async_request

    async def failing_patch(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            mock_transport.requests.append(request)
            raise exc
        return await serve(request)

    monkeypatch.setattr(mock_transport, "handle_async_request", failing_patch)


async def _checked_in_with_pending_restore(
    async_connection: AsyncConnection,
    *,
    checkout_at: str = "2025-03-08",
    pending: dict[str, Any] | None = None,
) -> int:
    """A Sydney trip whose pair is checked in, with its restore still pending."""
    journal_id = await _sydney_trip(async_connection)
    await _insert_recorded_sync_row(
        async_connection,
        source="snipeit_checkout",
        journal_id=journal_id,
        reference_data={
            "checkout_at": checkout_at,
            "expected_checkin": "2025-03-09",
            "asset_dates_before": {"last_checkout": None, "last_checkin": None},
        },
    )
    await _insert_recorded_sync_row(
        async_connection,
        source="snipeit_checkin",
        journal_id=journal_id,
        reference_data={
            "checkin_at": "2025-03-09",
            "pending_asset_dates": pending
            or {"payload": _RESTORE, "failed_at": _FAILED_AT},
        },
    )
    return journal_id


class TestSavingAPendingRestore:
    """A check-in whose restore failed transiently keeps that restore to retry."""

    @staticmethod
    def _queue_checkout_and_checkin(mock_transport: Any) -> None:
        _queue_asset_read(mock_transport)
        mock_transport.add_response(
            "/hardware/42/checkout",
            json_data={"status": "success", "messages": "Checked out."},
            method="POST",
        )
        mock_transport.add_response(
            "/hardware/42/checkin",
            json_data={"status": "success", "messages": "Checked in."},
            method="POST",
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status_code", "attempts"),
        [(429, 3), (503, 1)],
        ids=["rate-limited", "server-error"],
    )
    async def test_a_failed_status_keeps_the_restore(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        status_code: int,
        attempts: int,
    ) -> None:
        journal_id = await _sydney_trip(async_connection)
        self._queue_checkout_and_checkin(mock_transport)
        for _ in range(attempts):
            _queue_patch(mock_transport, status_code=status_code, json_data=None)

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id, session_factory=_session(async_connection)
        )

        assert await _sync_statuses(async_connection, journal_id) == {
            "snipeit_checkout": "success",
            "snipeit_checkin": "success",
        }
        pending = (await _checkin_reference(async_connection, journal_id))[
            "pending_asset_dates"
        ]
        assert pending["payload"] == _RESTORE
        assert pending["failed_at"]

    @pytest.mark.asyncio
    async def test_a_connection_error_keeps_the_restore(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        journal_id = await _sydney_trip(async_connection)
        self._queue_checkout_and_checkin(mock_transport)
        _fail_patches_with(mock_transport, monkeypatch, httpx.ConnectError("down"))

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id, session_factory=_session(async_connection)
        )

        reference = await _checkin_reference(async_connection, journal_id)
        assert reference["pending_asset_dates"]["payload"] == _RESTORE

    @pytest.mark.asyncio
    async def test_a_rejected_restore_is_not_kept(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        # Snipe-IT refused the values: sending them again cannot succeed.
        journal_id = await _sydney_trip(async_connection)
        self._queue_checkout_and_checkin(mock_transport)
        _queue_patch(mock_transport, json_data=_PATCH_REJECTED)

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id, session_factory=_session(async_connection)
        )

        reference = await _checkin_reference(async_connection, journal_id)
        assert "pending_asset_dates" not in reference


class TestRetryingAPendingRestore:
    """Reconciling the pair sends the kept restore, never the check-in again."""

    @pytest.mark.asyncio
    async def test_reconcile_sends_the_restore_and_clears_it(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _checked_in_with_pending_restore(async_connection)
        # Snipe-IT stamped the check-in at 10:30, before the restore failed.
        _queue_asset_read(
            mock_transport,
            last_checkout="2025-03-08 00:00:00",
            last_checkin="2026-11-04 10:30:00",
        )
        _queue_patch(mock_transport)

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id, _session(async_connection)
        )

        assert _posts(mock_transport) == []
        assert _patches(mock_transport) == [_RESTORE]
        reference = await _checkin_reference(async_connection, journal_id)
        assert "pending_asset_dates" not in reference
        assert reference["checkin_at"] == "2025-03-09"

    @pytest.mark.asyncio
    async def test_a_date_set_after_the_failure_is_left_alone(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        # The asset was checked in again after the restore failed: that newer
        # check-in is kept, and only the checkout is restored.
        journal_id = await _checked_in_with_pending_restore(async_connection)
        _queue_asset_read(
            mock_transport,
            last_checkout="2025-03-08 00:00:00",
            last_checkin="2026-11-04 12:00:00",
        )
        _queue_patch(mock_transport)

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id, _session(async_connection)
        )

        assert _patches(mock_transport) == [
            {"last_checkout": _RESTORE["last_checkout"]}
        ]
        reference = await _checkin_reference(async_connection, journal_id)
        assert "pending_asset_dates" not in reference

    @pytest.mark.asyncio
    async def test_nothing_is_sent_when_every_date_is_newer(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _checked_in_with_pending_restore(async_connection)
        _queue_asset_read(
            mock_transport,
            last_checkout="2026-11-04 12:00:00",
            last_checkin="2026-11-04 13:00:00",
        )

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id, _session(async_connection)
        )

        assert _patches(mock_transport) == []
        reference = await _checkin_reference(async_connection, journal_id)
        assert "pending_asset_dates" not in reference

    @pytest.mark.asyncio
    async def test_a_server_error_keeps_the_restore_and_holds_the_pair(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        # The checkout date changed, which would supersede the pair and check
        # the asset out again — reading the wrong dates as its baseline.
        journal_id = await _checked_in_with_pending_restore(
            async_connection, checkout_at="2025-03-01"
        )
        _queue_asset_read(mock_transport, last_checkin="2026-11-04 10:30:00")
        _queue_patch(mock_transport, status_code=503, json_data=None)

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id, _session(async_connection)
        )

        assert _posts(mock_transport) == []
        assert await _sync_statuses(async_connection, journal_id) == {
            "snipeit_checkout": "success",
            "snipeit_checkin": "success",
        }
        reference = await _checkin_reference(async_connection, journal_id)
        assert reference["pending_asset_dates"]["payload"] == _RESTORE

    @pytest.mark.asyncio
    async def test_a_rate_limit_keeps_the_restore_and_is_raised(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _checked_in_with_pending_restore(async_connection)
        _queue_asset_read(mock_transport, last_checkin="2026-11-04 10:30:00")
        for _ in range(3):
            _queue_patch(mock_transport, status_code=429, json_data=None)

        with pytest.raises(SnipeItRateLimitError):
            await snipeit_sync_service.reconcile_gear_usage(
                journal_id, _session(async_connection)
            )

        reference = await _checkin_reference(async_connection, journal_id)
        assert reference["pending_asset_dates"]["payload"] == _RESTORE

    @pytest.mark.asyncio
    async def test_a_rejected_retry_drops_the_restore(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _checked_in_with_pending_restore(async_connection)
        _queue_asset_read(mock_transport, last_checkin="2026-11-04 10:30:00")
        _queue_patch(mock_transport, json_data=_PATCH_REJECTED)

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id, _session(async_connection)
        )

        reference = await _checkin_reference(async_connection, journal_id)
        assert "pending_asset_dates" not in reference

    @pytest.mark.asyncio
    async def test_a_removed_gear_item_still_gets_its_restore(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _checked_in_with_pending_restore(async_connection)
        await async_connection.execute(
            text("DELETE FROM journal_gear_usage_items WHERE journal_id = :id"),
            {"id": journal_id},
        )
        _queue_asset_read(mock_transport, last_checkin="2026-11-04 10:30:00")
        _queue_patch(mock_transport)

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id, _session(async_connection)
        )

        assert _posts(mock_transport) == []
        assert _patches(mock_transport) == [_RESTORE]
        reference = await _checkin_reference(async_connection, journal_id)
        assert "pending_asset_dates" not in reference


class TestSweepFinishesPendingRestores:
    @pytest.mark.asyncio
    async def test_selects_a_checked_in_pair_with_a_pending_restore(
        self, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _checked_in_with_pending_restore(async_connection)

        selected: list[UnsyncedGearUsage] = await fetch_unsynced_gear_usage(
            _session(async_connection), "user-123"
        )

        assert [(u.asset_id, u.journal_id) for u in selected] == [(42, journal_id)]

    @pytest.mark.asyncio
    async def test_the_sweep_sends_the_restore_and_stops_selecting_the_pair(
        self, mock_transport: Any, async_connection: AsyncConnection
    ) -> None:
        from unittest.mock import patch

        from worker import periodic_checkin_all_snipeit_accounts

        journal_id = await _checked_in_with_pending_restore(async_connection)
        await _configure_snipeit(async_connection)
        _queue_asset_read(mock_transport, last_checkin="2026-11-04 10:30:00")
        _queue_patch(mock_transport)

        with (
            patch("worker._get_auth_data", return_value={"mock": "auth"}),
            patch(
                "worker._create_sync_service",
                side_effect=_sync_service_factory(mock_transport),
            ),
        ):
            result = await periodic_checkin_all_snipeit_accounts(
                {"session_factory": _session(async_connection)}
            )

        assert result == {"accounts_found": 1, "reconciled": 1}
        assert _posts(mock_transport) == []
        assert _patches(mock_transport) == [_RESTORE]
        assert (
            await fetch_unsynced_gear_usage(_session(async_connection), "user-123")
            == []
        )
        reference = await _checkin_reference(async_connection, journal_id)
        assert "pending_asset_dates" not in reference
