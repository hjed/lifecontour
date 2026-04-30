"""
Unit tests for the DeadLetterRepository.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.events.dead_letter_repository import (
    DeadLetterEvent,
    DeadLetterRepository,
)


@pytest.fixture
def mock_dead_letter_event() -> DeadLetterEvent:
    return DeadLetterEvent(
        event_id="evt-123",
        event_type="ContactCreated",
        aggregate_id=42,
        event_data={"foo": "bar"},
        consumer_group="test-consumer",
        delivery_count=5,
        last_error="Something went wrong",
    )


@pytest.mark.asyncio
async def test_save_dead_letter_event(
    async_connection: AsyncConnection,
    mock_dead_letter_event: DeadLetterEvent,
) -> None:
    """Test saving a new dead-letter event."""
    repository = DeadLetterRepository(async_connection)

    # Act
    saved_event = await repository.save(mock_dead_letter_event)

    # Assert
    assert saved_event.id is not None
    assert saved_event.created_at is not None
    assert saved_event.event_id == mock_dead_letter_event.event_id
    assert saved_event.event_data == {"foo": "bar"}

    # Verify count
    count = await repository.count()
    assert count == 1


@pytest.mark.asyncio
async def test_save_dead_letter_event_idempotent(
    async_connection: AsyncConnection,
    mock_dead_letter_event: DeadLetterEvent,
) -> None:
    """Test saving the same dead-letter event multiple times is idempotent."""
    repository = DeadLetterRepository(async_connection)

    # Act
    saved_event1 = await repository.save(mock_dead_letter_event)
    await repository.save(mock_dead_letter_event)

    # Assert
    assert saved_event1.id is not None
    # Second save won't return an id because on_conflict_do_nothing returns nothing
    # but the count should still be 1
    count = await repository.count()
    assert count == 1


@pytest.mark.asyncio
async def test_list_dead_letter_events(
    async_connection: AsyncConnection,
) -> None:
    """Test listing dead-letter events."""
    repository = DeadLetterRepository(async_connection)

    # Create multiple events
    events = [
        DeadLetterEvent(
            event_id=f"evt-{i}",
            event_type="ContactCreated",
            aggregate_id=i,
            event_data={"foo": i},
            consumer_group="test-consumer",
            delivery_count=5,
        )
        for i in range(3)
    ]

    for event in events:
        await repository.save(event)

    # Act
    listed_events = await repository.list_events(limit=2)

    # Assert
    assert len(listed_events) == 2
    # Should be ordered by newest first, so evt-2 and evt-1
    assert listed_events[0].event_id == "evt-2"
    assert listed_events[1].event_id == "evt-1"
