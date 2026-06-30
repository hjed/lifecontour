"""
Unit tests for StravaWorkerStreamConsumer.

Tests verify consumer group name, event type patterns, and event handling.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from core_shared.testing import make_session_factory_mock

from stream_consumer_tasks import StravaWorkerStreamConsumer


class TestStravaWorkerStreamConsumer:
    """Tests for StravaWorkerStreamConsumer configuration and behavior."""

    @pytest.fixture
    def consumer(self) -> StravaWorkerStreamConsumer:
        """Create a StravaWorkerStreamConsumer with mocked dependencies."""
        mock_stream_client = MagicMock()
        mock_session_factory = make_session_factory_mock()
        return StravaWorkerStreamConsumer(
            stream_client=mock_stream_client,
            session_factory=mock_session_factory,
        )

    def test_consumer_group_name_is_strava_worker(
        self, consumer: StravaWorkerStreamConsumer
    ) -> None:
        """Consumer group name is 'strava-worker'."""
        assert consumer._group_name == "strava-worker"

    def test_consumer_event_type_patterns(
        self, consumer: StravaWorkerStreamConsumer
    ) -> None:
        """Consumer subscribes to strava event patterns."""
        assert "strava." in consumer._event_type_patterns

    @pytest.mark.asyncio
    async def test_handle_event_logs_placeholder(
        self, consumer: StravaWorkerStreamConsumer
    ) -> None:
        """_handle_event route-dispatches a strava event without error."""
        from core_shared.stream_client import StreamEvent

        event = StreamEvent(
            message_id="1-0",
            event_id="evt-123",
            event_type="strava.activity.created",
            aggregate_id=123,
            event_data={"object_id": 123},
            occurred_at="2026-01-01T00:00:00Z",
        )
        # Should not raise — routes to the placeholder handler that just logs
        await consumer._handle_event(event)

    def test_stream_name_default(self, consumer: StravaWorkerStreamConsumer) -> None:
        """Default stream name is 'pms:domain-events'."""
        assert consumer._stream_name == "pms:domain-events"
