"""Which stream consumers read the task list events, pinned consumer by consumer.

The list events live outside ``app.core.tasks.models.events``, so the task event
inventory — which every consumer's task subscription test reads — does not
include them. Without this file, a consumer starting (or stopping) to match
``TaskListCreated`` would be caught by nothing.

**History reads every list event** since ITER21-001 Phase 7, which projects them
under ``entity_type='task_list'`` (never the task one). Every other consumer
still matches none; search is expected to flip deliberately when lists are
indexed (ITER21-008). Flipping one means changing this file on purpose, which is
the point.
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

_STREAM = "pms:domain-events"


def _consumers_that_ignore_list_events() -> list[StreamConsumer]:
    stream = _STREAM
    return [
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
def test_the_history_projection_matches_every_task_list_event(
    event_type: str,
) -> None:
    """A list's history is projected; an unmatched list event would be
    acknowledged and skipped, and its history line lost for good."""
    consumer = HistoryProjectionConsumer(stream_client=MagicMock(), stream_name=_STREAM)

    assert consumer._matches_event_type(event_type) is True


@pytest.mark.parametrize("event_type", sorted(TASK_LIST_EVENT_TYPES))
@pytest.mark.parametrize(
    "consumer",
    _consumers_that_ignore_list_events(),
    ids=lambda consumer: type(consumer).__name__,
)
def test_no_other_consumer_matches_a_task_list_event(
    consumer: StreamConsumer, event_type: str
) -> None:
    """An unmatched event is acknowledged and skipped, so it does no harm."""
    assert consumer._matches_event_type(event_type) is False
