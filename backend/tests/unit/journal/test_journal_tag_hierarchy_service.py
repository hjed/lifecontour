"""Unit tests for JournalTagHierarchyService descendant expansion."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

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

        result = await hierarchy_service.get_all_descendants_bulk([parent_id])

        assert result == [child]
        mock_tag_repo.get_descendants_for_tags.assert_awaited_once_with([parent_id])

    async def test_empty_input_short_circuits(self, hierarchy_service, mock_tag_repo):
        result = await hierarchy_service.get_all_descendants_bulk([])

        assert result == []
        mock_tag_repo.get_descendants_for_tags.assert_not_awaited()
