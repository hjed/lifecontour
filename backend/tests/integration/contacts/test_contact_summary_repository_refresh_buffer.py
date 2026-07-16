"""Integration tests for the summary refresh rolling-debounce marker methods."""

from datetime import UTC, datetime, timedelta

import pytest
from core_shared.models.contacts.entities import Contact, ContactSummary, SummaryStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import (
    SqlContactRepository,
    SqlContactSummaryRepository,
)


@pytest.mark.integration
class TestSummaryRefreshBufferRepository:
    """Integration tests for mark/clear/claim of the refresh debounce marker."""

    @pytest.fixture
    def contact_repo(self, clean_database: AsyncConnection):
        """Create ContactRepository instance."""
        return SqlContactRepository(clean_database)

    @pytest.fixture
    def summary_repo(self, clean_database: AsyncConnection):
        """Create ContactSummaryRepository instance."""
        return SqlContactSummaryRepository(clean_database)

    @pytest.fixture
    async def test_contact(self, contact_repo: SqlContactRepository) -> Contact:
        """Create and return a test contact."""
        contact = Contact(first_name="Buffer", last_name="Test")
        saved: Contact = await contact_repo.save(contact)
        return saved

    async def _get_marker(
        self, connection: AsyncConnection, contact_id: int
    ) -> datetime | None:
        """Read the raw refresh_requested_at marker for a contact."""
        result = await connection.execute(
            text(
                """
                SELECT refresh_requested_at FROM contact_summaries
                WHERE contact_id = :contact_id
                """
            ),
            {"contact_id": contact_id},
        )
        row = result.fetchone()
        assert row is not None, "expected a contact_summaries row"
        marker: datetime | None = row.refresh_requested_at
        return marker

    async def _backdate_marker(
        self, connection: AsyncConnection, contact_id: int, seconds_ago: int
    ) -> datetime:
        """Force the marker to a timestamp in the past and return it."""
        backdated = datetime.now(UTC) - timedelta(seconds=seconds_ago)
        await connection.execute(
            text(
                """
                UPDATE contact_summaries
                SET refresh_requested_at = :backdated
                WHERE contact_id = :contact_id
                """
            ),
            {"contact_id": contact_id, "backdated": backdated},
        )
        return backdated

    @pytest.mark.asyncio
    async def test_mark_creates_row_with_marker_and_pending_status(
        self, summary_repo, test_contact, clean_database
    ):
        """Marking a contact with no summary row creates one with the marker set."""
        await summary_repo.mark_refresh_requested(test_contact.id)

        summary = await summary_repo.find_by_contact_id(test_contact.id)
        assert summary is not None
        assert summary.status == SummaryStatus.PENDING

        marker = await self._get_marker(clean_database, test_contact.id)
        assert marker is not None

    @pytest.mark.asyncio
    async def test_mark_resets_timer_on_existing_marker(
        self, summary_repo, test_contact, clean_database
    ):
        """A second mark overwrites the marker (rolling debounce reset)."""
        await summary_repo.mark_refresh_requested(test_contact.id)
        backdated = await self._backdate_marker(
            clean_database, test_contact.id, seconds_ago=240
        )

        await summary_repo.mark_refresh_requested(test_contact.id)

        marker = await self._get_marker(clean_database, test_contact.id)
        assert marker is not None
        assert marker > backdated

    @pytest.mark.asyncio
    async def test_mark_preserves_existing_summary_content(
        self, summary_repo, test_contact, clean_database
    ):
        """Marking an existing generated summary must not clobber its content."""
        await summary_repo.upsert(
            ContactSummary(
                contact_id=test_contact.id,
                summary_text="Existing summary",
                follow_up_suggestions=["Call them"],
                status=SummaryStatus.GENERATED,
            )
        )

        await summary_repo.mark_refresh_requested(test_contact.id)

        summary = await summary_repo.find_by_contact_id(test_contact.id)
        assert summary is not None
        assert summary.summary_text == "Existing summary"
        assert summary.follow_up_suggestions == ["Call them"]
        assert summary.status == SummaryStatus.GENERATED

        marker = await self._get_marker(clean_database, test_contact.id)
        assert marker is not None

    @pytest.mark.asyncio
    async def test_mark_is_noop_for_disabled_summary(
        self, summary_repo, test_contact, clean_database
    ):
        """Marking a disabled summary must not set the marker."""
        await summary_repo.upsert(
            ContactSummary(
                contact_id=test_contact.id,
                status=SummaryStatus.DISABLED,
                is_disabled=True,
            )
        )

        await summary_repo.mark_refresh_requested(test_contact.id)

        marker = await self._get_marker(clean_database, test_contact.id)
        assert marker is None

    @pytest.mark.asyncio
    async def test_clear_refresh_request(
        self, summary_repo, test_contact, clean_database
    ):
        """Clearing removes a pending marker."""
        await summary_repo.mark_refresh_requested(test_contact.id)

        await summary_repo.clear_refresh_request(test_contact.id)

        marker = await self._get_marker(clean_database, test_contact.id)
        assert marker is None

    @pytest.mark.asyncio
    async def test_claim_returns_and_clears_due_rows(
        self, summary_repo, test_contact, clean_database
    ):
        """Claiming returns due contacts and clears their markers atomically."""
        await summary_repo.mark_refresh_requested(test_contact.id)
        await self._backdate_marker(clean_database, test_contact.id, seconds_ago=600)

        cutoff = datetime.now(UTC) - timedelta(seconds=300)
        claimed = await summary_repo.claim_due_refreshes(cutoff, limit=10)

        assert claimed == [(test_contact.id, False)]
        marker = await self._get_marker(clean_database, test_contact.id)
        assert marker is None

    @pytest.mark.asyncio
    async def test_claim_leaves_not_yet_due_rows(
        self, summary_repo, test_contact, clean_database
    ):
        """Rows whose marker is newer than the cutoff are not claimed."""
        await summary_repo.mark_refresh_requested(test_contact.id)

        cutoff = datetime.now(UTC) - timedelta(seconds=300)
        claimed = await summary_repo.claim_due_refreshes(cutoff, limit=10)

        assert claimed == []
        marker = await self._get_marker(clean_database, test_contact.id)
        assert marker is not None

    @pytest.mark.asyncio
    async def test_claim_returns_disabled_rows_flagged(
        self, summary_repo, test_contact, clean_database
    ):
        """Disabled rows with stale markers are claimed (cleared) but flagged."""
        await summary_repo.mark_refresh_requested(test_contact.id)
        await self._backdate_marker(clean_database, test_contact.id, seconds_ago=600)
        # Disable after the marker was set (e.g. LowActivityChecker mid-window)
        await clean_database.execute(
            text(
                """
                UPDATE contact_summaries
                SET is_disabled = TRUE, status = 'disabled'
                WHERE contact_id = :contact_id
                """
            ),
            {"contact_id": test_contact.id},
        )

        cutoff = datetime.now(UTC) - timedelta(seconds=300)
        claimed = await summary_repo.claim_due_refreshes(cutoff, limit=10)

        assert claimed == [(test_contact.id, True)]
        marker = await self._get_marker(clean_database, test_contact.id)
        assert marker is None

    @pytest.mark.asyncio
    async def test_claim_respects_limit_and_orders_oldest_first(
        self, summary_repo, contact_repo, clean_database
    ):
        """Claim honours the batch limit, claiming the oldest markers first."""
        contacts = []
        for index in range(3):
            contact = await contact_repo.save(
                Contact(first_name=f"Batch{index}", last_name="Limit")
            )
            contacts.append(contact)
            await summary_repo.mark_refresh_requested(contact.id)

        # Oldest marker on the first contact, newest on the last
        await self._backdate_marker(clean_database, contacts[0].id, seconds_ago=900)
        await self._backdate_marker(clean_database, contacts[1].id, seconds_ago=700)
        await self._backdate_marker(clean_database, contacts[2].id, seconds_ago=500)

        cutoff = datetime.now(UTC) - timedelta(seconds=300)
        claimed = await summary_repo.claim_due_refreshes(cutoff, limit=2)

        claimed_ids = [contact_id for contact_id, _ in claimed]
        assert claimed_ids == [contacts[0].id, contacts[1].id]

        remaining = await self._get_marker(clean_database, contacts[2].id)
        assert remaining is not None
