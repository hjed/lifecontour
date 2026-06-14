"""Unit tests for ContactMergeService (ITER13-001 Phases 1 & 2).

Phase 1 covers the merge preconditions and that the service delegates the
relationship and journal-link re-points to the repositories. Phase 2 completes
the engine: sub-entity re-points, the prefer-non-empty scalar policy, source
deletion, the inline ``merged_from`` history row, and the survivor summary
refresh event. The REST/MCP surface arrives in later phases.
"""

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.contacts.entities import Contact
from core_shared.models.history import Provenance

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
    # save() echoes the contact it was handed so callers can inspect the merge.
    repo.save.side_effect = lambda contact: contact
    return repo


@pytest.fixture
def mock_relationship_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_journal_rel_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_history_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_event_publisher() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def merge_service(
    mock_contact_repo,
    mock_relationship_repo,
    mock_journal_rel_repo,
    mock_history_service,
    mock_event_publisher,
) -> ContactMergeService:
    return ContactMergeService(
        contact_repo=mock_contact_repo,
        relationship_repo=mock_relationship_repo,
        journal_relationship_repo=mock_journal_rel_repo,
        history_service=mock_history_service,
        event_publisher=mock_event_publisher,
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

    @pytest.mark.asyncio
    async def test_repoints_every_sub_entity_then_deletes_source(
        self,
        merge_service,
        mock_contact_repo,
        mock_transaction,
    ) -> None:
        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction
        )

        for repoint in (
            mock_contact_repo.repoint_methods,
            mock_contact_repo.repoint_addresses,
            mock_contact_repo.repoint_notes,
            mock_contact_repo.repoint_important_dates,
            mock_contact_repo.repoint_tags,
        ):
            repoint.assert_awaited_once_with(SOURCE_ID, SURVIVOR_ID, mock_transaction)

        # The source is deleted only after the aggregate has been re-pointed.
        mock_contact_repo.delete.assert_awaited_once_with(SOURCE_ID)


class TestContactMergeScalarPolicy:
    """Prefer-non-empty scalar policy (survivor wins on conflict)."""

    @staticmethod
    def _saved_contact(mock_contact_repo: AsyncMock) -> Contact:
        mock_contact_repo.save.assert_awaited_once()
        return cast(Contact, mock_contact_repo.save.await_args.args[0])

    @pytest.mark.asyncio
    async def test_survivor_value_kept_when_source_empty(
        self, merge_service, mock_contact_repo, mock_transaction
    ) -> None:
        mock_contact_repo.find_by_id.side_effect = lambda cid: (
            Contact(id=SURVIVOR_ID, first_name="Survivor", company="Acme")
            if cid == SURVIVOR_ID
            else Contact(id=SOURCE_ID, first_name="Source", company=None)
        )

        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction
        )

        saved = self._saved_contact(mock_contact_repo)
        assert saved.id == SURVIVOR_ID
        assert saved.company == "Acme"

    @pytest.mark.asyncio
    async def test_source_value_used_when_survivor_empty(
        self, merge_service, mock_contact_repo, mock_transaction
    ) -> None:
        mock_contact_repo.find_by_id.side_effect = lambda cid: (
            Contact(id=SURVIVOR_ID, first_name="Survivor", job_title=None)
            if cid == SURVIVOR_ID
            else Contact(id=SOURCE_ID, first_name="Source", job_title="Engineer")
        )

        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction
        )

        saved = self._saved_contact(mock_contact_repo)
        assert saved.job_title == "Engineer"

    @pytest.mark.asyncio
    async def test_survivor_wins_when_both_differ(
        self, merge_service, mock_contact_repo, mock_transaction
    ) -> None:
        mock_contact_repo.find_by_id.side_effect = lambda cid: (
            Contact(id=SURVIVOR_ID, first_name="Survivor", last_name="Keep")
            if cid == SURVIVOR_ID
            else Contact(id=SOURCE_ID, first_name="Source", last_name="Drop")
        )

        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction
        )

        saved = self._saved_contact(mock_contact_repo)
        assert saved.first_name == "Survivor"
        assert saved.last_name == "Keep"


class TestContactMergeSideEffects:
    """The merge records an audit row and requests a summary refresh."""

    @pytest.mark.asyncio
    async def test_records_merged_from_history_row(
        self,
        merge_service,
        mock_history_service,
        mock_transaction,
    ) -> None:
        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction
        )

        mock_history_service.record_contact_change.assert_awaited_once()
        call = mock_history_service.record_contact_change.await_args
        assert call.args[0] == SURVIVOR_ID
        changed_fields = call.args[1]
        assert "merged_from" in changed_fields
        old_value, _ = changed_fields["merged_from"]
        assert old_value == SOURCE_ID

    @staticmethod
    def _published(mock_event_publisher: AsyncMock) -> dict[str, Any]:
        """Map each published event by its ``event_type``."""
        return {
            call.args[0].event_type: call.args[0]
            for call in mock_event_publisher.publish.await_args_list
        }

    @pytest.mark.asyncio
    async def test_requests_summary_refresh_for_survivor(
        self,
        merge_service,
        mock_event_publisher,
        mock_transaction,
    ) -> None:
        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction
        )

        event = self._published(mock_event_publisher)["ContactSummaryRefreshRequested"]
        assert event.aggregate_id == SURVIVOR_ID

    @pytest.mark.asyncio
    async def test_emits_contact_merged_event_with_provenance(
        self,
        merge_service,
        mock_event_publisher,
        mock_transaction,
    ) -> None:
        await merge_service.merge_contacts(
            SURVIVOR_ID,
            SOURCE_ID,
            transaction=mock_transaction,
            changed_by="ui",
            source=Provenance.UI,
        )

        event = self._published(mock_event_publisher)["ContactMerged"]
        assert event.aggregate_id == SURVIVOR_ID
        assert event.event_data["survivor_contact_id"] == SURVIVOR_ID
        assert event.event_data["source_contact_id"] == SOURCE_ID
        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"

    @pytest.mark.asyncio
    async def test_does_not_emit_contact_deleted_for_source(
        self,
        merge_service,
        mock_event_publisher,
        mock_transaction,
    ) -> None:
        """The merge must NOT emit ``ContactDeleted`` for the source.

        Integration workers (e.g. the Google worker) consume ``ContactDeleted``
        to delete the *remote* contact unconditionally — that contradicts merge
        semantics, where the source's external links may need to carry over to
        or consolidate onto the survivor (ITER13-005). Search de-indexing of the
        source is handled by the search indexer's ``ContactMerged`` handler
        instead, which has no integration side effects.
        """
        await merge_service.merge_contacts(
            SURVIVOR_ID, SOURCE_ID, transaction=mock_transaction
        )

        published = self._published(mock_event_publisher)
        assert "ContactDeleted" not in published
        assert "ContactMerged" in published
