"""Unit tests for the ImmichWorkerStreamConsumer declarative route table.

ITER14-004 Phase 2: the consumer declares an ``EventRoute`` table instead of
overriding ``_handle_event``. These tests assert the route table maps the
expected event types to the two handlers (contact-id injection vs raw forward),
the consumed-event set is unchanged, and unmatched events are acked without
dispatch.
"""

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.stream_client import StreamEvent
from core_shared.testing import make_session_factory_mock

from stream_consumer_tasks import ImmichWorkerStreamConsumer


@pytest.fixture
def consumer() -> ImmichWorkerStreamConsumer:
    """Return a configured ImmichWorkerStreamConsumer with mock dependencies."""
    return ImmichWorkerStreamConsumer(
        stream_client=MagicMock(),
        session_factory=make_session_factory_mock(),
    )


def _make_stream_event(event_type: str) -> StreamEvent:
    """Create a minimal StreamEvent for the given type."""
    return StreamEvent(
        message_id="1-0",
        event_id="evt-1",
        event_type=event_type,
        aggregate_id=42,
        event_data={"user_id": 1},
        occurred_at="2024-01-01T00:00:00Z",
    )


@pytest.fixture
def fake_worker_module() -> Generator[AsyncMock, None, None]:
    """Inject a fake ``worker`` module exposing process_contact_event.

    Avoids ImmichWorkerSettings instantiation during the lazy import in the
    route handlers.
    """
    import sys
    import types

    _sentinel = object()
    original = sys.modules.get("worker", _sentinel)

    mock = AsyncMock()
    fake_worker = types.ModuleType("worker")
    fake_worker.process_contact_event = mock  # type: ignore[attr-defined]
    sys.modules["worker"] = fake_worker
    yield mock
    if original is _sentinel:
        sys.modules.pop("worker", None)
    else:
        sys.modules["worker"] = original  # type: ignore[assignment]


class TestImmichWorkerRouteTable:
    """The consumer declares its consumed events via a route table."""

    def test_route_table_covers_exact_consumed_event_set(
        self, consumer: ImmichWorkerStreamConsumer
    ) -> None:
        """Route patterns equal the documented consumed-event set (regression)."""
        patterns = {route.pattern for route in consumer._routes}
        assert patterns == {
            "ContactCreated",
            "ContactUpdated",
            "ContactBirthdayChanged",
            "ContactMerged",
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "event_type",
        ["ContactCreated", "ContactUpdated", "ContactBirthdayChanged"],
    )
    async def test_injecting_route_adds_contact_id(
        self,
        consumer: ImmichWorkerStreamConsumer,
        fake_worker_module: AsyncMock,
        event_type: str,
    ) -> None:
        """The three lifecycle events inject contact_id from aggregate_id."""
        await consumer._handle_event(_make_stream_event(event_type))

        fake_worker_module.assert_awaited_once_with(
            {"session_factory": consumer._session_factory, "job_id": "evt-1"},
            event_type,
            {"user_id": 1, "contact_id": 42},
        )

    @pytest.mark.asyncio
    async def test_merged_route_forwards_raw_payload(
        self,
        consumer: ImmichWorkerStreamConsumer,
        fake_worker_module: AsyncMock,
    ) -> None:
        """ContactMerged forwards the payload unchanged (no contact_id injected)."""
        event = StreamEvent(
            message_id="4-0",
            event_id="evt-4",
            event_type="ContactMerged",
            aggregate_id=10,
            event_data={"survivor_contact_id": 10, "source_contact_id": 20},
            occurred_at="2024-01-01T00:00:00Z",
        )

        await consumer._handle_event(event)

        fake_worker_module.assert_awaited_once_with(
            {"session_factory": consumer._session_factory, "job_id": "evt-4"},
            "ContactMerged",
            {"survivor_contact_id": 10, "source_contact_id": 20},
        )

    @pytest.mark.asyncio
    async def test_unmatched_event_acked_without_dispatch(
        self,
        consumer: ImmichWorkerStreamConsumer,
        fake_worker_module: AsyncMock,
    ) -> None:
        """An unmatched event is acknowledged and no handler is invoked."""
        mock_client: Any = consumer._stream_client
        mock_client.read_events = AsyncMock(
            return_value=[_make_stream_event("JournalCreated")]
        )
        mock_client.acknowledge = AsyncMock()

        processed = await consumer._process_batch()

        assert processed == 1
        mock_client.acknowledge.assert_awaited_once()
        fake_worker_module.assert_not_awaited()
