"""Integration tests for the journal update precondition (optimistic concurrency).

The check lives in the service layer so REST and MCP share one implementation,
which is why it is tested here rather than only through a controller.

A note on the fixture: every request in this suite runs inside one shared
transaction and Postgres' ``now()`` is the *transaction* timestamp, so a real
write does not move ``updated_at`` here the way it does in production. A
concurrent writer is therefore simulated by nudging the row's timestamp
directly — which still exercises the real locking read, the real tag
computation and the real refusal.
"""

from datetime import datetime

import pytest
from core_shared.etag import resource_etag
from core_shared.exceptions import PreconditionFailedError
from core_shared.models.journals import EventDateRange, Journal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_service import JournalService
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher


def create_test_journal(title: str = "Original title") -> Journal:
    """A minimal journal to write against."""
    return Journal(
        user_id="user123",
        title=title,
        content="Original content",
        event_date_range=EventDateRange(
            start=datetime(2024, 1, 1), end=datetime(2024, 1, 1)
        ),
    )


async def _simulate_concurrent_write(
    connection: AsyncConnection, journal_id: int
) -> None:
    """Move the row's ``updated_at`` on, as another writer's commit would."""
    await connection.execute(
        text(
            "UPDATE journals SET updated_at = updated_at + interval '1 second' "
            "WHERE id = :journal_id"
        ),
        {"journal_id": journal_id},
    )


@pytest.mark.integration
class TestJournalUpdatePrecondition:
    """``JournalService.update_journal`` under an ``expected_etags`` precondition."""

    @pytest.fixture
    def journal_repo(self, clean_database: AsyncConnection):
        return SqlJournalRepository(clean_database)

    @pytest.fixture
    def journal_service(self, journal_repo, clean_database: AsyncConnection):
        return JournalService(
            journal_repo=journal_repo,
            event_publisher=OutboxEventPublisher(clean_database),
            task_anchor_repo=SqlTaskAnchorRepository(clean_database),
        )

    @pytest.mark.asyncio
    async def test_matching_tag_permits_the_write(
        self, journal_service, clean_database: AsyncConnection
    ):
        saved = await journal_service.create_journal(
            create_test_journal(), clean_database
        )
        etag = resource_etag("journals", saved.id, saved.updated_at)

        saved.title = "Updated title"
        result = await journal_service.update_journal(
            saved, clean_database, expected_etags=[etag]
        )

        assert result.title == "Updated title"

    @pytest.mark.asyncio
    async def test_stale_tag_refuses_the_write(
        self, journal_service, journal_repo, clean_database: AsyncConnection
    ):
        saved = await journal_service.create_journal(
            create_test_journal(), clean_database
        )
        stale_etag = resource_etag("journals", saved.id, saved.updated_at)
        await _simulate_concurrent_write(clean_database, saved.id)

        saved.title = "Updated title"
        with pytest.raises(PreconditionFailedError) as exc_info:
            await journal_service.update_journal(
                saved, clean_database, expected_etags=[stale_etag]
            )

        assert exc_info.value.status_code == 412
        # The refusal must leave the row alone — a partially applied conflict
        # would be worse than the lost update it exists to prevent.
        persisted = await journal_repo.find_by_id(saved.id)
        assert persisted.title == "Original title"

    @pytest.mark.asyncio
    async def test_refusal_carries_the_current_tag(
        self, journal_service, journal_repo, clean_database: AsyncConnection
    ):
        """The caller can recover from the error body without re-reading."""
        saved = await journal_service.create_journal(
            create_test_journal(), clean_database
        )
        stale_etag = resource_etag("journals", saved.id, saved.updated_at)
        await _simulate_concurrent_write(clean_database, saved.id)

        with pytest.raises(PreconditionFailedError) as exc_info:
            await journal_service.update_journal(
                saved, clean_database, expected_etags=[stale_etag]
            )

        current = await journal_repo.find_by_id(saved.id)
        assert exc_info.value.error_meta() == {
            "resource_type": "journals",
            "resource_id": str(saved.id),
            "current_etag": resource_etag("journals", saved.id, current.updated_at),
        }

    @pytest.mark.asyncio
    async def test_no_precondition_writes_as_before(
        self, journal_service, clean_database: AsyncConnection
    ):
        """The feature is opt-in: today's callers send nothing and are unaffected."""
        saved = await journal_service.create_journal(
            create_test_journal(), clean_database
        )
        await _simulate_concurrent_write(clean_database, saved.id)

        saved.title = "Updated title"
        result = await journal_service.update_journal(saved, clean_database)

        assert result.title == "Updated title"

    @pytest.mark.asyncio
    async def test_wildcard_permits_the_write_at_any_version(
        self, journal_service, clean_database: AsyncConnection
    ):
        saved = await journal_service.create_journal(
            create_test_journal(), clean_database
        )
        await _simulate_concurrent_write(clean_database, saved.id)

        saved.title = "Updated title"
        result = await journal_service.update_journal(
            saved, clean_database, expected_etags=["*"]
        )

        assert result.title == "Updated title"
