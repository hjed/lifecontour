"""Integration tests for TagService against a real database.

Focused on the create-or-get race-safety of ``create_tag``: a duplicate-name
insert must roll back via its SAVEPOINT (without poisoning the surrounding unit
of work) and fall back to the existing tag.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import SqlContactEventPublisher, SqlTagRepository
from app.core.contacts.services.tag_hierarchy_service import TagHierarchyService
from app.core.contacts.services.tag_service import TagService


@pytest.mark.integration
class TestTagServiceCreateOrGetIntegration:
    """create_tag is a race-safe create-or-get against real Postgres."""

    @pytest.fixture
    def tag_repo(self, clean_database: AsyncConnection):
        return SqlTagRepository(clean_database)

    @pytest.fixture
    def service(self, tag_repo, clean_database):
        return TagService(
            tag_repo=tag_repo,
            tag_hierarchy_service=TagHierarchyService(tag_repo),
            event_publisher=SqlContactEventPublisher(clean_database),
        )

    @pytest.mark.asyncio
    async def test_create_tag_returns_existing_on_duplicate_name(
        self, service, clean_database
    ):
        """A second create of the same name returns the first tag, not an error.

        This exercises the real SAVEPOINT recovery: the duplicate INSERT raises a
        unique-violation that, without the savepoint, would abort the whole
        transaction. The savepoint rolls back just the failed insert so the
        service can look the existing tag up and return it.
        """
        first = await service.create_tag(name="Work", transaction=clean_database)
        assert first.id is not None

        second = await service.create_tag(name="Work", transaction=clean_database)

        # Same row returned, no DuplicateTagNameError surfaced to the caller.
        assert second.id == first.id

        # Case-insensitive match: the constraint is on LOWER(name).
        third = await service.create_tag(name="WORK", transaction=clean_database)
        assert third.id == first.id

    @pytest.mark.asyncio
    async def test_connection_usable_after_duplicate_recovery(
        self, service, clean_database
    ):
        """After a duplicate is recovered, the connection still accepts writes.

        Proves the unit of work was not poisoned by the failed insert: a
        subsequent, unrelated create succeeds on the same connection.
        """
        await service.create_tag(name="Work", transaction=clean_database)
        await service.create_tag(name="Work", transaction=clean_database)  # duplicate

        other = await service.create_tag(name="Personal", transaction=clean_database)
        assert other.id is not None

        repo = SqlTagRepository(clean_database)
        assert (await repo.find_by_name("Work")) is not None
        assert (await repo.find_by_name("Personal")) is not None
