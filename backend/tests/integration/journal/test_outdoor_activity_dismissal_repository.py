"""Integration tests for SqlOutdoorActivityDismissalRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.history import Provenance
from core_shared.models.journals import EventDateRange, Journal
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.outdoor_activity_dismissal_repository import (
    SqlOutdoorActivityDismissalRepository,
)

USER_ID = "test-user-123"
OTHER_USER_ID = "test-user-456"


@pytest_asyncio.fixture
async def dismissal_repository(
    async_connection: AsyncConnection,
) -> SqlOutdoorActivityDismissalRepository:
    return SqlOutdoorActivityDismissalRepository(async_connection)


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    return SqlJournalRepository(async_connection)


async def _create_journal(
    journal_repository: SqlJournalRepository,
    *,
    title: str = "Test Journal",
    hours_offset: int = 0,
) -> Journal:
    now = datetime.now(UTC) + timedelta(hours=hours_offset)
    journal = Journal(
        user_id=USER_ID,
        title=title,
        content="content",
        event_date_range=EventDateRange(start=now, end=now + timedelta(hours=1)),
    )
    return await journal_repository.save(journal)


@pytest.mark.integration
class TestDismiss:
    async def test_dismiss_records_and_lists_journal_id(
        self,
        dismissal_repository: SqlOutdoorActivityDismissalRepository,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal = await _create_journal(journal_repository)
        assert journal.id is not None

        dismissal = await dismissal_repository.dismiss(
            journal_id=journal.id, user_id=USER_ID, provenance=Provenance.UI
        )

        assert dismissal.journal_id == journal.id
        assert dismissal.user_id == USER_ID
        assert dismissal.provenance == Provenance.UI
        assert dismissal.created_at is not None

        dismissed = await dismissal_repository.list_dismissed_journal_ids(USER_ID)
        assert dismissed == {journal.id}

    async def test_redismiss_is_idempotent_and_refreshes_provenance(
        self,
        dismissal_repository: SqlOutdoorActivityDismissalRepository,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal = await _create_journal(journal_repository)
        assert journal.id is not None

        first = await dismissal_repository.dismiss(
            journal_id=journal.id, user_id=USER_ID, provenance=Provenance.UI
        )
        second = await dismissal_repository.dismiss(
            journal_id=journal.id, user_id=USER_ID, provenance=Provenance.MCP
        )

        # Still a single dismissal for the journal (no duplicate rows / no error).
        assert await dismissal_repository.list_dismissed_journal_ids(USER_ID) == {
            journal.id
        }
        # Provenance is refreshed by the re-dismiss.
        assert second.provenance == Provenance.MCP
        assert second.created_at == first.created_at


@pytest.mark.integration
class TestUndismiss:
    async def test_undismiss_removes_the_dismissal(
        self,
        dismissal_repository: SqlOutdoorActivityDismissalRepository,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal = await _create_journal(journal_repository)
        assert journal.id is not None
        await dismissal_repository.dismiss(
            journal_id=journal.id, user_id=USER_ID, provenance=Provenance.UI
        )

        removed = await dismissal_repository.undismiss(
            journal_id=journal.id, user_id=USER_ID
        )

        assert removed is True
        assert await dismissal_repository.list_dismissed_journal_ids(USER_ID) == set()

    async def test_undismiss_is_idempotent_when_not_dismissed(
        self,
        dismissal_repository: SqlOutdoorActivityDismissalRepository,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal = await _create_journal(journal_repository)
        assert journal.id is not None

        # Never dismissed -> un-dismiss is a harmless no-op returning False.
        removed = await dismissal_repository.undismiss(
            journal_id=journal.id, user_id=USER_ID
        )

        assert removed is False
        assert await dismissal_repository.list_dismissed_journal_ids(USER_ID) == set()


@pytest.mark.integration
class TestUserScoping:
    async def test_dismissals_are_scoped_per_user(
        self,
        dismissal_repository: SqlOutdoorActivityDismissalRepository,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal = await _create_journal(journal_repository)
        assert journal.id is not None
        await dismissal_repository.dismiss(
            journal_id=journal.id, user_id=USER_ID, provenance=Provenance.UI
        )

        # Another user has not dismissed anything.
        assert (
            await dismissal_repository.list_dismissed_journal_ids(OTHER_USER_ID)
            == set()
        )
