"""
Unit tests for DualContactEventPublisher.

Tests that the dual publisher delegates to both the SQL (real-time)
and outbox (transactional) publishers, and that failures propagate
correctly.
"""

from datetime import datetime
from unittest.mock import create_autospec

import pytest

from app.core.contacts.adapters.sql import SqlContactEventPublisher
from app.core.contacts.models.events import DomainEvent
from app.infrastructure.events.dual_contact_event_publisher import (
    DualContactEventPublisher,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher


class TestDualContactEventPublisher:
    """Test cases for DualContactEventPublisher."""

    @pytest.fixture
    def mock_sql_pub(self):
        """Create a mock SqlContactEventPublisher."""
        return create_autospec(SqlContactEventPublisher, instance=True)

    @pytest.fixture
    def mock_outbox_pub(self):
        """Create a mock OutboxEventPublisher."""
        return create_autospec(OutboxEventPublisher, instance=True)

    @pytest.fixture
    def publisher(self, mock_sql_pub, mock_outbox_pub):
        """Create a DualContactEventPublisher with mocked delegates."""
        return DualContactEventPublisher(mock_sql_pub, mock_outbox_pub)

    @pytest.fixture
    def sample_event(self):
        """Create a sample domain event for testing."""
        return DomainEvent(
            event_id="test-event-123",
            event_type="ContactCreated",
            aggregate_id=42,
            event_data={"contact_id": 42, "first_name": "Alice"},
            occurred_at=datetime(2024, 1, 1, 12, 0, 0),
        )

    # --- publish() ---

    @pytest.mark.asyncio
    async def test_publish_delegates_to_both_publishers(
        self, publisher, mock_sql_pub, mock_outbox_pub, sample_event
    ):
        """Both the SQL and outbox publishers should receive the event."""
        await publisher.publish(sample_event)

        mock_sql_pub.publish.assert_awaited_once_with(sample_event)
        mock_outbox_pub.publish.assert_awaited_once_with(sample_event)

    @pytest.mark.asyncio
    async def test_publish_calls_sql_publisher_first(
        self, publisher, mock_sql_pub, mock_outbox_pub, sample_event
    ):
        """SQL publisher should be called before the outbox publisher."""
        call_order: list[str] = []
        mock_sql_pub.publish.side_effect = lambda _: call_order.append("sql")
        mock_outbox_pub.publish.side_effect = lambda _: call_order.append("outbox")

        await publisher.publish(sample_event)

        assert call_order == ["sql", "outbox"]

    @pytest.mark.asyncio
    async def test_publish_propagates_sql_publisher_error(
        self, publisher, mock_sql_pub, mock_outbox_pub, sample_event
    ):
        """If the SQL publisher raises, the error should propagate and outbox should not be called."""
        mock_sql_pub.publish.side_effect = Exception("SQL publish failed")

        with pytest.raises(Exception, match="SQL publish failed"):
            await publisher.publish(sample_event)

        mock_outbox_pub.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_publish_propagates_outbox_publisher_error(
        self, publisher, mock_sql_pub, mock_outbox_pub, sample_event
    ):
        """If the outbox publisher raises, the error should propagate (SQL was already called)."""
        mock_outbox_pub.publish.side_effect = Exception("Outbox publish failed")

        with pytest.raises(Exception, match="Outbox publish failed"):
            await publisher.publish(sample_event)

        # SQL publisher should have been called before the error
        mock_sql_pub.publish.assert_awaited_once_with(sample_event)

    # --- publish_batch() ---

    @pytest.mark.asyncio
    async def test_publish_batch_delegates_to_both_publishers(
        self, publisher, mock_sql_pub, mock_outbox_pub
    ):
        """Both publishers should receive the full batch."""
        events = [
            DomainEvent(
                event_id=f"test-event-{i}",
                event_type="ContactCreated",
                aggregate_id=i,
                event_data={"contact_id": i},
                occurred_at=datetime(2024, 1, 1, 12, 0, 0),
            )
            for i in range(3)
        ]

        await publisher.publish_batch(events)

        mock_sql_pub.publish_batch.assert_awaited_once_with(events)
        mock_outbox_pub.publish_batch.assert_awaited_once_with(events)

    @pytest.mark.asyncio
    async def test_publish_batch_empty(self, publisher, mock_sql_pub, mock_outbox_pub):
        """An empty batch should still be delegated to both publishers."""
        await publisher.publish_batch([])

        mock_sql_pub.publish_batch.assert_awaited_once_with([])
        mock_outbox_pub.publish_batch.assert_awaited_once_with([])

    @pytest.mark.asyncio
    async def test_publish_batch_propagates_sql_publisher_error(
        self, publisher, mock_sql_pub, mock_outbox_pub
    ):
        """If the SQL publisher raises during batch, outbox should not be called."""
        events = [
            DomainEvent(
                event_id="test-event-1",
                event_type="ContactCreated",
                aggregate_id=1,
                event_data={"contact_id": 1},
                occurred_at=datetime(2024, 1, 1, 12, 0, 0),
            ),
        ]
        mock_sql_pub.publish_batch.side_effect = Exception("SQL batch failed")

        with pytest.raises(Exception, match="SQL batch failed"):
            await publisher.publish_batch(events)

        mock_outbox_pub.publish_batch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_publish_batch_propagates_outbox_publisher_error(
        self, publisher, mock_sql_pub, mock_outbox_pub
    ):
        """If the outbox publisher raises during batch, the error propagates."""
        events = [
            DomainEvent(
                event_id="test-event-1",
                event_type="ContactCreated",
                aggregate_id=1,
                event_data={"contact_id": 1},
                occurred_at=datetime(2024, 1, 1, 12, 0, 0),
            ),
        ]
        mock_outbox_pub.publish_batch.side_effect = Exception("Outbox batch failed")

        with pytest.raises(Exception, match="Outbox batch failed"):
            await publisher.publish_batch(events)

        # SQL publisher should have been called before the error
        mock_sql_pub.publish_batch.assert_awaited_once_with(events)

    # --- initialization ---

    def test_stores_both_publishers(self, mock_sql_pub, mock_outbox_pub):
        """Constructor should store references to both delegate publishers."""
        publisher = DualContactEventPublisher(mock_sql_pub, mock_outbox_pub)

        assert publisher.sql_pub is mock_sql_pub
        assert publisher.outbox_pub is mock_outbox_pub
