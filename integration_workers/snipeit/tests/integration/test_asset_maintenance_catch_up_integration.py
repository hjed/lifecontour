"""Integration tests for the maintenance catch-up of a newly linked asset (#1563).

The asset and maintenance syncs run side by side, so a maintenance batch can
skip a record because its asset is not linked yet. The asset sync that first
links the asset imports that asset's unsettled records, so the record arrives
in the same run whichever sync gets there first.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from .test_maintenance_sync_integration import (
    _import_rows,
    _joined_session_factory,
    _journal_events,
    _listed,
    _seed_maintenance_journal,
    _seed_push_record,
    _seed_synced_asset,
)

_ASSET_ID = 51


def _queue_asset(mock_transport: Any) -> None:
    mock_transport.add_response(
        f"/hardware/{_ASSET_ID}",
        json_data={
            "id": _ASSET_ID,
            "name": "Canyoneroo 50m",
            "asset_tag": "00051",
            "status_label": {"id": 2, "name": "Ready to Deploy"},
        },
        method="GET",
    )


def _queue_asset_maintenances(
    mock_transport: Any, *rows: dict[str, Any], status_code: int = 200
) -> None:
    """Serve the asset's ``GET /maintenances?asset_id=`` listing, once."""
    mock_transport.add_response(
        f"asset_id={_ASSET_ID}",
        status_code=status_code,
        json_data={"total": len(rows), "rows": list(rows)},
        method="GET",
    )


def _maintenance_listings(mock_transport: Any) -> list[list[str] | None]:
    """The ``asset_id`` filter of each ``GET /maintenances`` listing made."""
    return [
        parse_qs(urlparse(str(request.url)).query).get("asset_id")
        for request in mock_transport.requests
        if request.url.path.endswith("/maintenances")
    ]


def _maintenance_fetches(mock_transport: Any) -> list[str]:
    """The path of each single-record ``GET /maintenances/<id>`` made."""
    return [
        request.url.path
        for request in mock_transport.requests
        if "/maintenances/" in request.url.path
    ]


async def _asset_link(async_connection: AsyncConnection) -> str | None:
    result = await async_connection.execute(
        text("""
            SELECT internal_uuid FROM sync_metadata
            WHERE user_id = 'user-123'
              AND integration_source = 'snipeit'
              AND external_id = :external_id
        """),
        {"external_id": str(_ASSET_ID)},
    )
    return result.scalar_one_or_none()


async def _imported_gear_item(async_connection: AsyncConnection) -> str:
    """The gear item the one journal outbox event puts its record on."""
    result = await async_connection.execute(
        text("""
            SELECT event_data FROM outbox_events
            WHERE event_type LIKE 'journal_event.%'
        """)
    )
    event_data = result.scalar_one()
    if isinstance(event_data, str):
        event_data = json.loads(event_data)
    return str(event_data["journal_data"]["gear_maintenance_data"]["gear_item_id"])


class TestNewlyLinkedAssetImportsItsMaintenances:
    @pytest.mark.asyncio
    async def test_a_record_skipped_for_its_asset_is_imported_once_the_asset_is_linked(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        session_factory = _joined_session_factory(async_connection)
        mock_transport.add_response(
            "/maintenances/301", json_data=_listed(301), method="GET"
        )
        skipped = await snipeit_sync_service.sync_maintenance_batch(
            [301], session_factory
        )
        assert skipped == {"synced": 0, "skipped": 1, "failed": 0}

        _queue_asset(mock_transport)
        _queue_asset_maintenances(mock_transport, _listed(301))
        mock_transport.add_response(
            "/maintenances/301", json_data=_listed(301), method="GET"
        )
        result = await snipeit_sync_service.sync_asset_batch(
            [_ASSET_ID], session_factory
        )

        assert result == {"synced": 1, "skipped": 0, "failed": 0}
        assert _maintenance_listings(mock_transport) == [[str(_ASSET_ID)]]
        assert await _journal_events(async_connection) == ["journal_event.created"]
        assert await _import_rows(async_connection, 301) == 1
        assert await _imported_gear_item(async_connection) == await _asset_link(
            async_connection
        )

    @pytest.mark.asyncio
    async def test_a_record_already_settled_here_is_not_fetched_again(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        other_gear = await _seed_synced_asset(async_connection, 99)
        journal_id = await _seed_maintenance_journal(
            async_connection, gear_item_id=other_gear, title="Retire Harness"
        )
        await _seed_push_record(
            async_connection, journal_id=journal_id, maintenance_id=302
        )
        _queue_asset(mock_transport)
        _queue_asset_maintenances(mock_transport, _listed(302))

        result = await snipeit_sync_service.sync_asset_batch(
            [_ASSET_ID], _joined_session_factory(async_connection)
        )

        assert result == {"synced": 1, "skipped": 0, "failed": 0}
        assert _maintenance_listings(mock_transport) == [[str(_ASSET_ID)]]
        assert _maintenance_fetches(mock_transport) == []
        assert await _journal_events(async_connection) == []

    @pytest.mark.asyncio
    async def test_resyncing_an_already_linked_asset_lists_no_maintenances(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        gear_item_id = await _seed_synced_asset(async_connection, _ASSET_ID)
        _queue_asset(mock_transport)

        result = await snipeit_sync_service.sync_asset_batch(
            [_ASSET_ID], _joined_session_factory(async_connection)
        )

        assert result == {"synced": 1, "skipped": 0, "failed": 0}
        assert await _asset_link(async_connection) == gear_item_id
        assert _maintenance_listings(mock_transport) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status_code", "attempts"),
        [(500, 1), (403, 1), (429, 3)],
        ids=["server-error", "forbidden", "rate-limited"],
    )
    async def test_a_failed_catch_up_leaves_the_asset_synced(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        status_code: int,
        attempts: int,
    ) -> None:
        """The record stays unsettled, so the next maintenance sync imports it."""
        _queue_asset(mock_transport)
        for _ in range(attempts):
            _queue_asset_maintenances(mock_transport, status_code=status_code)

        with patch("snipeit_api_client.asyncio.sleep"):
            result = await snipeit_sync_service.sync_asset_batch(
                [_ASSET_ID], _joined_session_factory(async_connection)
            )

        assert result == {"synced": 1, "skipped": 0, "failed": 0}
        assert await _asset_link(async_connection) is not None
        assert _maintenance_listings(mock_transport) == [[str(_ASSET_ID)]] * attempts
        assert await _journal_events(async_connection) == []
