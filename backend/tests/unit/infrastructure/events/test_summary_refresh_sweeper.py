"""
Unit tests for SummaryRefreshSweeper.

Tests the sweeper that claims due buffered summary-refresh markers and
publishes ContactSummaryRefreshDue events to the outbox.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infrastructure.events.summary_refresh_sweeper import SummaryRefreshSweeper


class TestSummaryRefreshSweeper:
    """Test cases for SummaryRefreshSweeper.sweep_batch."""

    @pytest.fixture
    def mock_repo(self) -> MagicMock:
        """Create a mock ContactSummaryRepository."""
        repo = MagicMock()
        repo.claim_due_refreshes = AsyncMock(return_value=[])
        return repo

    @pytest.fixture
    def mock_publisher(self) -> MagicMock:
        """Create a mock OutboxEventPublisher."""
        publisher = MagicMock()
        publisher.publish = AsyncMock()
        return publisher

    def _make_sweeper(self) -> SummaryRefreshSweeper:
        return SummaryRefreshSweeper(buffer_seconds=300, batch_size=50)

    async def _sweep(self, mock_repo: MagicMock, mock_publisher: MagicMock) -> int:
        """Run sweep_batch with the repository and publisher patched."""
        sweeper = self._make_sweeper()
        mock_conn = AsyncMock()
        with (
            patch(
                "app.infrastructure.events.summary_refresh_sweeper.SqlContactSummaryRepository",
                return_value=mock_repo,
            ),
            patch(
                "app.infrastructure.events.summary_refresh_sweeper.OutboxEventPublisher",
                return_value=mock_publisher,
            ),
        ):
            return await sweeper.sweep_batch(mock_conn)

    @pytest.mark.asyncio
    async def test_dispatches_due_enabled_contacts(
        self, mock_repo: MagicMock, mock_publisher: MagicMock
    ) -> None:
        """Each claimed enabled contact gets one ContactSummaryRefreshDue event."""
        mock_repo.claim_due_refreshes = AsyncMock(
            return_value=[(42, False), (43, False)]
        )

        dispatched = await self._sweep(mock_repo, mock_publisher)

        assert dispatched == 2
        assert mock_publisher.publish.await_count == 2
        published_events = [
            call.args[0] for call in mock_publisher.publish.await_args_list
        ]
        assert [event.event_data["contact_id"] for event in published_events] == [
            42,
            43,
        ]
        assert all(
            event.event_type == "ContactSummaryRefreshDue" for event in published_events
        )

    @pytest.mark.asyncio
    async def test_disabled_contacts_claimed_but_not_dispatched(
        self, mock_repo: MagicMock, mock_publisher: MagicMock
    ) -> None:
        """Disabled rows have their markers cleared but no event published."""
        mock_repo.claim_due_refreshes = AsyncMock(
            return_value=[(42, True), (43, False)]
        )

        dispatched = await self._sweep(mock_repo, mock_publisher)

        assert dispatched == 1
        assert mock_publisher.publish.await_count == 1
        event = mock_publisher.publish.await_args_list[0].args[0]
        assert event.event_data["contact_id"] == 43

    @pytest.mark.asyncio
    async def test_empty_claim_is_noop(
        self, mock_repo: MagicMock, mock_publisher: MagicMock
    ) -> None:
        """No due rows means no publishes."""
        dispatched = await self._sweep(mock_repo, mock_publisher)

        assert dispatched == 0
        mock_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cutoff_is_buffer_seconds_before_now(
        self, mock_repo: MagicMock, mock_publisher: MagicMock
    ) -> None:
        """The claim cutoff trails now by the configured buffer window."""
        before = datetime.now(UTC)
        await self._sweep(mock_repo, mock_publisher)
        after = datetime.now(UTC)

        cutoff = mock_repo.claim_due_refreshes.await_args.args[0]
        assert before - timedelta(seconds=300) <= cutoff
        assert cutoff <= after - timedelta(seconds=300)

        limit = mock_repo.claim_due_refreshes.await_args.args[1]
        assert limit == 50

    @pytest.mark.asyncio
    async def test_publish_failure_propagates_for_rollback(
        self, mock_repo: MagicMock, mock_publisher: MagicMock
    ) -> None:
        """A publish failure propagates so the transaction (and the claimed
        markers) rolls back and the batch is retried on the next sweep."""
        mock_repo.claim_due_refreshes = AsyncMock(return_value=[(42, False)])
        mock_publisher.publish = AsyncMock(side_effect=RuntimeError("outbox down"))

        with pytest.raises(RuntimeError, match="outbox down"):
            await self._sweep(mock_repo, mock_publisher)
