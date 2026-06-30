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
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

# ``MockTransport``, ``mock_transport``, ``integration_client`` and
# ``snipeit_sync_service`` are shared fixtures defined in ``conftest.py``.


async def _insert_checkout_metadata(
    async_connection: AsyncConnection, *, asset_id: str, journal_id: int
) -> None:
    """Insert a successful ``snipeit_checkout`` sync_metadata row."""
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata
                (integration_source, external_id, internal_uuid,
                 last_synced_at, version_hash, sync_status,
                 error_message, retry_count, created_at, updated_at)
            VALUES
                ('snipeit_checkout', :external_id, :journal_id,
                 now(), 'hash', 'success', NULL, 0, now(), now())
        """),
        {
            "external_id": f"snipeit_checkout:{asset_id}:{journal_id}",
            "journal_id": str(journal_id),
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
        gear_result = await async_connection.execute(
            text("""
                INSERT INTO gear_items (name, user_id)
                VALUES ('Tent', 'user-123')
                RETURNING id
            """)
        )
        gear_row = gear_result.fetchone()
        assert gear_row is not None
        gear_item_id = str(gear_row.id)

        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (integration_source, external_id, internal_uuid,
                     last_synced_at, version_hash, sync_status,
                     error_message, retry_count, created_at, updated_at)
                VALUES
                    ('snipeit', '42', :gear_item_id,
                     now(), 'hash', 'success', NULL, 0, now(), now())
            """),
            {"gear_item_id": gear_item_id},
        )

        journal_result = await async_connection.execute(
            text("""
                INSERT INTO journals (title, content, user_id,
                    event_date_range_start, event_date_range_end)
                VALUES ('Past trip', '', 'user-123', '2000-01-01', '2000-01-02')
                RETURNING id
            """)
        )
        journal_row = journal_result.fetchone()
        assert journal_row is not None
        journal_id = journal_row.id

        await async_connection.execute(
            text("""
                INSERT INTO journal_gear_usage_data
                    (journal_id, gear_item_id, checkout_date, checkin_date)
                VALUES (:journal_id, :gear_item_id, NULL, NULL)
            """),
            {"journal_id": journal_id, "gear_item_id": gear_item_id},
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
    async def test_periodic_sweep_query_selects_overdue_checkouts(
        self,
        async_connection: AsyncConnection,
    ) -> None:
        """The periodic sweep query selects only past, not-yet-checked-in usages.

        Validates the SQL shape used by
        ``periodic_checkin_all_snipeit_accounts`` against real Postgres.
        """
        # Overdue, no checkin → selected.
        overdue = await async_connection.execute(
            text("""
                INSERT INTO journals (title, content, user_id,
                    event_date_range_start, event_date_range_end)
                VALUES ('Overdue', '', 'user-123', '2024-01-01', '2024-01-02')
                RETURNING id
            """)
        )
        overdue_id = _returned_id(overdue)

        # Future window → excluded.
        future = await async_connection.execute(
            text("""
                INSERT INTO journals (title, content, user_id,
                    event_date_range_start, event_date_range_end)
                VALUES ('Future', '', 'user-123', '2099-01-01', '2099-01-02')
                RETURNING id
            """)
        )
        future_id = _returned_id(future)

        # Overdue but already checked in → excluded.
        done = await async_connection.execute(
            text("""
                INSERT INTO journals (title, content, user_id,
                    event_date_range_start, event_date_range_end)
                VALUES ('Done', '', 'user-123', '2024-01-01', '2024-01-02')
                RETURNING id
            """)
        )
        done_id = _returned_id(done)

        gear_ids: dict[int, str] = {}
        for jid in (overdue_id, future_id, done_id):
            gear = await async_connection.execute(
                text("""
                    INSERT INTO gear_items (name, user_id)
                    VALUES ('Item', 'user-123') RETURNING id
                """)
            )
            gear_id = str(_returned_id(gear))
            gear_ids[jid] = gear_id
            await async_connection.execute(
                text("""
                    INSERT INTO journal_gear_usage_data
                        (journal_id, gear_item_id, checkout_date, checkin_date)
                    VALUES (:journal_id, :gear_item_id, NULL, NULL)
                """),
                {"journal_id": jid, "gear_item_id": gear_id},
            )
            await _insert_checkout_metadata(
                async_connection, asset_id=str(jid), journal_id=jid
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

        result = await async_connection.execute(
            text("""
                SELECT j.id AS journal_id
                FROM sync_metadata co
                JOIN journals j ON j.id = co.internal_uuid::integer
                JOIN journal_gear_usage_data u ON u.journal_id = j.id
                LEFT JOIN sync_metadata ci
                    ON ci.integration_source = 'snipeit_checkin'
                    AND ci.internal_uuid = co.internal_uuid
                    AND ci.sync_status = 'success'
                WHERE co.integration_source = 'snipeit_checkout'
                  AND co.sync_status = 'success'
                  AND j.user_id = :user_id
                  AND ci.id IS NULL
                  AND COALESCE(u.checkin_date, j.event_date_range_end) < now()
            """),
            {"user_id": "user-123"},
        )
        selected = {row.journal_id for row in result.fetchall()}

        assert overdue_id in selected
        assert future_id not in selected
        assert done_id not in selected
