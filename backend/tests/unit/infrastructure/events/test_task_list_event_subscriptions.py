"""No stream consumer reads the task list events yet, and that is pinned.

The list events live outside ``app.core.tasks.models.events``, so the task event
inventory (``tests/task_event_inventory.py``) — which every consumer's task
subscription test reads — cannot see them. Without this file, a consumer starting
to match ``TaskListCreated`` would be caught by nothing.

Each assertion here is expected to flip deliberately in a later phase: history
when the list history projection lands (it must use its own ``entity_type``,
never the task one), search when lists are indexed. Flipping one means changing
this file on purpose, which is the point.
"""

from unittest.mock import MagicMock

import pytest
from core_shared.stream_client import StreamClient
from core_shared.stream_consumer import StreamConsumer

from app.core.tasks.models.task_list_events import TASK_LIST_EVENT_TYPES
from app.infrastructure.config import Settings
from app.infrastructure.events.history_projection_consumer import (
    HistoryProjectionConsumer,
)
from app.infrastructure.events.inbound_event_consumer import InboundEventConsumer
from app.infrastructure.events.search_indexer_consumer import SearchIndexerConsumer
from app.infrastructure.events.summary_invalidation_consumer import (
    SummaryInvalidationConsumer,
)


def _consumers() -> list[StreamConsumer]:
    stream = "pms:domain-events"
    return [
        HistoryProjectionConsumer(stream_client=MagicMock(), stream_name=stream),
        SearchIndexerConsumer(
            stream_client=MagicMock(spec=StreamClient), stream_name=stream
        ),
        SummaryInvalidationConsumer(
            stream_client=MagicMock(spec=StreamClient), stream_name=stream
        ),
        InboundEventConsumer(
            stream_client=MagicMock(spec=StreamClient),
            container=MagicMock(),
            settings=MagicMock(spec=Settings),
            stream_name=stream,
        ),
    ]


@pytest.mark.parametrize("event_type", sorted(TASK_LIST_EVENT_TYPES))
@pytest.mark.parametrize(
    "consumer", _consumers(), ids=lambda consumer: type(consumer).__name__
)
def test_no_consumer_matches_a_task_list_event(
    consumer: StreamConsumer, event_type: str
) -> None:
    """An unmatched event is acknowledged and skipped, so it does no harm."""
    assert consumer._matches_event_type(event_type) is False
