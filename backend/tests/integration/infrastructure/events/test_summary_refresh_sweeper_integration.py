"""Integration tests for SummaryRefreshSweeper against a real database."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from core_shared.models.contacts.entities import Contact
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import (
    SqlContactRepository,
    SqlContactSummaryRepository,
)
from app.infrastructure.events.summary_refresh_sweeper import SummaryRefreshSweeper


@pytest.mark.integration
class TestSummaryRefreshSweeperIntegration:
    """Sweeps claim due markers and publish ContactSummaryRefreshDue to the outbox."""

    @pytest.fixture
    def sweeper(self) -> SummaryRefreshSweeper:
        """Create a sweeper with the default 5-minute buffer."""
        return SummaryRefreshSweeper(buffer_seconds=300, batch_size=50)

    @pytest.fixture
    async def test_contact_id(self, clean_database: AsyncConnection) -> int:
        """Create a test contact and return its id."""
        contact = Contact(first_name="Sweeper", last_name="Test")
        saved: Contact = await SqlContactRepository(clean_database).save(contact)
        assert saved.id is not None
        return saved.id

    async def _mark_backdated(
        self, connection: AsyncConnection, contact_id: int, seconds_ago: int
    ) -> None:
        """Set a refresh marker backdated by the given number of seconds."""
        await SqlContactSummaryRepository(connection).mark_refresh_requested(contact_id)
        await connection.execute(
            text(
                """
                UPDATE contact_summaries
                SET refresh_requested_at = :backdated
                WHERE contact_id = :contact_id
                """
            ),
            {
                "contact_id": contact_id,
                "backdated": datetime.now(UTC) - timedelta(seconds=seconds_ago),
            },
        )

    async def _get_due_outbox_events(
        self, connection: AsyncConnection, contact_id: int
    ) -> list[Any]:
        """Fetch ContactSummaryRefreshDue outbox rows for a contact."""
        result = await connection.execute(
            text(
                """
                SELECT event_id, event_type, aggregate_id
                FROM outbox_events
                WHERE event_type = 'ContactSummaryRefreshDue'
                  AND aggregate_id = :contact_id
                """
            ),
            {"contact_id": contact_id},
        )
        return list(result.fetchall())

    @pytest.mark.asyncio
    async def test_sweep_dispatches_due_marker_to_outbox(
        self,
        sweeper: SummaryRefreshSweeper,
        test_contact_id: int,
        clean_database: AsyncConnection,
    ):
        """A marker older than the buffer produces one Due outbox event and clears."""
        await self._mark_backdated(clean_database, test_contact_id, seconds_ago=600)

        dispatched = await sweeper.sweep_batch(clean_database)

        assert dispatched == 1
        events = await self._get_due_outbox_events(clean_database, test_contact_id)
        assert len(events) == 1
        assert events[0].aggregate_id == test_contact_id

        result = await clean_database.execute(
            text(
                "SELECT refresh_requested_at FROM contact_summaries "
                "WHERE contact_id = :contact_id"
            ),
            {"contact_id": test_contact_id},
        )
        assert result.scalar_one() is None

    @pytest.mark.asyncio
    async def test_second_sweep_does_not_double_dispatch(
        self,
        sweeper: SummaryRefreshSweeper,
        test_contact_id: int,
        clean_database: AsyncConnection,
    ):
        """Once claimed, a marker is not dispatched again by a later sweep."""
        await self._mark_backdated(clean_database, test_contact_id, seconds_ago=600)

        first = await sweeper.sweep_batch(clean_database)
        second = await sweeper.sweep_batch(clean_database)

        assert first == 1
        assert second == 0
        events = await self._get_due_outbox_events(clean_database, test_contact_id)
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_sweep_leaves_recent_marker_untouched(
        self,
        sweeper: SummaryRefreshSweeper,
        test_contact_id: int,
        clean_database: AsyncConnection,
    ):
        """A marker still inside the buffer window is not dispatched."""
        await self._mark_backdated(clean_database, test_contact_id, seconds_ago=10)

        dispatched = await sweeper.sweep_batch(clean_database)

        assert dispatched == 0
        events = await self._get_due_outbox_events(clean_database, test_contact_id)
        assert events == []

    @pytest.mark.asyncio
    async def test_sweep_dispatches_auto_paused_contact(
        self,
        sweeper: SummaryRefreshSweeper,
        test_contact_id: int,
        clean_database: AsyncConnection,
    ):
        """A low-activity pause is re-evaluated: its due marker is dispatched."""
        await self._mark_backdated(clean_database, test_contact_id, seconds_ago=600)
        await clean_database.execute(
            text(
                """
                UPDATE contact_summaries
                SET is_disabled = TRUE, disabled_reason = 'low_activity',
                    status = 'disabled'
                WHERE contact_id = :contact_id
                """
            ),
            {"contact_id": test_contact_id},
        )

        dispatched = await sweeper.sweep_batch(clean_database)

        assert dispatched == 1
        events = await self._get_due_outbox_events(clean_database, test_contact_id)
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_sweep_skips_user_disabled_contact(
        self,
        sweeper: SummaryRefreshSweeper,
        test_contact_id: int,
        clean_database: AsyncConnection,
    ):
        """A user's own disable is sticky: its due marker is cleared, not dispatched."""
        await self._mark_backdated(clean_database, test_contact_id, seconds_ago=600)
        await clean_database.execute(
            text(
                """
                UPDATE contact_summaries
                SET is_disabled = TRUE, disabled_reason = 'user', status = 'disabled'
                WHERE contact_id = :contact_id
                """
            ),
            {"contact_id": test_contact_id},
        )

        dispatched = await sweeper.sweep_batch(clean_database)

        assert dispatched == 0
        events = await self._get_due_outbox_events(clean_database, test_contact_id)
        assert events == []
