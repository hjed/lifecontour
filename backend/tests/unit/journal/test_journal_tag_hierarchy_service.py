"""Unit tests for JournalTagHierarchyService descendant expansion."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from core_shared.models.journals import JournalTagNotFoundError

from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.services.journal_tag_hierarchy_service import (
    JournalTagHierarchyService,
)
from tests.integration.contact_seeding import TEST_USER_ID


@pytest.fixture
def mock_tag_repo():
    """Create a mock journal tag repository."""
    return AsyncMock()


@pytest.fixture
def hierarchy_service(mock_tag_repo):
    """Create a JournalTagHierarchyService with a mocked repository."""
    return JournalTagHierarchyService(tag_repo=mock_tag_repo)


class TestGetAllDescendantsBulk:
    """The bulk descendant lookup mirrors the contact TagHierarchyService."""

    async def test_delegates_to_repository(self, hierarchy_service, mock_tag_repo):
        parent_id = uuid4()
        child = JournalTag(
            user_id=TEST_USER_ID, id=uuid4(), name="Child", parent_id=parent_id
        )
        mock_tag_repo.get_descendants_for_tags.return_value = [child]

        result = await hierarchy_service.get_all_descendants_bulk(
            [parent_id], user_id=TEST_USER_ID
        )

        assert result == [child]
        mock_tag_repo.get_descendants_for_tags.assert_awaited_once_with(
            [parent_id], user_id=TEST_USER_ID
        )

    async def test_empty_input_short_circuits(self, hierarchy_service, mock_tag_repo):
        result = await hierarchy_service.get_all_descendants_bulk(
            [], user_id=TEST_USER_ID
        )

        assert result == []
        mock_tag_repo.get_descendants_for_tags.assert_not_awaited()


class TestChecksStayWithinTheOwner:
    """Every lookup the hierarchy rules make is scoped to the acting user."""

    async def test_name_uniqueness_is_checked_among_the_owners_tags(
        self, hierarchy_service, mock_tag_repo
    ):
        mock_tag_repo.find_by_name.return_value = None

        await hierarchy_service.validate_tag_name_uniqueness(
            "family", user_id=TEST_USER_ID
        )

        mock_tag_repo.find_by_name.assert_awaited_once_with(
            "family", user_id=TEST_USER_ID
        )

    async def test_a_parent_the_owner_cannot_see_is_not_found(
        self, hierarchy_service, mock_tag_repo
    ):
        mock_tag_repo.find_by_id.return_value = None
        foreign_parent = uuid4()

        with pytest.raises(JournalTagNotFoundError):
            await hierarchy_service.validate_parent(
                foreign_parent, uuid4(), user_id=TEST_USER_ID
            )

        mock_tag_repo.find_by_id.assert_awaited_once_with(
            foreign_parent, user_id=TEST_USER_ID
        )

    async def test_a_merge_target_the_owner_cannot_see_is_not_found(
        self, hierarchy_service, mock_tag_repo
    ):
        source = JournalTag(user_id=TEST_USER_ID, id=uuid4(), name="mine")
        mock_tag_repo.find_by_id.side_effect = [source, None]

        with pytest.raises(JournalTagNotFoundError):
            await hierarchy_service.validate_merge_target(
                source.id, uuid4(), user_id=TEST_USER_ID
            )
