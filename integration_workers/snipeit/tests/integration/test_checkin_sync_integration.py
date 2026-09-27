"""
Integration tests for Snipe-IT check-in sync.

Verifies that a GEAR_USAGE checkout is returned (checked in) via a POST to the
Snipe-IT API with correct ``snipeit_checkin`` sync_metadata, including the
post-deletion path (asset resolved from checkout metadata), the immediate
check-in on create for a past usage window, idempotency, and the periodic
sweep's overdue-selection query.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from snipeit_sync_service import GearUsagePair

# ``MockTransport``, ``mock_transport``, ``integration_client`` and
# ``snipeit_sync_service`` are shared fixtures defined in ``conftest.py``.


async def _insert_checkout_metadata(
    async_connection: AsyncConnection,
    *,
    asset_id: str,
    journal_id: int,
    sync_status: str = "success",
) -> None:
    """Insert a ``snipeit_checkout`` sync_metadata row (successful by default)."""
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata
                (integration_source, external_id, internal_uuid,
                 last_synced_at, version_hash, sync_status,
                 error_message, retry_count, created_at, updated_at)
            VALUES
                ('snipeit_checkout', :external_id, :journal_id,
                 now(), 'hash', :sync_status, NULL, 0, now(), now())
        """),
        {
            "external_id": f"snipeit_checkout:{asset_id}:{journal_id}",
            "journal_id": str(journal_id),
            "sync_status": sync_status,
        },
    )


@asynccontextmanager
async def _session_factory(async_connection: AsyncConnection) -> Any:
    async with AsyncSession(
        async_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as session:
        yield session


def _returned_id(result: Any) -> Any:
    """Return the ``id`` of an ``INSERT ... RETURNING id`` result, asserting present."""
    row = result.fetchone()
    assert row is not None
    return row.id


async def _insert_gear_usage_journal(
    async_connection: AsyncConnection,
    *,
    start: str,
    end: str,
    asset_id: str = "42",
    user_timezone: str | None = None,
    event_timezone: str | None = None,
) -> int:
    """Insert a GEAR_USAGE journal on a Snipe-IT-synced gear item.

    ``start``/``end`` are the stored instants (the UTC instant of a local
    midnight, as the app writes them). A user timezone is stored in
    ``user_settings`` and an event timezone on ``journal_calendar_info``.
    """
    gear_item_id = str(
        _returned_id(
            await async_connection.execute(
                text("""
                    INSERT INTO gear_items (name, user_id)
                    VALUES ('Tent', 'user-123')
                    RETURNING id
                """)
            )
        )
    )
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata
                (integration_source, external_id, internal_uuid,
                 last_synced_at, version_hash, sync_status,
                 error_message, retry_count, created_at, updated_at)
            VALUES
                ('snipeit', :asset_id, :gear_item_id,
                 now(), 'hash', 'success', NULL, 0, now(), now())
        """),
        {"asset_id": asset_id, "gear_item_id": gear_item_id},
    )
    journal_id: int = _returned_id(
        await async_connection.execute(
            text("""
                INSERT INTO journals (title, content, user_id,
                    event_date_range_start, event_date_range_end)
                VALUES ('Past trip', '', 'user-123', :start, :end)
                RETURNING id
            """),
            {
                "start": datetime.fromisoformat(start),
                "end": datetime.fromisoformat(end),
            },
        )
    )
    await async_connection.execute(
        text("""
            WITH entry AS (
                INSERT INTO journal_gear_usage_data (journal_id)
                VALUES (:journal_id)
                RETURNING journal_id
            )
            INSERT INTO journal_gear_usage_items
                (journal_id, gear_item_id, checkout_date, checkin_date)
            SELECT journal_id, CAST(:gear_item_id AS uuid), NULL, NULL FROM entry
        """),
        {"journal_id": journal_id, "gear_item_id": gear_item_id},
    )
    if user_timezone:
        await async_connection.execute(
            text("""
                INSERT INTO user_settings (user_id, timezone)
                VALUES ('user-123', :timezone)
            """),
            {"timezone": user_timezone},
        )
    if event_timezone:
        calendar_id = uuid4()
        await async_connection.execute(
            text("""
                INSERT INTO calendars (id, user_id, name, color, is_synced_to_google)
                VALUES (:id, 'user-123', 'Trips', '#FF0000', false)
            """),
            {"id": calendar_id},
        )
        await async_connection.execute(
            text("""
                INSERT INTO journal_calendar_info
                    (journal_id, calendar_id, is_all_day, timezone)
                VALUES (:journal_id, :calendar_id, true, :timezone)
            """),
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "timezone": event_timezone,
            },
        )
    return journal_id


def _request_body(
    mock_transport: Any, path: str, method: str | None = None
) -> dict[str, Any]:
    """Return the JSON body of the single request whose URL contains ``path``."""
    (request,) = [
        r
        for r in mock_transport.requests
        if path in str(r.url) and method in (None, r.method)
    ]
    body: dict[str, Any] = json.loads(request.content)
    return body


async def _reference_data(
    async_connection: AsyncConnection, *, source: str, journal_id: int
) -> Any:
    """Return the decoded ``reference_data`` of a journal's sync row for ``source``."""
    result = await async_connection.execute(
        text("""
            SELECT reference_data FROM sync_metadata
            WHERE integration_source = :source AND internal_uuid = :journal_id
        """),
        {"source": source, "journal_id": str(journal_id)},
    )
    row = result.fetchone()
    assert row is not None, source
    return json.loads(row.reference_data)


def _snipeit_datetime_object(value: str | None) -> dict[str, str] | None:
    """Return a Snipe-IT GET ``datetime`` object for ``value`` (``None`` stays)."""
    return {"datetime": value, "formatted": value} if value else None


def _queue_asset_dates(
    mock_transport: Any,
    asset_id: str = "42",
    *,
    last_checkout: str | None = None,
    last_checkin: str | None = None,
) -> None:
    """Queue the asset read before a checkout and the PATCH restoring its dates."""
    mock_transport.add_response(
        f"/hardware/{asset_id}",
        json_data={
            "id": int(asset_id),
            "asset_tag": f"T-{asset_id}",
            "last_checkout": _snipeit_datetime_object(last_checkout),
            "last_checkin": _snipeit_datetime_object(last_checkin),
        },
        method="GET",
    )
    mock_transport.add_response(
        f"/hardware/{asset_id}",
        json_data={
            "status": "success",
            "messages": "Updated.",
            "payload": {"id": int(asset_id), "asset_tag": f"T-{asset_id}"},
        },
        method="PATCH",
    )


def _queue_checkout_and_checkin(
    mock_transport: Any,
    asset_id: str = "42",
    *,
    last_checkout: str | None = None,
    last_checkin: str | None = None,
) -> None:
    _queue_asset_dates(
        mock_transport,
        asset_id,
        last_checkout=last_checkout,
        last_checkin=last_checkin,
    )
    mock_transport.add_response(
        f"/hardware/{asset_id}/checkout",
        json_data={"status": "success", "messages": "Checked out."},
        method="POST",
    )
    mock_transport.add_response(
        f"/hardware/{asset_id}/checkin",
        json_data={"status": "success", "messages": "Checked in."},
        method="POST",
    )


def _queue_asset_assignee(
    mock_transport: Any, assigned_to: dict[str, Any] | None = None
) -> None:
    """Queue the asset read that checks it is free before a pair is re-recorded."""
    mock_transport.add_response(
        "/hardware/42",
        json_data={"id": 42, "asset_tag": "T-42", "assigned_to": assigned_to},
        method="GET",
    )


_OUT_TO_SOMEONE = {"id": 5, "name": "Harry", "type": "user"}


class TestHistoricalDatesIntegration:
    """Past usage is recorded in Snipe-IT on the journal's local dates."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("start", "end", "checkout_at", "checkin_at"),
        [
            # AEDT (+11:00): 8-9 March local
            (
                "2025-03-07T13:00:00+00:00",
                "2025-03-08T13:00:00+00:00",
                "2025-03-08",
                "2025-03-09",
            ),
            # AEST (+10:00): 8-9 June local
            (
                "2025-06-07T14:00:00+00:00",
                "2025-06-08T14:00:00+00:00",
                "2025-06-08",
                "2025-06-09",
            ),
        ],
        ids=["aedt", "aest"],
    )
    async def test_past_usage_is_checked_out_and_in_on_local_dates(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        start: str,
        end: str,
        checkout_at: str,
        checkin_at: str,
    ) -> None:
        journal_id = await _insert_gear_usage_journal(
            async_connection, start=start, end=end, user_timezone="Australia/Sydney"
        )
        _queue_checkout_and_checkin(mock_transport)

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        checkout_body = _request_body(mock_transport, "hardware/42/checkout")
        assert checkout_body["checkout_at"] == f"{checkout_at} 00:00:00"
        assert checkout_body["expected_checkin"] == checkin_at
        checkin_body = _request_body(mock_transport, "hardware/42/checkin")
        assert checkin_body == {
            "checkin_at": checkin_at,
            "note": f"Usage period {checkout_at} to {checkin_at}",
        }
        assert await _reference_data(
            async_connection, source="snipeit_checkout", journal_id=journal_id
        ) == {
            "checkout_at": checkout_at,
            "expected_checkin": checkin_at,
            "asset_dates_before": {"last_checkout": None, "last_checkin": None},
        }
        assert await _reference_data(
            async_connection, source="snipeit_checkin", journal_id=journal_id
        ) == {"checkin_at": checkin_at}

    @pytest.mark.asyncio
    async def test_checkout_keeps_its_local_time_of_day(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        # A day trip imported with clock times (journal 215031's shape): out
        # 09:44:35 and back 16:20:30 on 29 March 2024, Sydney daylight time.
        journal_id = await _insert_gear_usage_journal(
            async_connection,
            start="2024-03-28T22:44:35+00:00",
            end="2024-03-29T05:20:30+00:00",
            user_timezone="Australia/Sydney",
        )
        _queue_checkout_and_checkin(mock_transport)

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        checkout_body = _request_body(mock_transport, "hardware/42/checkout")
        assert checkout_body["checkout_at"] == "2024-03-29 09:44:35"
        assert checkout_body["expected_checkin"] == "2024-03-29"
        checkin_body = _request_body(mock_transport, "hardware/42/checkin")
        assert checkin_body == {
            "checkin_at": "2024-03-29",
            "note": "Usage period 2024-03-29 to 2024-03-29",
        }
        assert await _reference_data(
            async_connection, source="snipeit_checkout", journal_id=journal_id
        ) == {
            "checkout_at": "2024-03-29",
            "expected_checkin": "2024-03-29",
            "asset_dates_before": {"last_checkout": None, "last_checkin": None},
        }

    @pytest.mark.asyncio
    async def test_historical_usage_restores_the_assets_last_dates(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        # Snipe-IT stamps the check-in's asset date "now" and the checkout's
        # replaces an older one; both are restored to the trip's local times.
        journal_id = await _insert_gear_usage_journal(
            async_connection,
            start="2024-03-28T22:44:35+00:00",
            end="2024-03-29T05:20:30+00:00",
            user_timezone="Australia/Sydney",
        )
        _queue_checkout_and_checkin(
            mock_transport,
            last_checkout="2023-12-01 08:00:00",
            last_checkin="2023-12-02 17:00:00",
        )

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert len(mock_transport.responses) == 0
        assert _request_body(mock_transport, "hardware/42", method="PATCH") == {
            "last_checkout": "2024-03-29 09:44:35",
            "last_checkin": "2024-03-29 16:20:30",
        }
        methods = [(r.method, r.url.path) for r in mock_transport.requests]
        assert methods.index(("GET", "/api/v1/hardware/42")) < methods.index(
            ("POST", "/api/v1/hardware/42/checkout")
        )
        assert methods[-1] == ("PATCH", "/api/v1/hardware/42")
        checkout_reference = await _reference_data(
            async_connection, source="snipeit_checkout", journal_id=journal_id
        )
        assert checkout_reference["asset_dates_before"] == {
            "last_checkout": "2023-12-01 08:00:00",
            "last_checkin": "2023-12-02 17:00:00",
        }

    @pytest.mark.asyncio
    async def test_user_timezone_is_used_even_when_event_timezone_differs(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        # 23:30 UTC is still the same day in London but the next day in Sydney.
        # Snipe-IT reads every value in its own zone, taken to be the user's.
        journal_id = await _insert_gear_usage_journal(
            async_connection,
            start="2025-03-07T23:30:00+00:00",
            end="2025-03-08T23:30:00+00:00",
            user_timezone="Australia/Sydney",
            event_timezone="Europe/London",
        )
        _queue_checkout_and_checkin(mock_transport)

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        checkout_body = _request_body(mock_transport, "hardware/42/checkout")
        assert checkout_body["checkout_at"] == "2025-03-08 10:30:00"
        assert checkout_body["expected_checkin"] == "2025-03-09"
        checkin_body = _request_body(mock_transport, "hardware/42/checkin")
        assert checkin_body["checkin_at"] == "2025-03-09"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("previous_assignee", "posts"),
        [
            # The lost attempt did check the old asset out: return it first.
            (
                {"id": 5, "name": "Harry", "type": "user"},
                [
                    "/api/v1/hardware/41/checkin",
                    "/api/v1/hardware/42/checkout",
                    "/api/v1/hardware/42/checkin",
                ],
            ),
            # The old asset is not out to the mapped user: leave it alone.
            (None, ["/api/v1/hardware/42/checkout", "/api/v1/hardware/42/checkin"]),
            (
                {"id": 6, "name": "Someone else", "type": "user"},
                ["/api/v1/hardware/42/checkout", "/api/v1/hardware/42/checkin"],
            ),
        ],
        ids=["old-asset-still-out", "old-asset-returned", "old-asset-with-other-user"],
    )
    async def test_a_changed_gear_item_is_checked_out_in_place_of_a_failed_one(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        previous_assignee: dict[str, Any] | None,
        posts: list[str],
    ) -> None:
        """A failed checkout of a gear item no longer listed is dropped for the new one.

        The failure may have been a lost response after Snipe-IT checked the old
        asset out, so the old asset is returned before its pair is forgotten.
        """
        journal_id = await _insert_gear_usage_journal(
            async_connection,
            start="2025-03-07T13:00:00+00:00",
            end="2025-03-08T13:00:00+00:00",
            asset_id="42",
        )
        await _insert_checkout_metadata(
            async_connection, asset_id="41", journal_id=journal_id, sync_status="failed"
        )
        mock_transport.add_response(
            "/hardware/41",
            json_data={"id": 41, "asset_tag": "T-41", "assigned_to": previous_assignee},
            method="GET",
        )
        # Consumed only when the old asset is returned.
        mock_transport.add_response(
            "/hardware/41/checkin",
            json_data={"status": "success", "messages": "Checked in."},
        )
        _queue_checkout_and_checkin(mock_transport)

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert [
            r.url.path for r in mock_transport.requests if r.method == "POST"
        ] == posts
        result = await async_connection.execute(
            text("""
                SELECT external_id, sync_status FROM sync_metadata
                WHERE integration_source = 'snipeit_checkout'
                  AND internal_uuid = :journal_id
            """),
            {"journal_id": str(journal_id)},
        )
        row = result.fetchone()
        assert row is not None
        assert row.external_id == f"snipeit_checkout:42:{journal_id}"
        assert row.sync_status == "success"


class TestCheckinSyncIntegration:
    """Integration tests for the Snipe-IT check-in pipeline."""

    @pytest.mark.asyncio
    async def test_push_checkin_create_posts_to_snipeit(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """A recorded checkout is returned and a snipeit_checkin row is saved."""
        journal_result = await async_connection.execute(
            text("""
                INSERT INTO journals (title, content, user_id,
                    event_date_range_start, event_date_range_end)
                VALUES ('Rope usage', '', 'user-123', '2024-06-01', '2024-06-02')
                RETURNING id
            """)
        )
        journal_row = journal_result.fetchone()
        assert journal_row is not None
        journal_id = journal_row.id

        await _insert_checkout_metadata(
            async_connection, asset_id="42", journal_id=journal_id
        )

        mock_transport.add_response(
            "/hardware/42/checkin",
            json_data={"status": "success", "messages": "Asset checked in."},
        )

        def factory() -> Any:
            return _session_factory(async_connection)

        await snipeit_sync_service.push_checkin_create(
            GearUsagePair(journal_id, 42),
            session_factory=factory,
            note="Returned after trip",
        )

        # The checkin POST was made.
        assert len(mock_transport.responses) == 0
        checkin_request = next(
            r for r in mock_transport.requests if "checkin" in str(r.url)
        )
        body = json.loads(checkin_request.content)
        assert body["note"] == "Returned after trip"

        # The snipeit_checkin sync_metadata row was recorded as success.
        meta_result = await async_connection.execute(
            text("""
                SELECT internal_uuid, sync_status
                FROM sync_metadata
                WHERE integration_source = 'snipeit_checkin'
                  AND external_id = :external_id
            """),
            {"external_id": f"snipeit_checkin:42:{journal_id}"},
        )
        meta_row = meta_result.fetchone()
        assert meta_row is not None
        assert meta_row.internal_uuid == str(journal_id)
        assert meta_row.sync_status == "success"

    @pytest.mark.asyncio
    async def test_push_checkin_resolves_asset_after_journal_deleted(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Check-in works when the journal/usage data is gone (deletion path).

        Only the checkout sync_metadata row exists — no journal or gear-usage
        rows — mirroring the cascade-deleted state after ``JournalDeleted``.
        """
        deleted_journal_id = 987654

        await _insert_checkout_metadata(
            async_connection, asset_id="77", journal_id=deleted_journal_id
        )

        mock_transport.add_response(
            "/hardware/77/checkin",
            json_data={"status": "success", "messages": "Asset checked in."},
        )

        def factory() -> Any:
            return _session_factory(async_connection)

        await snipeit_sync_service.push_checkin_create(
            GearUsagePair(deleted_journal_id, 77),
            session_factory=factory,
            note="Gear usage journal deleted",
        )

        assert len(mock_transport.responses) == 0
        assert any("hardware/77/checkin" in str(r.url) for r in mock_transport.requests)

    @pytest.mark.asyncio
    async def test_push_checkin_skips_without_checkout(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """No recorded checkout means there is nothing to check in."""

        def factory() -> Any:
            return _session_factory(async_connection)

        await snipeit_sync_service.push_checkin_create(
            GearUsagePair(555, 42),
            session_factory=factory,
        )

        assert len(mock_transport.requests) == 0

    @pytest.mark.asyncio
    async def test_push_checkin_idempotent(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """A pre-existing successful checkin row makes the call a no-op."""
        journal_id = 424242
        await _insert_checkout_metadata(
            async_connection, asset_id="42", journal_id=journal_id
        )
        # Pre-existing successful checkin.
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
                "external_id": f"snipeit_checkin:42:{journal_id}",
                "journal_id": str(journal_id),
            },
        )

        def factory() -> Any:
            return _session_factory(async_connection)

        await snipeit_sync_service.push_checkin_create(
            GearUsagePair(journal_id, 42),
            session_factory=factory,
        )

        assert len(mock_transport.requests) == 0

    @pytest.mark.asyncio
    async def test_immediate_checkin_on_create_when_period_past(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """A checkout with a past usage window is checked out then checked in."""
        journal_id = await _insert_gear_usage_journal(
            async_connection,
            start="2000-01-01T00:00:00+00:00",
            end="2000-01-02T00:00:00+00:00",
        )

        _queue_checkout_and_checkin(mock_transport)

        def factory() -> Any:
            return _session_factory(async_connection)

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=factory,
        )

        # Both the checkout and the immediate checkin POSTs were made.
        assert len(mock_transport.responses) == 0
        urls = [str(r.url) for r in mock_transport.requests]
        assert any("hardware/42/checkout" in u for u in urls)
        assert any("hardware/42/checkin" in u for u in urls)

        # Both sync_metadata rows are recorded as success.
        for source in ("snipeit_checkout", "snipeit_checkin"):
            result = await async_connection.execute(
                text("""
                    SELECT sync_status FROM sync_metadata
                    WHERE integration_source = :source AND internal_uuid = :journal_id
                """),
                {"source": source, "journal_id": str(journal_id)},
            )
            row = result.fetchone()
            assert row is not None, source
            assert row.sync_status == "success", source

    @pytest.mark.asyncio
    async def test_fetch_overdue_gear_usage_selects_unreturned_past_usage(
        self,
        async_connection: AsyncConnection,
    ) -> None:
        """The periodic sweep selects past, not-yet-checked-in usage on local dates."""
        from snipeit_sync_service import (
            AssetUsageDates,
            OverdueGearUsage,
            fetch_overdue_gear_usage,
        )

        # Overdue, no check-in → selected, dated in the user's zone (AEDT).
        overdue_id = await _insert_gear_usage_journal(
            async_connection,
            start="2025-03-07T13:00:00+00:00",
            end="2025-03-08T13:00:00+00:00",
            asset_id="41",
            user_timezone="Australia/Sydney",
        )
        # Future window → excluded.
        future_id = await _insert_gear_usage_journal(
            async_connection,
            start="2099-01-01T00:00:00+00:00",
            end="2099-01-02T00:00:00+00:00",
            asset_id="42",
        )
        # Overdue but already checked in → excluded.
        done_id = await _insert_gear_usage_journal(
            async_connection,
            start="2000-01-01T00:00:00+00:00",
            end="2000-01-02T00:00:00+00:00",
            asset_id="43",
        )
        for asset_id, jid in (("41", overdue_id), ("42", future_id), ("43", done_id)):
            await _insert_checkout_metadata(
                async_connection, asset_id=asset_id, journal_id=jid
            )

        # Mark the "done" journal as already checked in.
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
                "external_id": f"snipeit_checkin:43:{done_id}",
                "journal_id": str(done_id),
            },
        )

        overdue = await fetch_overdue_gear_usage(
            lambda: _session_factory(async_connection), "user-123"
        )

        assert overdue == [
            OverdueGearUsage(
                journal_id=overdue_id,
                asset_id=41,
                checkout_at=date(2025, 3, 8),
                checkin_at=date(2025, 3, 9),
                usage_dates=AssetUsageDates(
                    last_checkout=datetime(2025, 3, 8),
                    last_checkin=datetime(2025, 3, 9),
                ),
            )
        ]


async def _insert_recorded_sync_row(
    async_connection: AsyncConnection,
    *,
    source: str,
    journal_id: int,
    reference_data: dict[str, Any] | None,
    error_message: str | None = None,
    asset_id: str = "42",
    sync_status: str = "success",
) -> None:
    """Insert a checkout/check-in sync row (successful by default) with its dates."""
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata
                (integration_source, external_id, internal_uuid,
                 last_synced_at, version_hash, sync_status, reference_data,
                 error_message, retry_count, created_at, updated_at)
            VALUES
                (:source, :external_id, :journal_id,
                 now(), 'hash', :sync_status, :reference_data,
                 :error_message, 0, now(), now())
        """),
        {
            "sync_status": sync_status,
            "source": source,
            "external_id": f"{source}:{asset_id}:{journal_id}",
            "journal_id": str(journal_id),
            "reference_data": (
                json.dumps(reference_data) if reference_data is not None else None
            ),
            "error_message": error_message,
        },
    )


async def _sydney_trip(async_connection: AsyncConnection) -> int:
    """A past trip that is 8-9 March 2025 in Sydney (AEDT)."""
    return await _insert_gear_usage_journal(
        async_connection,
        start="2025-03-07T13:00:00+00:00",
        end="2025-03-08T13:00:00+00:00",
        user_timezone="Australia/Sydney",
    )


class TestAssetDatesSnapshotIntegration:
    """The asset dates a checkout replaces are kept and restored after check-in."""

    BEFORE = {
        "last_checkout": "2024-01-01 08:00:00",
        "last_checkin": "2024-01-02 17:00:00",
    }

    @pytest.mark.asyncio
    async def test_superseded_checkout_reuses_the_original_snapshot(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        # The first pair (1-2 March) left its own dates on the asset; the pair
        # re-recorded for 8-9 March must be restored against the dates before it.
        journal_id = await _sydney_trip(async_connection)
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkout",
            journal_id=journal_id,
            reference_data={
                "checkout_at": "2025-03-01",
                "expected_checkin": "2025-03-02",
                "asset_dates_before": self.BEFORE,
            },
        )
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkin",
            journal_id=journal_id,
            reference_data={"checkin_at": "2025-03-02"},
        )
        _queue_asset_assignee(mock_transport)
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
        mock_transport.add_response(
            "/hardware/42",
            json_data={
                "status": "success",
                "payload": {"id": 42, "asset_tag": "T-42"},
            },
            method="PATCH",
        )

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert len(mock_transport.responses) == 0
        # Read once, to check the asset is free; its dates are not read again.
        assert [(r.method, r.url.path) for r in mock_transport.requests].count(
            ("GET", "/api/v1/hardware/42")
        ) == 1
        checkout_reference = await _reference_data(
            async_connection, source="snipeit_checkout", journal_id=journal_id
        )
        assert checkout_reference["asset_dates_before"] == self.BEFORE
        assert _request_body(mock_transport, "hardware/42", method="PATCH") == {
            "last_checkout": "2025-03-08 00:00:00",
            "last_checkin": "2025-03-09 00:00:00",
        }

    @pytest.mark.asyncio
    async def test_checkout_moved_to_another_asset_reads_that_assets_dates(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _sydney_trip(async_connection)
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkout",
            journal_id=journal_id,
            reference_data={"asset_dates_before": self.BEFORE},
            asset_id="41",
            sync_status="failed",
        )
        mock_transport.add_response(
            "/hardware/41",
            json_data={"id": 41, "asset_tag": "T-41", "assigned_to": None},
            method="GET",
        )
        _queue_checkout_and_checkin(
            mock_transport,
            last_checkout="2025-01-10 09:00:00",
            last_checkin=None,
        )

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert len(mock_transport.responses) == 0
        checkout_reference = await _reference_data(
            async_connection, source="snipeit_checkout", journal_id=journal_id
        )
        assert checkout_reference["asset_dates_before"] == {
            "last_checkout": "2025-01-10 09:00:00",
            "last_checkin": None,
        }

    @pytest.mark.asyncio
    async def test_older_usage_keeps_the_assets_later_dates(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        # Importing a 2024 trip after the asset was used in 2026.
        journal_id = await _insert_gear_usage_journal(
            async_connection,
            start="2024-03-28T22:44:35+00:00",
            end="2024-03-29T05:20:30+00:00",
            user_timezone="Australia/Sydney",
        )
        _queue_checkout_and_checkin(
            mock_transport,
            last_checkout="2026-01-21 23:14:00",
            last_checkin="2026-02-12 21:26:37",
        )

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _request_body(mock_transport, "hardware/42", method="PATCH") == {
            "last_checkout": "2026-01-21 23:14:00",
            "last_checkin": "2026-02-12 21:26:37",
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "patch_response",
        [{"status": "error", "messages": {"last_checkin": ["Invalid."]}}, None],
        ids=["rejected", "transport-error"],
    )
    async def test_failed_restore_does_not_fail_the_checkin(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        patch_response: dict[str, Any] | None,
    ) -> None:
        journal_id = await _sydney_trip(async_connection)
        mock_transport.add_response(
            "/hardware/42", json_data={"id": 42, "asset_tag": "T-42"}, method="GET"
        )
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
        if patch_response is not None:
            mock_transport.add_response(
                "/hardware/42", json_data=patch_response, method="PATCH"
            )

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert ("PATCH", "/api/v1/hardware/42") in [
            (r.method, r.url.path) for r in mock_transport.requests
        ]
        for source in ("snipeit_checkout", "snipeit_checkin"):
            result = await async_connection.execute(
                text("""
                    SELECT sync_status FROM sync_metadata
                    WHERE integration_source = :source AND internal_uuid = :journal_id
                """),
                {"source": source, "journal_id": str(journal_id)},
            )
            row = result.fetchone()
            assert row is not None, source
            assert row.sync_status == "success", source

    @pytest.mark.asyncio
    async def test_checkin_without_usage_dates_leaves_the_asset_dates_alone(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        # e.g. the journal was deleted: Snipe-IT's "now" is the right return time.
        journal_id = await _sydney_trip(async_connection)
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkout",
            journal_id=journal_id,
            reference_data={
                "checkout_at": "2025-03-08",
                "expected_checkin": "2025-03-09",
                "asset_dates_before": self.BEFORE,
            },
        )
        mock_transport.add_response(
            "/hardware/42/checkin",
            json_data={"status": "success", "messages": "Checked in."},
            method="POST",
        )

        checked_in = await snipeit_sync_service.push_checkin_create(
            GearUsagePair(journal_id, 42),
            session_factory=lambda: _session_factory(async_connection),
        )

        assert checked_in is True
        assert [(r.method, r.url.path) for r in mock_transport.requests] == [
            ("POST", "/api/v1/hardware/42/checkin")
        ]


class TestReconcileGearUsageIntegration:
    """Updating a journal re-records Snipe-IT history only where it is missing."""

    @pytest.mark.asyncio
    async def test_open_checkout_is_checked_in_on_the_journal_date(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _sydney_trip(async_connection)
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkout",
            journal_id=journal_id,
            reference_data={
                "checkout_at": "2025-03-08",
                "expected_checkin": "2099-01-01",
            },
        )
        # Recorded before asset dates were kept: they are read before the
        # check-in instead, while the asset still shows the check-in before it.
        _queue_asset_dates(
            mock_transport,
            last_checkout="2025-03-08 00:00:00",
            last_checkin="2025-02-01 18:00:00",
        )
        mock_transport.add_response(
            "/hardware/42/checkin",
            json_data={"status": "success", "messages": "Checked in."},
            method="POST",
        )

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert [(r.method, r.url.path) for r in mock_transport.requests] == [
            ("GET", "/api/v1/hardware/42"),
            ("POST", "/api/v1/hardware/42/checkin"),
            ("PATCH", "/api/v1/hardware/42"),
        ]
        checkin_body = _request_body(mock_transport, "hardware/42/checkin")
        assert checkin_body["checkin_at"] == "2025-03-09"
        assert _request_body(mock_transport, "hardware/42", method="PATCH") == {
            "last_checkout": "2025-03-08 00:00:00",
            "last_checkin": "2025-03-09 00:00:00",
        }

    @pytest.mark.asyncio
    async def test_changed_checkout_date_after_checkin_records_a_new_pair(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _sydney_trip(async_connection)
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkout",
            journal_id=journal_id,
            reference_data={
                "checkout_at": "2025-03-01",
                "expected_checkin": "2025-03-02",
            },
        )
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkin",
            journal_id=journal_id,
            reference_data={"checkin_at": "2025-03-02"},
        )
        _queue_asset_assignee(mock_transport)
        _queue_checkout_and_checkin(mock_transport)

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert len(mock_transport.responses) == 0
        assert (
            _request_body(mock_transport, "hardware/42/checkout")["checkout_at"]
            == "2025-03-08 00:00:00"
        )
        assert (
            _request_body(mock_transport, "hardware/42/checkin")["checkin_at"]
            == "2025-03-09"
        )
        assert await _reference_data(
            async_connection, source="snipeit_checkout", journal_id=journal_id
        ) == {
            "checkout_at": "2025-03-08",
            "expected_checkin": "2025-03-09",
            "asset_dates_before": {"last_checkout": None, "last_checkin": None},
        }
        assert await _reference_data(
            async_connection, source="snipeit_checkin", journal_id=journal_id
        ) == {"checkin_at": "2025-03-09"}

    @pytest.mark.asyncio
    async def test_changed_checkout_date_waits_while_the_asset_is_out(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Snipe-IT would refuse the new checkout, so the recorded pair is kept."""
        journal_id = await _sydney_trip(async_connection)
        recorded = {"checkout_at": "2025-03-01", "expected_checkin": "2025-03-02"}
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkout",
            journal_id=journal_id,
            reference_data=recorded,
        )
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkin",
            journal_id=journal_id,
            reference_data={"checkin_at": "2025-03-02"},
        )
        _queue_asset_assignee(mock_transport, _OUT_TO_SOMEONE)

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _posts(mock_transport) == []
        assert await _sync_statuses(async_connection, journal_id) == {
            "snipeit_checkout": "success",
            "snipeit_checkin": "success",
        }
        assert (
            await _reference_data(
                async_connection, source="snipeit_checkout", journal_id=journal_id
            )
            == recorded
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("checkout_reference", "checkin_error"),
        [
            # Only the check-in date changed: that checkout is already returned.
            ({"checkout_at": "2025-03-08", "expected_checkin": "2025-03-05"}, None),
            # A row from before dates were recorded is not re-recorded.
            (None, None),
            # A terminal 403/404 check-in may have left the asset checked out.
            (
                {"checkout_at": "2025-03-01", "expected_checkin": "2025-03-02"},
                "Terminal: API 404",
            ),
        ],
        ids=["checkin-date-only", "legacy-row", "terminal-checkin"],
    )
    async def test_checked_in_usage_is_left_alone(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        checkout_reference: dict[str, Any] | None,
        checkin_error: str | None,
    ) -> None:
        journal_id = await _sydney_trip(async_connection)
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkout",
            journal_id=journal_id,
            reference_data=checkout_reference,
        )
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkin",
            journal_id=journal_id,
            reference_data={"checkin_at": "2025-03-05"},
            error_message=checkin_error,
        )

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert mock_transport.requests == []

    @pytest.mark.asyncio
    async def test_supersede_loses_to_a_concurrent_update(
        self,
        snipeit_sync_service: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """A second update that read the old dates cannot supersede again."""
        journal_id = await _sydney_trip(async_connection)
        current = {"checkout_at": "2025-03-08", "expected_checkin": "2025-03-09"}
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkout",
            journal_id=journal_id,
            reference_data=current,
        )
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkin",
            journal_id=journal_id,
            reference_data={"checkin_at": "2025-03-09"},
        )

        superseded = await snipeit_sync_service._supersede_checkout(
            GearUsagePair(journal_id, 42),
            recorded_reference=json.dumps(
                {"checkout_at": "2025-03-01", "expected_checkin": "2025-03-02"}
            ),
            session_factory=lambda: _session_factory(async_connection),
            reason="checkout date changed",
        )

        assert superseded is False
        assert (
            await _reference_data(
                async_connection, source="snipeit_checkout", journal_id=journal_id
            )
            == current
        )
        assert await _reference_data(
            async_connection, source="snipeit_checkin", journal_id=journal_id
        ) == {"checkin_at": "2025-03-09"}


def _activity_row(
    log_id: int,
    day: str,
    *,
    action_type: str = "checkout",
    asset_id: int = 42,
    user_id: int = 5,
    time: str = "00:00:00",
) -> dict[str, Any]:
    """An activity report row as Snipe-IT's ``ActionlogsTransformer`` returns it."""
    return {
        "id": log_id,
        "action_type": action_type,
        "action_date": {"datetime": f"{day} {time}", "formatted": day},
        "created_at": {"datetime": "2026-09-13 09:00:00", "formatted": ""},
        "item": {"id": asset_id, "name": "Tent", "type": "asset"},
        "target": {"id": user_id, "name": "Harry", "type": "user"},
    }


def _queue_activity(
    mock_transport: Any, action_type: str, *rows: dict[str, Any]
) -> None:
    """Serve one page of the activity report for ``checkout`` or ``checkin``."""
    mock_transport.add_response(
        f"action_type={action_type}",
        json_data={"total": len(rows), "rows": list(rows)},
    )


def _posts(mock_transport: Any) -> list[str]:
    """The paths of every POST sent to Snipe-IT, in order."""
    return [r.url.path for r in mock_transport.requests if r.method == "POST"]


def _looked_up_checkins(mock_transport: Any) -> bool:
    return any("action_type=checkin" in str(r.url) for r in mock_transport.requests)


async def _sync_statuses(
    async_connection: AsyncConnection, journal_id: int
) -> dict[str, str]:
    result = await async_connection.execute(
        text("""
            SELECT integration_source, sync_status FROM sync_metadata
            WHERE internal_uuid = :journal_id
              AND integration_source IN ('snipeit_checkout', 'snipeit_checkin')
        """),
        {"journal_id": str(journal_id)},
    )
    return {row.integration_source: row.sync_status for row in result.fetchall()}


_CHECKOUT_POST = "/api/v1/hardware/42/checkout"
_CHECKIN_POST = "/api/v1/hardware/42/checkin"


class TestLinkExistingActivityIntegration:
    """History already in Snipe-IT is linked rather than recorded twice."""

    @pytest.mark.asyncio
    async def test_matching_checkout_and_checkin_are_linked(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _sydney_trip(async_connection)
        _queue_activity(mock_transport, "checkout", _activity_row(100, "2025-03-08"))
        _queue_activity(
            mock_transport,
            "checkin",
            _activity_row(101, "2025-03-09", action_type="checkin from"),
        )

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _posts(mock_transport) == []
        assert await _sync_statuses(async_connection, journal_id) == {
            "snipeit_checkout": "success",
            "snipeit_checkin": "success",
        }
        assert await _reference_data(
            async_connection, source="snipeit_checkout", journal_id=journal_id
        ) == {
            "checkout_at": "2025-03-08",
            "expected_checkin": "2025-03-09",
            "snipeit_log_id": 100,
        }
        assert await _reference_data(
            async_connection, source="snipeit_checkin", journal_id=journal_id
        ) == {"checkin_at": "2025-03-09", "snipeit_log_id": 101}

    @pytest.mark.asyncio
    async def test_linked_checkout_restores_only_the_last_checkin(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        # The checkout was entered by hand, so Snipe-IT's last checkout is its
        # own; only the check-in the worker posts overwrites a date.
        journal_id = await _sydney_trip(async_connection)
        _queue_activity(mock_transport, "checkout", _activity_row(100, "2025-03-08"))
        _queue_asset_dates(
            mock_transport,
            last_checkout="2025-03-08 07:30:00",
            last_checkin="2025-02-01 18:00:00",
        )
        mock_transport.add_response(
            "/hardware/42/checkin",
            json_data={"status": "success", "messages": "Checked in."},
            method="POST",
        )

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _posts(mock_transport) == [_CHECKIN_POST]
        assert len(mock_transport.responses) == 0
        assert _request_body(mock_transport, "hardware/42", method="PATCH") == {
            "last_checkin": "2025-03-09 00:00:00"
        }

    @pytest.mark.asyncio
    async def test_checkout_whose_response_was_lost_still_restores_last_checkout(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        # The first checkout reached Snipe-IT but its response never arrived. The
        # retry links that checkout and must still restore the later last
        # checkout it replaced, read before the first attempt posted.
        journal_id = await _sydney_trip(async_connection)
        before = {
            "last_checkout": "2026-01-21 23:14:00",
            "last_checkin": "2026-02-12 21:26:37",
        }
        mock_transport.add_response(
            "/hardware/42",
            json_data={
                "id": 42,
                "asset_tag": "T-42",
                "last_checkout": _snipeit_datetime_object(before["last_checkout"]),
                "last_checkin": _snipeit_datetime_object(before["last_checkin"]),
            },
            method="GET",
        )
        # No checkout response is queued, so the POST fails as if it were lost.
        with pytest.raises(ValueError, match="No mock response"):
            await snipeit_sync_service.push_checkout_create(
                journal_id=journal_id,
                session_factory=lambda: _session_factory(async_connection),
            )

        _queue_activity(mock_transport, "checkout", _activity_row(100, "2025-03-08"))
        mock_transport.add_response(
            "/hardware/42/checkin",
            json_data={"status": "success", "messages": "Checked in."},
            method="POST",
        )
        mock_transport.add_response(
            "/hardware/42",
            json_data={"status": "success", "payload": {"id": 42, "asset_tag": "T-42"}},
            method="PATCH",
        )

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert len(mock_transport.responses) == 0
        assert _posts(mock_transport) == [_CHECKOUT_POST, _CHECKIN_POST]
        checkout_reference = await _reference_data(
            async_connection, source="snipeit_checkout", journal_id=journal_id
        )
        assert checkout_reference["snipeit_log_id"] == 100
        assert checkout_reference["asset_dates_before"] == before
        assert _request_body(mock_transport, "hardware/42", method="PATCH") == before

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "log",
        [
            _activity_row(100, "2025-03-07"),
            _activity_row(100, "2025-03-08", user_id=6),
            _activity_row(100, "2025-03-08", asset_id=41),
            # Snipe-IT 6.3.1 can ignore the report's action_type filter.
            _activity_row(100, "2025-03-08", action_type="checkin from"),
            # Another usage of the asset that day, posted with its own time.
            _activity_row(100, "2025-03-08", time="09:00:00"),
        ],
        ids=["other-date", "other-user", "other-asset", "other-action", "other-time"],
    )
    async def test_non_matching_checkout_is_recorded(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        log: dict[str, Any],
    ) -> None:
        journal_id = await _sydney_trip(async_connection)
        _queue_activity(mock_transport, "checkout", log)
        _queue_checkout_and_checkin(mock_transport)

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _posts(mock_transport) == [_CHECKOUT_POST, _CHECKIN_POST]
        # A checkout we recorded ourselves leaves the asset out, so there is
        # no earlier check-in to link.
        assert not _looked_up_checkins(mock_transport)

    @pytest.mark.asyncio
    async def test_checkout_linked_to_another_journal_is_not_reused(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Two journals using the same asset on the same day need two checkouts."""
        journal_id = await _sydney_trip(async_connection)
        other_journal_id = await _insert_gear_usage_journal(
            async_connection,
            start="2025-03-07T13:00:00+00:00",
            end="2025-03-08T13:00:00+00:00",
            asset_id="41",
        )
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkout",
            journal_id=other_journal_id,
            reference_data={
                "checkout_at": "2025-03-08",
                "expected_checkin": "2025-03-08",
                "snipeit_log_id": 100,
            },
        )
        _queue_activity(mock_transport, "checkout", _activity_row(100, "2025-03-08"))
        _queue_checkout_and_checkin(mock_transport)

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _posts(mock_transport) == [_CHECKOUT_POST, _CHECKIN_POST]

    @pytest.mark.asyncio
    async def test_checkin_older_than_the_linked_checkout_is_not_linked(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _sydney_trip(async_connection)
        _queue_activity(mock_transport, "checkout", _activity_row(100, "2025-03-08"))
        _queue_activity(
            mock_transport,
            "checkin",
            _activity_row(90, "2025-03-09", action_type="checkin from"),
        )
        mock_transport.add_response(
            "/hardware/42/checkin",
            json_data={"status": "success", "messages": "Checked in."},
        )

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _posts(mock_transport) == [_CHECKIN_POST]
        assert await _reference_data(
            async_connection, source="snipeit_checkin", journal_id=journal_id
        ) == {"checkin_at": "2025-03-09"}


async def _usage_of_the_same_gear(
    async_connection: AsyncConnection, journal_id: int, *, start: str, end: str
) -> int:
    """Insert another GEAR_USAGE journal on the gear item ``journal_id`` uses."""
    new_journal_id: int = _returned_id(
        await async_connection.execute(
            text("""
                INSERT INTO journals (title, content, user_id,
                    event_date_range_start, event_date_range_end)
                VALUES ('Second trip', '', 'user-123', :start, :end)
                RETURNING id
            """),
            {
                "start": datetime.fromisoformat(start),
                "end": datetime.fromisoformat(end),
            },
        )
    )
    await async_connection.execute(
        text("""
            WITH entry AS (
                INSERT INTO journal_gear_usage_data (journal_id)
                VALUES (:new_journal_id)
                RETURNING journal_id
            )
            INSERT INTO journal_gear_usage_items
                (journal_id, gear_item_id, checkout_date, checkin_date)
            SELECT entry.journal_id, u.gear_item_id, NULL, NULL
            FROM entry, journal_gear_usage_items u
            WHERE u.journal_id = :journal_id
        """),
        {"new_journal_id": new_journal_id, "journal_id": journal_id},
    )
    return new_journal_id


async def _two_canyons(async_connection: AsyncConnection) -> tuple[int, int]:
    """Two usages of one asset on 26 Oct 2024 in Sydney (AEDT): 08:30-11:33, 12:43-18:33."""
    morning = await _insert_gear_usage_journal(
        async_connection,
        start="2024-10-25T21:30:00+00:00",
        end="2024-10-26T00:33:00+00:00",
        user_timezone="Australia/Sydney",
    )
    afternoon = await _usage_of_the_same_gear(
        async_connection,
        morning,
        start="2024-10-26T01:43:00+00:00",
        end="2024-10-26T07:33:00+00:00",
    )
    return morning, afternoon


_MORNING_CHECKOUT = _activity_row(100, "2024-10-26", time="08:30:00")
_MORNING_CHECKIN = _activity_row(
    101, "2024-10-26", action_type="checkin from", time="11:33:00"
)


async def _link_afternoon_to(
    async_connection: AsyncConnection,
    afternoon: int,
    *,
    log_id: int = 100,
    checkout_extra: dict[str, Any] | None = None,
    checkin_error: str | None = None,
) -> None:
    """Record the afternoon's pair as linked to existing entries, as #1572 left it."""
    await _insert_recorded_sync_row(
        async_connection,
        source="snipeit_checkout",
        journal_id=afternoon,
        reference_data={
            "checkout_at": "2024-10-26",
            "expected_checkin": "2024-10-26",
            "snipeit_log_id": log_id,
            **(checkout_extra or {}),
        },
    )
    await _insert_recorded_sync_row(
        async_connection,
        source="snipeit_checkin",
        journal_id=afternoon,
        reference_data={"checkin_at": "2024-10-26", "snipeit_log_id": log_id + 1},
        error_message=checkin_error,
    )


def _read_checkout_activity(mock_transport: Any) -> bool:
    return any("action_type=checkout" in str(r.url) for r in mock_transport.requests)


class TestSameDayUsagesIntegration:
    """Two usages of one asset on one day each get their own checkout and check-in."""

    @pytest.mark.asyncio
    async def test_usage_after_one_posted_before_log_ids_were_kept_is_recorded(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """The morning pair was posted without keeping its log id (#1572).

        The afternoon checkout must not take the morning's entry as its own: it
        is at another time of day.
        """
        morning, afternoon = await _two_canyons(async_connection)
        for source in ("snipeit_checkout", "snipeit_checkin"):
            await _insert_recorded_sync_row(
                async_connection,
                source=source,
                journal_id=morning,
                reference_data={"checkout_at": "2024-10-26"},
            )
        _queue_activity(mock_transport, "checkout", _MORNING_CHECKOUT)
        _queue_activity(
            mock_transport,
            "checkout",
            _activity_row(102, "2024-10-26", time="12:43:00"),
            _MORNING_CHECKOUT,
        )
        _queue_activity(mock_transport, "checkin", _MORNING_CHECKIN)
        _queue_checkout_and_checkin(mock_transport)

        await snipeit_sync_service.push_checkout_create(
            journal_id=afternoon,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _posts(mock_transport) == [_CHECKOUT_POST, _CHECKIN_POST]
        assert _request_body(mock_transport, "checkout", method="POST")[
            "checkout_at"
        ] == ("2024-10-26 12:43:00")
        checkout_reference = await _reference_data(
            async_connection, source="snipeit_checkout", journal_id=afternoon
        )
        assert checkout_reference["snipeit_log_id"] == 102
        assert "snipeit_log_id" not in await _reference_data(
            async_connection, source="snipeit_checkin", journal_id=afternoon
        )

    @pytest.mark.asyncio
    async def test_date_only_usages_on_one_day_are_both_recorded(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Both checkouts are at midnight, so only the kept log id tells them apart."""
        first = await _sydney_trip(async_connection)
        second = await _usage_of_the_same_gear(
            async_connection,
            first,
            start="2025-03-07T13:00:00+00:00",
            end="2025-03-08T13:00:00+00:00",
        )
        _queue_activity(mock_transport, "checkout")
        _queue_activity(mock_transport, "checkout", _activity_row(100, "2025-03-08"))
        _queue_checkout_and_checkin(mock_transport)
        await snipeit_sync_service.push_checkout_create(
            journal_id=first,
            session_factory=lambda: _session_factory(async_connection),
        )
        _queue_activity(mock_transport, "checkout", _activity_row(100, "2025-03-08"))
        _queue_activity(
            mock_transport,
            "checkout",
            _activity_row(102, "2025-03-08"),
            _activity_row(100, "2025-03-08"),
        )
        _queue_checkout_and_checkin(mock_transport)

        await snipeit_sync_service.push_checkout_create(
            journal_id=second,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _posts(mock_transport) == [_CHECKOUT_POST, _CHECKIN_POST] * 2
        for journal_id, log_id in ((first, 100), (second, 102)):
            reference = await _reference_data(
                async_connection, source="snipeit_checkout", journal_id=journal_id
            )
            assert reference["snipeit_log_id"] == log_id

    @pytest.mark.asyncio
    async def test_lost_response_retry_links_the_entry_at_its_checkout_time(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        _, afternoon = await _two_canyons(async_connection)
        _queue_asset_dates(mock_transport)
        # No checkout response is queued, so the POST fails as if it were lost.
        with pytest.raises(ValueError, match="No mock response"):
            await snipeit_sync_service.push_checkout_create(
                journal_id=afternoon,
                session_factory=lambda: _session_factory(async_connection),
            )
        _queue_activity(
            mock_transport,
            "checkout",
            _activity_row(102, "2024-10-26", time="12:43:00"),
            _MORNING_CHECKOUT,
        )
        mock_transport.add_response(
            "/hardware/42/checkin",
            json_data={"status": "success", "messages": "Checked in."},
            method="POST",
        )

        await snipeit_sync_service.push_checkout_create(
            journal_id=afternoon,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _posts(mock_transport) == [_CHECKOUT_POST, _CHECKIN_POST]
        checkout_reference = await _reference_data(
            async_connection, source="snipeit_checkout", journal_id=afternoon
        )
        assert checkout_reference["snipeit_log_id"] == 102

    @pytest.mark.asyncio
    async def test_unreadable_report_after_posting_keeps_no_log_id(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _sydney_trip(async_connection)
        _queue_activity(mock_transport, "checkout")
        mock_transport.add_response("action_type=checkout", status_code=403)
        _queue_checkout_and_checkin(mock_transport)

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _posts(mock_transport) == [_CHECKOUT_POST, _CHECKIN_POST]
        assert await _sync_statuses(async_connection, journal_id) == {
            "snipeit_checkout": "success",
            "snipeit_checkin": "success",
        }
        assert "snipeit_log_id" not in await _reference_data(
            async_connection, source="snipeit_checkout", journal_id=journal_id
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("posting", "age", "deferred"),
        [
            (True, 0, True),
            # Not yet posting: no entry of its own can be among the candidates.
            (False, 0, False),
            # Its worker died mid-post; the in-flight window has passed.
            (True, 3600, False),
        ],
        ids=["posting", "not-yet-posting", "stale"],
    )
    async def test_link_waits_for_a_checkout_being_posted_on_the_asset(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        posting: bool,
        age: int,
        deferred: bool,
    ) -> None:
        """The entry found may be the one the other journal is posting.

        Until that journal claims its entry, it cannot be told apart from an
        entry made by hand, so the link is retried rather than taken.
        """
        from snipeit_sync_service import SnipeItSyncInProgress

        first = await _sydney_trip(async_connection)
        second = await _usage_of_the_same_gear(
            async_connection,
            first,
            start="2025-03-07T13:00:00+00:00",
            end="2025-03-08T13:00:00+00:00",
        )
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkout",
            journal_id=first,
            reference_data={"posting": True} if posting else {},
            sync_status="pending",
        )
        await async_connection.execute(
            text("""
                UPDATE sync_metadata
                SET updated_at = now() - make_interval(secs => :age)
                WHERE integration_source = 'snipeit_checkout'
                  AND internal_uuid = :journal_id
            """),
            {"age": age, "journal_id": str(first)},
        )
        _queue_activity(mock_transport, "checkout", _activity_row(100, "2025-03-08"))

        if deferred:
            with pytest.raises(SnipeItSyncInProgress):
                await snipeit_sync_service.push_checkout_create(
                    journal_id=second,
                    session_factory=lambda: _session_factory(async_connection),
                )
            assert _posts(mock_transport) == []
            assert (await _sync_statuses(async_connection, second))[
                "snipeit_checkout"
            ] == "failed"
        else:
            mock_transport.add_response(
                "/hardware/42/checkin",
                json_data={"status": "success", "messages": "Checked in."},
                method="POST",
            )
            await snipeit_sync_service.push_checkout_create(
                journal_id=second,
                session_factory=lambda: _session_factory(async_connection),
            )
            checkout_reference = await _reference_data(
                async_connection, source="snipeit_checkout", journal_id=second
            )
            assert checkout_reference["snipeit_log_id"] == 100

    @pytest.mark.asyncio
    async def test_checkout_is_marked_posting_before_it_is_posted(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        journal_id = await _sydney_trip(async_connection)
        _queue_asset_dates(mock_transport)
        # No checkout response is queued, so the POST fails as if it were lost.
        with pytest.raises(ValueError, match="No mock response"):
            await snipeit_sync_service.push_checkout_create(
                journal_id=journal_id,
                session_factory=lambda: _session_factory(async_connection),
            )

        checkout_reference = await _reference_data(
            async_connection, source="snipeit_checkout", journal_id=journal_id
        )
        assert checkout_reference["posting"] is True

    @pytest.mark.asyncio
    async def test_reconcile_records_a_usage_linked_to_another_usages_entry(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """A title update repairs a usage that took the morning's entries (#1572)."""
        morning, afternoon = await _two_canyons(async_connection)
        for source in ("snipeit_checkout", "snipeit_checkin"):
            await _insert_recorded_sync_row(
                async_connection,
                source=source,
                journal_id=morning,
                reference_data={"checkout_at": "2024-10-26"},
            )
        await _link_afternoon_to(async_connection, afternoon)
        _queue_activity(mock_transport, "checkout", _MORNING_CHECKOUT)
        _queue_asset_assignee(mock_transport)
        _queue_activity(mock_transport, "checkout", _MORNING_CHECKOUT)
        _queue_activity(
            mock_transport,
            "checkout",
            _activity_row(102, "2024-10-26", time="12:43:00"),
            _MORNING_CHECKOUT,
        )
        _queue_checkout_and_checkin(mock_transport)

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=afternoon,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _posts(mock_transport) == [_CHECKOUT_POST, _CHECKIN_POST]
        assert len(mock_transport.responses) == 0
        assert await _sync_statuses(async_connection, afternoon) == {
            "snipeit_checkout": "success",
            "snipeit_checkin": "success",
        }
        checkout_reference = await _reference_data(
            async_connection, source="snipeit_checkout", journal_id=afternoon
        )
        assert checkout_reference["snipeit_log_id"] == 102

    @pytest.mark.asyncio
    async def test_reconcile_repair_waits_while_the_asset_is_out(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Snipe-IT would refuse the checkout, so the linked pair is kept for now."""
        _, afternoon = await _two_canyons(async_connection)
        await _link_afternoon_to(async_connection, afternoon)
        _queue_activity(mock_transport, "checkout", _MORNING_CHECKOUT)
        _queue_asset_assignee(mock_transport, _OUT_TO_SOMEONE)

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=afternoon,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _posts(mock_transport) == []
        assert await _sync_statuses(async_connection, afternoon) == {
            "snipeit_checkout": "success",
            "snipeit_checkin": "success",
        }
        assert (
            await _reference_data(
                async_connection, source="snipeit_checkout", journal_id=afternoon
            )
        )["snipeit_log_id"] == 100

    @pytest.mark.asyncio
    async def test_reconcile_keeps_a_link_to_an_entry_made_by_hand(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        _, afternoon = await _two_canyons(async_connection)
        await _link_afternoon_to(async_connection, afternoon)
        _queue_activity(mock_transport, "checkout", _activity_row(100, "2024-10-26"))

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=afternoon,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _posts(mock_transport) == []
        assert (
            await _reference_data(
                async_connection, source="snipeit_checkout", journal_id=afternoon
            )
        )["snipeit_log_id"] == 100

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("checkout_extra", "checkin_error"),
        [
            # The worker read the asset first, so it posted this checkout itself
            # and linked it only because the response was lost.
            (
                {
                    "asset_dates_before": {
                        "last_checkout": None,
                        "last_checkin": None,
                    }
                },
                None,
            ),
            # The asset may still be out, so no checkout can be recorded.
            (None, "Terminal: API 404"),
        ],
        ids=["posted-by-the-worker", "check-in-failed"],
    )
    async def test_reconcile_does_not_check_a_link_it_cannot_repair(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        checkout_extra: dict[str, Any] | None,
        checkin_error: str | None,
    ) -> None:
        _, afternoon = await _two_canyons(async_connection)
        await _link_afternoon_to(
            async_connection,
            afternoon,
            checkout_extra=checkout_extra,
            checkin_error=checkin_error,
        )

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=afternoon,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _posts(mock_transport) == []
        assert not _read_checkout_activity(mock_transport)


class TestInFlightCheckoutIntegration:
    """A journal event that meets another worker's checkout is retried, not dropped."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "operation", ["push_checkout_create", "reconcile_gear_usage"]
    )
    async def test_event_meeting_an_in_flight_checkout_is_retried(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        operation: str,
    ) -> None:
        """The in-flight worker may be sending older dates, so this event must retry."""
        from snipeit_sync_service import SnipeItSyncInProgress

        journal_id = await _sydney_trip(async_connection)
        await _insert_checkout_metadata(
            async_connection,
            asset_id="42",
            journal_id=journal_id,
            sync_status="pending",
        )

        factory = lambda: _session_factory(async_connection)  # noqa: E731
        with pytest.raises(SnipeItSyncInProgress):
            if operation == "push_checkin_create":
                await snipeit_sync_service.push_checkin_create(
                    GearUsagePair(journal_id, 42), session_factory=factory
                )
            else:
                await snipeit_sync_service.reconcile_gear_usage(
                    journal_id=journal_id, session_factory=factory
                )

        assert mock_transport.requests == []


class TestActivityClaimsIntegration:
    """Claims on Snipe-IT log entries are exclusive and never block recording."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("other_status", "claimed"),
        [("pending", None), ("success", None), ("failed", 100)],
        ids=["held-by-in-flight-journal", "held-by-synced-journal", "stale-failed"],
    )
    async def test_a_log_entry_is_claimed_by_one_journal(
        self,
        snipeit_sync_service: Any,
        async_connection: AsyncConnection,
        other_status: str,
        claimed: int | None,
    ) -> None:
        """A claim is written while the other journal is still in progress.

        Two journals processed at once each hold a pending row, so the claim
        must be visible before either finishes; a claim on a failed row is stale.
        """
        journal_id = await _sydney_trip(async_connection)
        other_journal_id = await _insert_gear_usage_journal(
            async_connection,
            start="2025-03-07T13:00:00+00:00",
            end="2025-03-08T13:00:00+00:00",
            asset_id="41",
        )
        await _insert_checkout_metadata(
            async_connection,
            asset_id="42",
            journal_id=journal_id,
            sync_status="pending",
        )
        await _insert_checkout_metadata(
            async_connection,
            asset_id="42",
            journal_id=other_journal_id,
            sync_status=other_status,
        )
        assert (
            await snipeit_sync_service._claim_activity_log(
                [100],
                source="snipeit_checkout",
                asset_id=42,
                journal_id=other_journal_id,
                external_id=f"snipeit_checkout:42:{other_journal_id}",
                session_factory=lambda: _session_factory(async_connection),
            )
            == 100
        )

        assert (
            await snipeit_sync_service._claim_activity_log(
                [100],
                source="snipeit_checkout",
                asset_id=42,
                journal_id=journal_id,
                external_id=f"snipeit_checkout:42:{journal_id}",
                session_factory=lambda: _session_factory(async_connection),
            )
            == claimed
        )

    @pytest.mark.asyncio
    async def test_a_claim_on_another_users_instance_does_not_block(
        self,
        snipeit_sync_service: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Snipe-IT log ids are only unique per instance, and each user has their own.

        Another user's journal linked to log 100 on their instance says nothing
        about log 100 on this user's instance.
        """
        journal_id = await _sydney_trip(async_connection)
        other_users_journal_id = _returned_id(
            await async_connection.execute(
                text("""
                    INSERT INTO journals (title, content, user_id,
                        event_date_range_start, event_date_range_end)
                    VALUES ('Their trip', '', 'user-456', '2025-03-08', '2025-03-09')
                    RETURNING id
                """)
            )
        )
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkout",
            journal_id=other_users_journal_id,
            reference_data={"snipeit_log_id": 100},
        )
        await _insert_checkout_metadata(
            async_connection,
            asset_id="42",
            journal_id=journal_id,
            sync_status="pending",
        )

        assert (
            await snipeit_sync_service._claim_activity_log(
                [100],
                source="snipeit_checkout",
                asset_id=42,
                journal_id=journal_id,
                external_id=f"snipeit_checkout:42:{journal_id}",
                session_factory=lambda: _session_factory(async_connection),
            )
            == 100
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status_code", "body"),
        [
            (403, {"status": "error", "messages": "Forbidden."}),
            (404, None),
            (200, {"status": "error", "messages": "Unauthorized."}),
            (200, b"<html>Service Unavailable</html>"),
        ],
        ids=["forbidden", "missing-endpoint", "unreadable-report", "non-json-report"],
    )
    async def test_unavailable_activity_report_does_not_block_the_checkout(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        status_code: int,
        body: dict[str, Any] | bytes | None,
    ) -> None:
        """Linking is best-effort: without the report, history is recorded as usual."""
        journal_id = await _sydney_trip(async_connection)
        mock_transport.add_response(
            "action_type=checkout", status_code=status_code, json_data=body
        )
        _queue_checkout_and_checkin(mock_transport)

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert _posts(mock_transport) == [_CHECKOUT_POST, _CHECKIN_POST]


class TestSupersededAssetRetryIntegration:
    """A failed return of a removed item's asset is retried against that asset."""

    @pytest.mark.asyncio
    async def test_failed_return_keeps_the_abandoned_pairs_row(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """The pair must not be forgotten until its asset is returned.

        Forgetting it first would leave the next retry nothing to return the old
        asset from.
        """
        from snipeit_api_client import SnipeItAPIError

        journal_id = await _insert_gear_usage_journal(
            async_connection,
            start="2025-03-07T13:00:00+00:00",
            end="2025-03-08T13:00:00+00:00",
            asset_id="42",
        )
        await _insert_checkout_metadata(
            async_connection, asset_id="41", journal_id=journal_id, sync_status="failed"
        )
        mock_transport.add_response(
            "/hardware/41",
            json_data={
                "id": 41,
                "asset_tag": "T-41",
                "assigned_to": {"id": 5, "name": "Harry", "type": "user"},
            },
            method="GET",
        )
        mock_transport.add_response(
            "/hardware/41/checkin", status_code=500, json_data={"status": "error"}
        )

        with pytest.raises(SnipeItAPIError):
            await snipeit_sync_service.reconcile_gear_usage(
                journal_id=journal_id,
                session_factory=lambda: _session_factory(async_connection),
            )

        result = await async_connection.execute(
            text("""
                SELECT external_id, sync_status FROM sync_metadata
                WHERE integration_source = 'snipeit_checkout'
                  AND internal_uuid = :journal_id
            """),
            {"journal_id": str(journal_id)},
        )
        row = result.fetchone()
        assert row is not None
        assert (row.external_id, row.sync_status) == (
            f"snipeit_checkout:41:{journal_id}",
            "failed",
        )
        assert not any(
            r.url.path.endswith("/hardware/42/checkout")
            for r in mock_transport.requests
        )


class TestInFlightCheckinIntegration:
    """An event that meets another worker's check-in is retried, not acknowledged."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "operation", ["push_checkin_create", "reconcile_gear_usage"]
    )
    async def test_event_meeting_an_in_flight_checkin_is_retried(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        operation: str,
    ) -> None:
        """A changed checkout date must still be re-recorded once the check-in lands.

        Acknowledging the event while the older check-in is in flight would leave
        nothing to supersede that check-in afterwards.
        """
        from snipeit_sync_service import SnipeItSyncInProgress

        journal_id = await _sydney_trip(async_connection)
        # The recorded checkout date differs from the journal's (8 March).
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkout",
            journal_id=journal_id,
            reference_data={
                "checkout_at": "2025-03-01",
                "expected_checkin": "2025-03-02",
            },
        )
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (integration_source, external_id, internal_uuid,
                     last_synced_at, version_hash, sync_status,
                     error_message, retry_count, created_at, updated_at)
                VALUES
                    ('snipeit_checkin', :external_id, :journal_id,
                     now(), 'PENDING', 'pending', NULL, 0, now(), now())
            """),
            {
                "external_id": f"snipeit_checkin:42:{journal_id}",
                "journal_id": str(journal_id),
            },
        )

        factory = lambda: _session_factory(async_connection)  # noqa: E731
        with pytest.raises(SnipeItSyncInProgress):
            if operation == "push_checkin_create":
                await snipeit_sync_service.push_checkin_create(
                    GearUsagePair(journal_id, 42), session_factory=factory
                )
            else:
                await snipeit_sync_service.reconcile_gear_usage(
                    journal_id=journal_id, session_factory=factory
                )

        assert mock_transport.requests == []


class TestLateCheckinRerecordIntegration:
    """A check-in that lands for an outdated checkout date is followed by a new pair."""

    @pytest.mark.asyncio
    async def test_retried_checkin_rerecords_a_changed_checkout_date(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """The update that finally checks the asset in must also record the new dates.

        Acknowledging it after the check-in alone would leave no event to replace
        the checkout still recorded on the old date.
        """
        journal_id = await _sydney_trip(async_connection)
        await _insert_recorded_sync_row(
            async_connection,
            source="snipeit_checkout",
            journal_id=journal_id,
            reference_data={
                "checkout_at": "2025-03-01",
                "expected_checkin": "2025-03-02",
            },
        )
        # An earlier check-in attempt failed with a retryable error.
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (integration_source, external_id, internal_uuid,
                     last_synced_at, version_hash, sync_status,
                     error_message, retry_count, created_at, updated_at)
                VALUES
                    ('snipeit_checkin', :external_id, :journal_id,
                     now(), 'PENDING', 'failed', 'Snipe-IT API error: 502', 0,
                     now(), now())
            """),
            {
                "external_id": f"snipeit_checkin:42:{journal_id}",
                "journal_id": str(journal_id),
            },
        )
        for path in (
            "/hardware/42/checkin",
            "/hardware/42/checkout",
            "/hardware/42/checkin",
        ):
            mock_transport.add_response(
                path, json_data={"status": "success", "messages": "Done."}
            )
        _queue_asset_dates(mock_transport)
        _queue_asset_dates(mock_transport)
        _queue_asset_assignee(mock_transport)

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert [r.url.path for r in mock_transport.requests if r.method == "POST"] == [
            "/api/v1/hardware/42/checkin",
            "/api/v1/hardware/42/checkout",
            "/api/v1/hardware/42/checkin",
        ]
        assert await _reference_data(
            async_connection, source="snipeit_checkout", journal_id=journal_id
        ) == {
            "checkout_at": "2025-03-08",
            "expected_checkin": "2025-03-09",
            "asset_dates_before": {"last_checkout": None, "last_checkin": None},
        }
        assert await _reference_data(
            async_connection, source="snipeit_checkin", journal_id=journal_id
        ) == {"checkin_at": "2025-03-09"}


class TestPreviousAssetHeldElsewhereIntegration:
    """A removed item's asset is only returned when no other pair may be using it."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("other_checkout_status", "other_checkin_status", "posts"),
        [
            # A pending or failed attempt may have checked the asset out anyway.
            (
                "pending",
                "failed",
                ["/api/v1/hardware/42/checkout", "/api/v1/hardware/42/checkin"],
            ),
            (
                "failed",
                "failed",
                ["/api/v1/hardware/42/checkout", "/api/v1/hardware/42/checkin"],
            ),
            # Checked out and not yet returned.
            (
                "success",
                "failed",
                ["/api/v1/hardware/42/checkout", "/api/v1/hardware/42/checkin"],
            ),
            # The other journal already returned it, so the lost attempt holds it.
            (
                "success",
                "success",
                [
                    "/api/v1/hardware/41/checkin",
                    "/api/v1/hardware/42/checkout",
                    "/api/v1/hardware/42/checkin",
                ],
            ),
        ],
        ids=["other-pending", "other-failed", "other-still-out", "other-returned"],
    )
    async def test_previous_asset_is_left_while_another_journal_may_hold_it(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        other_checkout_status: str,
        other_checkin_status: str,
        posts: list[str],
    ) -> None:
        """Returning an asset another journal is still using would be worse than
        leaving it out for that journal's own retry or the periodic sweep."""
        journal_id = await _insert_gear_usage_journal(
            async_connection,
            start="2025-03-07T13:00:00+00:00",
            end="2025-03-08T13:00:00+00:00",
            asset_id="42",
        )
        await _insert_checkout_metadata(
            async_connection, asset_id="41", journal_id=journal_id, sync_status="failed"
        )
        other_journal_id = 880001
        await _insert_checkout_metadata(
            async_connection,
            asset_id="41",
            journal_id=other_journal_id,
            sync_status=other_checkout_status,
        )
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (integration_source, external_id, internal_uuid,
                     last_synced_at, version_hash, sync_status,
                     error_message, retry_count, created_at, updated_at)
                VALUES
                    ('snipeit_checkin', :external_id, :journal_id,
                     now(), 'CHECKED_IN', :sync_status, NULL, 0, now(), now())
            """),
            {
                "external_id": f"snipeit_checkin:41:{other_journal_id}",
                "journal_id": str(other_journal_id),
                "sync_status": other_checkin_status,
            },
        )
        mock_transport.add_response(
            "/hardware/41",
            json_data={
                "id": 41,
                "asset_tag": "T-41",
                "assigned_to": {"id": 5, "name": "Harry", "type": "user"},
            },
            method="GET",
        )
        # Consumed only when the old asset is returned.
        mock_transport.add_response(
            "/hardware/41/checkin",
            json_data={"status": "success", "messages": "Checked in."},
        )
        _queue_checkout_and_checkin(mock_transport)

        await snipeit_sync_service.reconcile_gear_usage(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert [
            r.url.path for r in mock_transport.requests if r.method == "POST"
        ] == posts
        # The abandoned pair is forgotten only once its asset was dealt with:
        # left out for another pair, its row stays so a later sync retries it.
        abandoned = await async_connection.execute(
            text("""
                SELECT 1 FROM sync_metadata
                WHERE integration_source = 'snipeit_checkout'
                  AND external_id = :external_id
            """),
            {"external_id": f"snipeit_checkout:41:{journal_id}"},
        )
        assert (abandoned.fetchone() is None) == (
            "/api/v1/hardware/41/checkin" in posts
        )
