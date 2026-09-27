"""Integration tests for gear usage pushes that fail part-way and are retried.

A usage journal's checkout and check-in are two Snipe-IT writes. When the
second one fails (typically a 429 during a burst of imports), the event is
redelivered, and the retry must finish the pair rather than stop at the
checkout it already recorded: an asset left checked out makes every later
checkout of it fail.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from core_shared.stream_client import StreamEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from snipeit_api_client import SnipeItAPIClient
from snipeit_rate_limiter import SnipeItRateLimitError
from snipeit_sync_service import SnipeItSyncService
from stream_consumer_tasks import SnipeItWorkerStreamConsumer

from .test_checkin_sync_integration import (
    _insert_gear_usage_journal,
    _posts,
    _queue_asset_dates,
    _session_factory,
    _sync_statuses,
)

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
