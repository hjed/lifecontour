"""Unit tests for the consumer that owns daily summary freshness.

Until ITER18-005 Phase 7 this ran inside ``SearchIndexerConsumer``, where it had
landed incidentally. It could not stay there: the architecture documentation
records — and tests at both the consumer and the indexer pin — that the search
indexer **permanently ignores task events**, and this phase's whole point is
that a task change makes a summary stale. So the invalidation moved to a group
of its own and the journal half came with it, because summary freshness having
two owners is what made it incidental in the first place.

What is asserted here is the wiring: which events reach the service, which
deliberately do not, and that the group does not replay the stream's history the
first time it starts.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.stream_client import StreamClient, StreamEvent

from app.core.journal.services.daily_summary_invalidation_service import (
    HANDLED_EVENT_TYPES,
)
from app.infrastructure.events.summary_invalidation_consumer import (
    SummaryInvalidationConsumer,
)
from tests.task_event_inventory import task_event_types


@pytest.fixture
def consumer() -> SummaryInvalidationConsumer:
    return SummaryInvalidationConsumer(
        stream_client=MagicMock(spec=StreamClient),
        stream_name="pms:domain-events",
    )


def _make_stream_event(
    event_type: str = "JournalUpdated",
    event_data: dict[str, Any] | None = None,
) -> StreamEvent:
    return StreamEvent(
        message_id="1234567890-0",
        event_id="evt-test-123",
        event_type=event_type,
        aggregate_id=42,
        event_data=event_data or {"journal_id": 42},
        occurred_at="2026-04-27T10:30:00+00:00",
    )


class TestWhatThisConsumerListensFor:
    """The subscription is derived from the service, not written out again.

    A second list is a second thing to remember to extend, and this domain has
    already been caught by one: the handler this replaces matched exactly three
    journal events, so a type change, a deletion and a contact change each left
    the day's summary ``GENERATED``.
    """

    @pytest.mark.parametrize("event_type", sorted(HANDLED_EVENT_TYPES))
    def test_every_event_the_service_handles_is_subscribed(
        self, consumer: SummaryInvalidationConsumer, event_type: str
    ) -> None:
        assert consumer._matches_event_type(event_type) is True

    @pytest.mark.parametrize(
        "event_type",
        [
            "JournalTagAssigned",
            "JournalTagRemoved",
            "JournalTagDeleted",
            "JournalTagMerged",
            "JournalTagRenamed",
        ],
    )
    def test_journal_tag_events_are_not_subscribed(
        self, consumer: SummaryInvalidationConsumer, event_type: str
    ) -> None:
        """The summary's agenda entries carry no tags and the prompt renders none.

        ITER18-004 Phase 4f predicted these would matter here because the
        dashboard's agenda *card* shows tags (**W15**). Checked: the summary's
        does not, so subscribing would discard cached summaries — and pay to
        regenerate them — for a change that cannot alter one.
        """
        assert consumer._matches_event_type(event_type) is False

    @pytest.mark.parametrize("event_type", ["ContactCreated", "TagAssigned"])
    def test_unrelated_contact_events_are_not_subscribed(
        self, consumer: SummaryInvalidationConsumer, event_type: str
    ) -> None:
        assert consumer._matches_event_type(event_type) is False

    def test_contact_deleted_is_subscribed(
        self, consumer: SummaryInvalidationConsumer
    ) -> None:
        """Deleting a contact takes its important dates with it, by cascade.

        Only ``ContactDeleted`` is published for that, so a summary listing one
        of those dates would otherwise go on naming a contact that has gone.
        """
        assert consumer._matches_event_type("ContactDeleted") is True

    def test_contact_updated_is_subscribed_for_one_field_only(
        self, consumer: SummaryInvalidationConsumer
    ) -> None:
        """Subscribed at the stream, filtered in the service.

        ``ContactUpdated`` is the only announcement that an important date was
        removed, and the only one that a **merge** re-pointed a contact's dates
        onto a survivor whose name is different: ``update_contact`` deletes a contact's dates and re-adds
        them, so the one that went leaves no event of its own and the survivors'
        say nothing about it. Every other ``ContactUpdated`` — a rename, a new
        phone number — reaches the service and is discarded there, because that
        is where the ``changed_fields`` key can be read.
        """
        assert consumer._matches_event_type("ContactUpdated") is True

    def test_the_group_is_its_own(self, consumer: SummaryInvalidationConsumer) -> None:
        """A group of its own is what lets it read events the indexer refuses."""
        assert consumer._group_name == "summary-invalidation"

    def test_the_task_events_that_change_a_prompt_are_subscribed(
        self, consumer: SummaryInvalidationConsumer
    ) -> None:
        """Read out of the tasks module, so a new event type fails here.

        The set is deliberately not every task event: a task's *intermediate*
        journal links are populated on the read model and never rendered, so
        attaching one cannot change a prompt and invalidating on it would buy a
        regeneration that produces the same prose.
        """
        subscribed = {
            event_type
            for event_type in task_event_types()
            if consumer._matches_event_type(event_type)
        }

        assert subscribed == task_event_types() - {
            "TaskJournalLinked",
            "TaskJournalUnlinked",
        }


class TestTheGroupDoesNotReplayTheStreamsHistory:
    """A new group reading from id ``0`` would consume every event ever published.

    ``pms:domain-events`` is not trimmed, so on the deploy that introduces this
    group the default would walk the entire history and mark stale every summary
    any of it touched. The cost of starting at the latest id instead is one
    deploy window of events, which is the smaller of the two by a long way.
    """

    def test_the_group_starts_at_the_latest_id(
        self, consumer: SummaryInvalidationConsumer
    ) -> None:
        assert consumer._group_start_id == "$"

    def test_the_other_consumers_still_start_at_the_beginning(self) -> None:
        """The default is unchanged; only this group opts out."""
        from app.infrastructure.events.history_projection_consumer import (
            HistoryProjectionConsumer,
        )

        projection = HistoryProjectionConsumer(
            stream_client=MagicMock(spec=StreamClient)
        )

        assert projection._group_start_id == "0"


class TestHandlingAnEvent:
    """The consumer adapts and delegates; the deciding lives in the service."""

    @pytest.mark.asyncio
    async def test_the_event_reaches_the_service_whole(
        self, consumer: SummaryInvalidationConsumer, mock_db_engine: MagicMock
    ) -> None:
        service = AsyncMock()
        event = _make_stream_event(
            event_type="JournalDeleted",
            event_data={"journal_id": 7, "user_id": "user-1"},
        )

        with (
            patch(
                "app.infrastructure.events.summary_invalidation_consumer"
                ".get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch.object(consumer, "_service_for", return_value=service),
        ):
            await consumer._handle_event(event)

        service.invalidate_for_event.assert_awaited_once_with(
            "JournalDeleted", {"journal_id": 7, "user_id": "user-1"}
        )

    @pytest.mark.asyncio
    async def test_the_work_runs_inside_one_transaction(
        self, consumer: SummaryInvalidationConsumer, mock_db_engine: MagicMock
    ) -> None:
        """``engine.begin()`` commits on exit, so an invalidation is durable.

        The same shape the projection and indexer consumers use: one connection
        per event, committed by the context manager rather than by the service,
        which holds no unit of work of its own.
        """
        service = AsyncMock()

        with (
            patch(
                "app.infrastructure.events.summary_invalidation_consumer"
                ".get_async_database_engine",
                return_value=mock_db_engine,
            ),
            patch.object(consumer, "_service_for", return_value=service) as build,
        ):
            await consumer._handle_event(_make_stream_event())

        build.assert_called_once()
