"""
Integration tests for Snipe-IT checkout sync.

Verifies that GEAR_USAGE journal entries trigger an asset checkout
POST to the Snipe-IT API and persist correct sync_metadata.
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


class TestCheckoutSyncIntegration:
    """Integration tests for Snipe-IT checkout sync pipeline."""

    @pytest.mark.asyncio
    async def test_push_checkout_create_posts_to_snipeit(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Verify push_checkout_create POSTs checkout and saves sync_metadata.

        Steps:
        1. Create gear item, journal, usage data, asset sync_metadata.
        2. Mock the Snipe-IT POST /hardware/{id}/checkout response.
        3. Run push_checkout_create.
        4. Assert POST was made with correct payload.
        5. Assert sync_metadata was created for the checkout.
        """
        # Step 1: Insert gear item
        gear_item_result = await async_connection.execute(
            text("""
                INSERT INTO gear_items (name, user_id)
                VALUES ('Climbing Rope 60m', 'user-123')
                RETURNING id
            """)
        )
        gear_item_row = gear_item_result.fetchone()
        assert gear_item_row is not None
        gear_item_id = str(gear_item_row.id)

        # Asset sync_metadata
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (integration_source, external_id, internal_uuid,
                     last_synced_at, version_hash, sync_status,
                     error_message, retry_count, created_at, updated_at)
                VALUES
                    ('snipeit', '42', :gear_item_id,
                     now(), 'test-hash', 'success',
                     NULL, 0, now(), now())
            """),
            {"gear_item_id": gear_item_id},
        )

        # Insert journal with date range
        journal_result = await async_connection.execute(
            text("""
                INSERT INTO journals (title, content, user_id,
                    event_date_range_start, event_date_range_end)
                VALUES ('Rope usage at crag', 'Used climbing rope', 'user-123',
                    '2099-06-01', '2099-06-02')
                RETURNING id
            """)
        )
        journal_row = journal_result.fetchone()
        assert journal_row is not None
        journal_id = journal_row.id

        # Journal gear usage data with buffer dates (future, so no immediate checkin)
        await async_connection.execute(
            text("""
                INSERT INTO journal_gear_usage_data
                    (journal_id, gear_item_id, checkout_date, checkin_date)
                VALUES (:journal_id, :gear_item_id,
                    '2099-06-01 08:00:00+00', '2099-06-02 18:00:00+00')
            """),
            {"journal_id": journal_id, "gear_item_id": gear_item_id},
        )

        # Step 2: Mock Snipe-IT checkout POST response
        mock_transport.add_response(
            "/hardware/42/checkout",
            json_data={
                "status": "success",
                "messages": "Asset checked out successfully.",
                "payload": {"id": 42, "name": "Climbing Rope 60m"},
            },
        )

        # Step 3: Build session factory joined to test transaction
        @asynccontextmanager
        async def mock_session_factory() -> Any:
            async with AsyncSession(
                async_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=mock_session_factory,
        )

        # Step 4: All mock responses consumed (POST was made)
        assert len(mock_transport.responses) == 0

        # Verify request payload
        # The activity-report lookup also mentions "checkout"; take the POST.
        checkout_request = next(
            r for r in mock_transport.requests if r.url.path.endswith("/checkout")
        )
        request_body = json.loads(checkout_request.content)
        assert request_body["assigned_user"] == "5"
        assert request_body["checkout_to_type"] == "user"
        assert request_body["checkout_at"] == "2099-06-01 08:00:00"
        assert request_body["expected_checkin"] == "2099-06-02"
        assert request_body["note"] == "Rope usage at crag"

        # Step 5: Verify sync_metadata was created
        meta_result = await async_connection.execute(
            text("""
                SELECT internal_uuid, sync_status, version_hash
                FROM sync_metadata
                WHERE integration_source = 'snipeit_checkout'
                  AND external_id = :external_id
            """),
            {"external_id": f"snipeit_checkout:42:{journal_id}"},
        )
        meta_row = meta_result.fetchone()
        assert meta_row is not None
        assert meta_row.internal_uuid == str(journal_id)
        assert meta_row.sync_status == "success"
        assert meta_row.version_hash is not None

    @pytest.mark.asyncio
    async def test_push_checkout_create_idempotent(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Verify push_checkout_create skips when checkout is already synced.

        Steps:
        1. Create prerequisite data + existing sync_metadata for checkout.
        2. Run push_checkout_create (should skip without calling API).
        """
        # Step 1: Insert gear item
        gear_item_result = await async_connection.execute(
            text("""
                INSERT INTO gear_items (name, user_id)
                VALUES ('Test Harness', 'user-123')
                RETURNING id
            """)
        )
        gear_item_row = gear_item_result.fetchone()
        assert gear_item_row is not None
        gear_item_id = str(gear_item_row.id)

        # Asset sync_metadata
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (integration_source, external_id, internal_uuid,
                     last_synced_at, version_hash, sync_status,
                     error_message, retry_count, created_at, updated_at)
                VALUES
                    ('snipeit', '55', :gear_item_id,
                     now(), 'test-hash', 'success',
                     NULL, 0, now(), now())
            """),
            {"gear_item_id": gear_item_id},
        )

        # Insert journal
        journal_result = await async_connection.execute(
            text("""
                INSERT INTO journals (title, content, user_id,
                    event_date_range_start, event_date_range_end)
                VALUES ('Existing Usage', 'Already synced', 'user-123',
                    '2024-06-01', '2024-06-02')
                RETURNING id
            """)
        )
        journal_row = journal_result.fetchone()
        assert journal_row is not None
        journal_id = journal_row.id

        # Gear usage data
        await async_connection.execute(
            text("""
                INSERT INTO journal_gear_usage_data
                    (journal_id, gear_item_id, checkout_date, checkin_date)
                VALUES (:journal_id, :gear_item_id, NULL, NULL)
            """),
            {"journal_id": journal_id, "gear_item_id": gear_item_id},
        )

        # Pre-existing checkout sync_metadata (already synced)
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (integration_source, external_id, internal_uuid,
                     last_synced_at, version_hash, sync_status,
                     error_message, retry_count, created_at, updated_at)
                VALUES
                    ('snipeit_checkout', :external_id, :journal_id,
                     now(), 'existing-hash', 'success',
                     NULL, 0, now(), now())
            """),
            {
                "external_id": f"snipeit_checkout:55:{journal_id}",
                "journal_id": str(journal_id),
            },
        )

        # Step 2: Build session factory
        @asynccontextmanager
        async def mock_session_factory() -> Any:
            async with AsyncSession(
                async_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=mock_session_factory,
        )

        # No API call should have been made (no responses were added)
        assert len(mock_transport.requests) == 0

    @pytest.mark.asyncio
    async def test_push_checkout_falls_back_to_journal_dates(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Verify checkout uses journal date range when buffer dates are null.

        Steps:
        1. Create data with NULL checkout_date/checkin_date.
        2. Run push_checkout_create.
        3. Assert payload uses journal event_date_range_start/end.
        """
        # Step 1: Insert gear item
        gear_item_result = await async_connection.execute(
            text("""
                INSERT INTO gear_items (name, user_id)
                VALUES ('Ice Axe', 'user-123')
                RETURNING id
            """)
        )
        gear_item_row = gear_item_result.fetchone()
        assert gear_item_row is not None
        gear_item_id = str(gear_item_row.id)

        # Asset sync_metadata
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (integration_source, external_id, internal_uuid,
                     last_synced_at, version_hash, sync_status,
                     error_message, retry_count, created_at, updated_at)
                VALUES
                    ('snipeit', '99', :gear_item_id,
                     now(), 'test-hash', 'success',
                     NULL, 0, now(), now())
            """),
            {"gear_item_id": gear_item_id},
        )

        # Insert journal
        journal_result = await async_connection.execute(
            text("""
                INSERT INTO journals (title, content, user_id,
                    event_date_range_start, event_date_range_end)
                VALUES ('Ice Axe usage', '', 'user-123',
                    '2099-07-10', '2099-07-12')
                RETURNING id
            """)
        )
        journal_row = journal_result.fetchone()
        assert journal_row is not None
        journal_id = journal_row.id

        # Gear usage data with NULL buffer dates
        await async_connection.execute(
            text("""
                INSERT INTO journal_gear_usage_data
                    (journal_id, gear_item_id, checkout_date, checkin_date)
                VALUES (:journal_id, :gear_item_id, NULL, NULL)
            """),
            {"journal_id": journal_id, "gear_item_id": gear_item_id},
        )

        # Step 2: Mock Snipe-IT checkout POST response
        mock_transport.add_response(
            "/hardware/99/checkout",
            json_data={
                "status": "success",
                "messages": "Asset checked out successfully.",
            },
        )

        @asynccontextmanager
        async def mock_session_factory() -> Any:
            async with AsyncSession(
                async_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session

        await snipeit_sync_service.push_checkout_create(
            journal_id=journal_id,
            session_factory=mock_session_factory,
        )

        # Step 3: Verify dates fell back to journal range
        # The activity-report lookup also mentions "checkout"; take the POST.
        checkout_request = next(
            r for r in mock_transport.requests if r.url.path.endswith("/checkout")
        )
        request_body = json.loads(checkout_request.content)
        assert request_body["checkout_at"] == "2099-07-10 00:00:00"
        assert request_body["expected_checkin"] == "2099-07-12"
