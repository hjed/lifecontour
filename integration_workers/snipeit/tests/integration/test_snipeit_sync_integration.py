"""
Integration tests for SnipeItSyncService.

Verifies that assets fetched from the Snipe-IT API are correctly
upserted into the `gear_items` table and their state is tracked
in `sync_metadata`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from snipeit_api_client import SnipeItAPIClient
from snipeit_sync_service import SnipeItSyncService
from snipeit_sync_window import ListedRecord

# ``MockTransport``, ``mock_transport`` and ``integration_client`` are shared
# fixtures defined in ``conftest.py``.


@pytest.fixture
def sync_service(integration_client: SnipeItAPIClient) -> SnipeItSyncService:
    return SnipeItSyncService(
        api_client=integration_client,
        user_id="user-123",
    )


class TestSnipeItSyncIntegration:
    @pytest.mark.asyncio
    async def test_sync_asset_batch_inserts_gear_item(
        self,
        sync_service: SnipeItSyncService,
        mock_transport: Any,
        db_session: AsyncSession,
        async_engine: Any,
    ) -> None:
        """Verify that a successful asset sync upserts gear_items and sync_metadata."""

        # Setup API mock response
        asset_id = 999
        mock_transport.add_response(
            f"/hardware/{asset_id}",
            json_data={
                "id": asset_id,
                "name": "Climbing Rope 60m",
                "asset_tag": "ROPE-001",
                "serial": "SN-98765",
                "model_number": "MR-60",
                "model": {"id": 10, "name": "Dynamic 9.8mm"},
                "manufacturer": {"id": 5, "name": "Petzl"},
                "purchase_date": {"date": "2024-01-15", "formatted": "2024-01-15"},
                "category": {"id": 2, "name": "Climbing Gear"},
            },
        )

        # We need a session_factory for the sync service
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_session_factory():
            # Use the provided db_session which already has savepoints configured
            yield db_session

        # Run sync batch
        result = await sync_service.sync_asset_batch(
            asset_ids=[asset_id],
            session_factory=mock_session_factory,
        )

        assert result["synced"] == 1
        assert result["failed"] == 0

        # Verify gear_items row
        gear_result = await db_session.execute(
            text(
                "SELECT id, name, serial_number, manufacturer, purchase_date FROM gear_items WHERE user_id = 'user-123'"
            )
        )
        gear_row = gear_result.fetchone()
        assert gear_row is not None
        assert gear_row.name == "Climbing Rope 60m"
        assert gear_row.serial_number == "SN-98765"
        assert gear_row.manufacturer == "Petzl"
        assert str(gear_row.purchase_date) == "2024-01-15"

        gear_id = str(gear_row.id)

        # Verify sync_metadata row
        meta_result = await db_session.execute(
            text(
                "SELECT user_id, internal_uuid, version_hash, sync_status FROM sync_metadata WHERE integration_source = 'snipeit' AND external_id = '999'"
            )
        )
        meta_row = meta_result.fetchone()
        assert meta_row is not None
        assert meta_row.user_id == "user-123"
        assert meta_row.internal_uuid == gear_id
        assert meta_row.sync_status == "success"
        assert meta_row.version_hash is not None


def _asset_json(
    asset_id: int, name: str, status: str = "Ready to Deploy"
) -> dict[str, Any]:
    return {
        "id": asset_id,
        "name": name,
        "asset_tag": f"{asset_id:05d}",
        "status_label": {"id": 4 if status == "Retired" else 2, "name": status},
    }


def _listing(*assets: dict[str, Any]) -> dict[str, Any]:
    return {"total": len(assets), "rows": list(assets)}


def _listing_statuses(mock_transport: Any) -> list[list[str] | None]:
    """The ``status`` filter of each ``GET /hardware`` listing, in call order."""
    statuses: list[list[str] | None] = []
    for request in mock_transport.requests:
        url = urlparse(str(request.url))
        if url.path.endswith("/hardware"):
            statuses.append(parse_qs(url.query).get("status"))
    return statuses


def _queue_listings(
    mock_transport: Any, default: dict[str, Any], archived: dict[str, Any]
) -> None:
    """Queue the default then the archived listing.

    The default listing is queued first: its pattern is also a substring of
    the archived listing's URL, and the transport serves the first match.
    """
    mock_transport.add_response("/hardware?", json_data=default, method="GET")
    mock_transport.add_response(
        "/hardware?offset=0&limit=50&status=Archived",
        json_data=archived,
        method="GET",
    )


async def _collect_records(
    sync_service: SnipeItSyncService,
) -> list[list[ListedRecord]]:
    return [page async for page in sync_service.list_asset_batches()]


async def _collect(sync_service: SnipeItSyncService) -> list[list[int]]:
    return [
        [record.id for record in page] for page in await _collect_records(sync_service)
    ]


@pytest.fixture
def session_factory(async_connection: AsyncConnection) -> Any:
    """A worker-style session factory bound to the rolled-back test connection."""

    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            async_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

    return _factory


async def _gear_rows_for(conn: AsyncConnection, external_id: str) -> list[Any]:
    """The gear items linked to a Snipe-IT asset through ``sync_metadata``."""
    result = await conn.execute(
        text("""
            SELECT g.id, g.name
            FROM sync_metadata m
            JOIN gear_items g ON g.id::text = m.internal_uuid
            WHERE m.integration_source = 'snipeit' AND m.external_id = :external_id
        """),
        {"external_id": external_id},
    )
    return list(result.fetchall())


class TestSnipeItListingTimestamps:
    """Listings carry each record's ``updated_at``, so a smart sync can fetch
    only the records changed since its last run (#1560)."""

    @pytest.mark.asyncio
    async def test_asset_listing_carries_updated_at(
        self, sync_service: SnipeItSyncService, mock_transport: Any
    ) -> None:
        changed = {
            **_asset_json(1, "Rope"),
            "updated_at": {"datetime": "2026-10-07 09:30:05", "formatted": "x"},
        }
        _queue_listings(
            mock_transport,
            default=_listing(changed, _asset_json(2, "Harness")),
            archived=_listing(),
        )

        pages = await _collect_records(sync_service)

        assert pages == [
            [
                ListedRecord(1, datetime(2026, 10, 7, 9, 30, 5)),
                ListedRecord(2, None),
            ]
        ]

    @pytest.mark.asyncio
    async def test_maintenance_listing_carries_updated_at_and_asset(
        self, sync_service: SnipeItSyncService, mock_transport: Any
    ) -> None:
        mock_transport.add_response(
            "/maintenances?",
            json_data={
                "total": 2,
                "rows": [
                    {
                        "id": 7,
                        "asset": {"id": 51, "name": "Rope"},
                        "updated_at": {
                            "datetime": "2026-10-07 09:30:05",
                            "formatted": "x",
                        },
                    },
                    {"id": 8, "updated_at": None},
                ],
            },
            method="GET",
        )

        pages = [page async for page in sync_service.list_maintenance_batches()]

        assert pages == [
            [
                ListedRecord(7, datetime(2026, 10, 7, 9, 30, 5), asset_id=51),
                ListedRecord(8, None),
            ]
        ]


class TestSnipeItArchivedAssetListing:
    """Snipe-IT leaves archived (e.g. Retired) assets out of its default
    hardware listing, so the asset sync lists them separately (#1570)."""

    @pytest.mark.asyncio
    async def test_lists_archived_assets_after_the_default_listing(
        self, sync_service: SnipeItSyncService, mock_transport: Any
    ) -> None:
        _queue_listings(
            mock_transport,
            default=_listing(_asset_json(1, "Rope")),
            archived=_listing(_asset_json(18, "CE4Y Harness 1", "Retired")),
        )

        batches = await _collect(sync_service)

        assert batches == [[1], [18]]
        assert _listing_statuses(mock_transport) == [None, ["Archived"]]

    @pytest.mark.asyncio
    async def test_asset_in_both_listings_is_listed_once(
        self, sync_service: SnipeItSyncService, mock_transport: Any
    ) -> None:
        """An instance that shows archived assets in its default listing
        returns them from both listings."""
        retired = _asset_json(18, "CE4Y Harness 1", "Retired")
        _queue_listings(
            mock_transport,
            default=_listing(_asset_json(1, "Rope"), retired),
            archived=_listing(retired),
        )

        batches = await _collect(sync_service)

        assert batches == [[1, 18]]

    @pytest.mark.asyncio
    async def test_full_sync_creates_gear_item_for_archived_asset(
        self,
        sync_service: SnipeItSyncService,
        mock_transport: Any,
        async_connection: AsyncConnection,
        session_factory: Any,
    ) -> None:
        retired = _asset_json(18, "CE4Y Harness 1", "Retired")
        _queue_listings(mock_transport, default=_listing(), archived=_listing(retired))
        mock_transport.add_response("/hardware/18", json_data=retired, method="GET")

        for batch in await _collect(sync_service):
            result = await sync_service.sync_asset_batch(batch, session_factory)
            assert result["synced"] == len(batch)

        rows = await _gear_rows_for(async_connection, "18")
        assert [row.name for row in rows] == ["CE4Y Harness 1"]

    @pytest.mark.asyncio
    async def test_asset_retired_after_sync_keeps_its_gear_item(
        self,
        sync_service: SnipeItSyncService,
        mock_transport: Any,
        async_connection: AsyncConnection,
        session_factory: Any,
    ) -> None:
        deployable = _asset_json(18, "CE4Y Harness 1")
        _queue_listings(
            mock_transport, default=_listing(deployable), archived=_listing()
        )
        mock_transport.add_response("/hardware/18", json_data=deployable, method="GET")
        for batch in await _collect(sync_service):
            await sync_service.sync_asset_batch(batch, session_factory)
        [original] = await _gear_rows_for(async_connection, "18")

        retired = {
            **_asset_json(18, "CE4Y Harness 1", "Retired"),
            "name": "Harness (retired)",
        }
        _queue_listings(mock_transport, default=_listing(), archived=_listing(retired))
        mock_transport.add_response("/hardware/18", json_data=retired, method="GET")
        for batch in await _collect(sync_service):
            result = await sync_service.sync_asset_batch(batch, session_factory)
            assert result["synced"] == 1

        rows = await _gear_rows_for(async_connection, "18")
        assert [(row.id, row.name) for row in rows] == [
            (original.id, "Harness (retired)")
        ]
        gear_count = await async_connection.scalar(
            text("SELECT count(*) FROM gear_items WHERE user_id = 'user-123'")
        )
        assert gear_count == 1


class TestSnipeItLinkOwner:
    """An asset another user already links is a failed asset, not a takeover."""

    @pytest.mark.asyncio
    async def test_an_asset_id_another_users_instance_uses_is_synced_too(
        self,
        sync_service: SnipeItSyncService,
        mock_transport: Any,
        async_connection: AsyncConnection,
        session_factory: Any,
    ) -> None:
        """Snipe-IT ids are per instance: another user's asset 31 is not this
        user's, so this user's asset 31 is imported with its own link."""
        await async_connection.execute(
            text("""
                INSERT INTO sync_metadata
                    (user_id, internal_uuid, integration_source, external_id,
                     last_synced_at, version_hash, sync_status)
                VALUES ('other-user', gen_random_uuid()::text, 'snipeit', '31',
                        now(), 'theirs', 'success')
            """)
        )
        mock_transport.add_response(
            "/hardware/31", json_data=_asset_json(31, "My rope"), method="GET"
        )

        result = await sync_service.sync_asset_batch([31], session_factory)

        assert (result["synced"], result["failed"]) == (1, 0)
        links = (
            await async_connection.execute(
                text("""
                    SELECT user_id, version_hash FROM sync_metadata
                    WHERE integration_source = 'snipeit' AND external_id = '31'
                    ORDER BY user_id
                """)
            )
        ).fetchall()
        assert [row.user_id for row in links] == ["other-user", "user-123"]
        assert links[0].version_hash == "theirs"
        assert [row.name for row in await _gear_rows_for(async_connection, "31")] == [
            "My rope"
        ]
