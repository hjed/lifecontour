"""Unit tests for ContactMergeService (ITER13-001 Phase 1).

Covers the merge preconditions and that the service delegates the relationship
and journal-link re-points to the repositories. Sub-entity merge, source
deletion, events, and the REST/MCP surface arrive in later phases.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.contacts.entities import Contact

from app.core.contacts.models.exceptions import (
    ContactMergeConflictError,
    ContactNotFoundError,
)
from app.core.contacts.services.contact_merge_service import ContactMergeService

SURVIVOR_ID = 1
SOURCE_ID = 2


@pytest.fixture
def mock_transaction() -> AsyncMock:
    mock_tx = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_result.fetchone.return_value = None
    mock_tx.execute.return_value = mock_result
    return mock_tx


@pytest.fixture
def survivor() -> Contact:
    return Contact(id=SURVIVOR_ID, first_name="Survivor")


@pytest.fixture
def source() -> Contact:
    return Contact(id=SOURCE_ID, first_name="Source")


@pytest.fixture
def mock_contact_repo(mock_transaction, survivor, source) -> AsyncMock:
    repo = AsyncMock()
    repo.transaction = mock_transaction
    repo.find_by_id.side_effect = lambda cid: (
        survivor if cid == SURVIVOR_ID else source if cid == SOURCE_ID else None
    )
    return repo


@pytest.fixture
def mock_relationship_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_journal_rel_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def merge_service(
    mock_contact_repo, mock_relationship_repo, mock_journal_rel_repo
) -> ContactMergeService:
    return ContactMergeService(
        contact_repo=mock_contact_repo,
        relationship_repo=mock_relationship_repo,
        journal_relationship_repo=mock_journal_rel_repo,
    )


class TestContactMergePreconditions:
    """Validation of the merge preconditions."""

    @pytest.mark.asyncio
    async def test_self_merge_raises_conflict(
        self, merge_service, mock_transaction
    ) -> None:
        with pytest.raises(ContactMergeConflictError):
            await merge_service.merge_contacts(
                SURVIVOR_ID, SURVIVOR_ID, transaction=mock_transaction
            )

    @pytest.mark.asyncio
    async def test_missing_survivor_raises_not_found(
        self, merge_service, mock_contact_repo, mock_transaction
    ) -> None:
        mock_contact_repo.find_by_id.side_effect = lambda cid: (
            None if cid == 999 else Contact(id=cid, first_name="Source")
        )
        with pytest.raises(ContactNotFoundError):
            await merge_service.merge_contacts(
                999, SOURCE_ID, transaction=mock_transaction
            )

    @pytest.mark.asyncio
    async def test_missing_source_raises_not_found(
        self, merge_service, mock_contact_repo, mock_transaction
    ) -> None:
        mock_contact_repo.find_by_id.side_effect = lambda cid: (
            Contact(id=cid, first_name="Survivor") if cid == SURVIVOR_ID else None
        )
        with pytest.raises(ContactNotFoundError):
            await merge_service.merge_contacts(
                SURVIVOR_ID, 999, transaction=mock_transaction
            )


class TestContactMergeDelegation:
    """The service delegates the re-points to the repositories."""

    @pytest.mark.asyncio
    async def test_repoints_relationships_and_journal_links(
        self,
        merge_service,
        mock_relationship_repo,
        mock_journal_rel_repo,
        mock_transaction,
        survivor,
    ) -> None:
        result = await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction
        )

        mock_relationship_repo.repoint_contact.assert_awaited_once_with(
            SOURCE_ID, SURVIVOR_ID, mock_transaction
        )
        mock_journal_rel_repo.repoint_contact.assert_awaited_once_with(
            SOURCE_ID, SURVIVOR_ID, mock_transaction
        )
        assert result is survivor
