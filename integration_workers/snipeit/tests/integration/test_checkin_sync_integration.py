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
            INSERT INTO journal_gear_usage_data
                (journal_id, gear_item_id, checkout_date, checkin_date)
            VALUES (:journal_id, :gear_item_id, NULL, NULL)
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


def _request_body(mock_transport: Any, path: str) -> dict[str, Any]:
    """Return the JSON body of the single request whose URL contains ``path``."""
    (request,) = [r for r in mock_transport.requests if path in str(r.url)]
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


def _queue_checkout_and_checkin(mock_transport: Any, asset_id: str = "42") -> None:
    mock_transport.add_response(
        f"/hardware/{asset_id}/checkout",
        json_data={"status": "success", "messages": "Checked out."},
    )
    mock_transport.add_response(
        f"/hardware/{asset_id}/checkin",
        json_data={"status": "success", "messages": "Checked in."},
    )


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
        assert checkout_body["checkout_at"] == checkout_at
        assert checkout_body["expected_checkin"] == checkin_at
        checkin_body = _request_body(mock_transport, "hardware/42/checkin")
        assert checkin_body == {
            "checkin_at": checkin_at,
            "note": f"Usage period {checkout_at} to {checkin_at}",
        }
        assert await _reference_data(
            async_connection, source="snipeit_checkout", journal_id=journal_id
        ) == {"checkout_at": checkout_at, "expected_checkin": checkin_at}
        assert await _reference_data(
            async_connection, source="snipeit_checkin", journal_id=journal_id
        ) == {"checkin_at": checkin_at}

    @pytest.mark.asyncio
    async def test_event_timezone_takes_precedence_over_user_timezone(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        # 23:30 UTC is still the same day in London but the next day in Sydney.
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
        assert checkout_body["checkout_at"] == "2025-03-07"
        assert checkout_body["expected_checkin"] == "2025-03-08"
        checkin_body = _request_body(mock_transport, "hardware/42/checkin")
        assert checkin_body["checkin_at"] == "2025-03-08"

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
    async def test_retried_checkout_follows_a_changed_gear_item(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        previous_assignee: dict[str, Any] | None,
        posts: list[str],
    ) -> None:
        """A failed checkout recorded against the old asset is retried on the new one.

        The failure may have been a lost response after Snipe-IT checked the old
        asset out, so the old asset is returned before it loses its association.
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
        )
        # Consumed only when the old asset is returned.
        mock_transport.add_response(
            "/hardware/41/checkin",
            json_data={"status": "success", "messages": "Checked in."},
        )
        _queue_checkout_and_checkin(mock_transport)

        await snipeit_sync_service.push_checkout_create(
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
            journal_id=journal_id,
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
            journal_id=deleted_journal_id,
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
            journal_id=555,
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
            journal_id=journal_id,
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

        mock_transport.add_response(
            "/hardware/42/checkout",
            json_data={"status": "success", "messages": "Checked out."},
        )
        mock_transport.add_response(
            "/hardware/42/checkin",
            json_data={"status": "success", "messages": "Checked in."},
        )

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
        from snipeit_sync_service import OverdueGearUsage, fetch_overdue_gear_usage

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
                "external_id": f"snipeit_checkin:{done_id}:{done_id}",
                "journal_id": str(done_id),
            },
        )

        overdue = await fetch_overdue_gear_usage(
            lambda: _session_factory(async_connection), "user-123"
        )

        assert overdue == [
            OverdueGearUsage(
                journal_id=overdue_id,
                checkout_at=date(2025, 3, 8),
                checkin_at=date(2025, 3, 9),
            )
        ]


class TestSupersededAssetRetryIntegration:
    """A failed return of the previous asset is retried against that asset."""

    @pytest.mark.asyncio
    async def test_failed_return_keeps_the_row_on_the_previous_asset(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """The row must not forget the old asset until that asset is returned.

        Re-keying it first would make the next retry derive the new asset and
        never return the old one.
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
        )
        mock_transport.add_response(
            "/hardware/41/checkin", status_code=500, json_data={"status": "error"}
        )

        with pytest.raises(SnipeItAPIError):
            await snipeit_sync_service.push_checkout_create(
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


class TestPreviousAssetHeldElsewhereIntegration:
    """A superseded asset is only returned when no other journal may be using it."""

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
        )
        # Consumed only when the old asset is returned.
        mock_transport.add_response(
            "/hardware/41/checkin",
            json_data={"status": "success", "messages": "Checked in."},
        )
        _queue_checkout_and_checkin(mock_transport)

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=lambda: _session_factory(async_connection),
        )

        assert [
            r.url.path for r in mock_transport.requests if r.method == "POST"
        ] == posts
