"""Unit tests for JournalIndexingService tag-change re-indexing.

The journal search document carries ``tag_ids`` as a filterable attribute, so a
journal whose tags change needs its document rebuilt. These tests pin the
dispatch from journal tag events onto that re-index, the deliberate exclusion of
the rename, and the two behaviours that make the tag path differ from
``_index_journal_updated``: it must not overwrite ``updated_at``, and it must not
fabricate a fallback document.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infrastructure.events.outbox_repository import OutboxEvent
from app.infrastructure.search.journal_indexing_service import JournalIndexingService

# Every event type whose handling changes what tags a journal carries. Written
# out rather than imported from the production frozenset: importing it would make
# the parametrisation agree with the implementation by construction and the test
# could never fail.
TAG_REINDEX_EVENT_TYPES = [
    "JournalTagAssigned",
    "JournalTagRemoved",
    "JournalTagDeleted",
    "JournalTagMerged",
]

ROW_UPDATED_AT = "2026-03-01T09:00:00+00:00"
EVENT_OCCURRED_AT = datetime(2026, 6, 15, 10, 30, tzinfo=UTC)


def _tag_event(event_type: str, journal_id: int = 77) -> OutboxEvent:
    """Build an outbox event shaped like a published journal tag event."""
    return OutboxEvent(
        id=1,
        event_id=f"{event_type}-1",
        event_type=event_type,
        aggregate_id=journal_id,
        event_data={
            "journal_id": journal_id,
            "tag_id": "0f9a1d6e-1f2a-4c3b-8d4e-5f6a7b8c9d0e",
            "tag_name": "Hiking",
            "source": "ui",
            "changed_by": "ui",
        },
        occurred_at=EVENT_OCCURRED_AT,
        retry_count=0,
        created_at=EVENT_OCCURRED_AT,
    )


def _journal_document(journal_id: int = 77) -> dict[str, Any]:
    """A complete journal document as ``_fetch_complete_journal_data`` returns it."""
    return {
        "id": journal_id,
        "user_id": "user-1",
        "title": "Tagged journal",
        "content": "Body",
        "types": ["NOTE"],
        "contact_ids": [],
        "tag_ids": ["0f9a1d6e-1f2a-4c3b-8d4e-5f6a7b8c9d0e"],
        "entity_type": "journal",
        "updated_at": ROW_UPDATED_AT,
    }


@pytest.fixture
def meili_index() -> MagicMock:
    """A MeiliSearch index mock that reports itself as already configured."""
    index = MagicMock()
    index.primary_key = "id"
    index.get_filterable_attributes.return_value = ["user_id", "tag_ids"]
    return index


@pytest.fixture
def service(meili_index: MagicMock) -> JournalIndexingService:
    """Indexing service wired to a mock MeiliSearch client."""
    client = MagicMock()
    client.index.return_value = meili_index
    return JournalIndexingService(db_connection=MagicMock(), client=client)


class TestJournalTagReindexDispatch:
    """Journal tag events must reach the re-index path, and only the right ones."""

    @pytest.mark.parametrize("event_type", TAG_REINDEX_EVENT_TYPES)
    @pytest.mark.asyncio
    async def test_tag_event_reindexes_the_journal(
        self, service: JournalIndexingService, event_type: str
    ) -> None:
        """Each tag event rebuilds the affected journal's document.

        This is the test that fails when ``_SEARCH_EVENT_TYPES`` and the dispatch
        branch drift apart: a type subscribed but not dispatched is acked with
        only a debug log, leaving the index silently stale.
        """
        with patch.object(
            service, "_reindex_journal_for_tag_change", new=AsyncMock()
        ) as reindex:
            await service.process_event(_tag_event(event_type))

        reindex.assert_awaited_once()
        assert reindex.await_args is not None
        assert reindex.await_args.args[1].event_type == event_type

    @pytest.mark.asyncio
    async def test_rename_does_not_reindex(
        self, service: JournalIndexingService
    ) -> None:
        """A rename cannot change any document, so it must not re-index.

        Journal documents index ``tag_ids`` and never tag names, so renaming a tag
        leaves every document byte-identical. Pinned so that indexing tag names —
        a recorded follow-up — cannot ship without also adding the rename here.
        """
        with patch.object(
            service, "_reindex_journal_for_tag_change", new=AsyncMock()
        ) as reindex:
            await service.process_event(_tag_event("JournalTagRenamed"))

        reindex.assert_not_awaited()


class TestReindexJournalForTagChange:
    """The re-index itself differs from _index_journal_updated in two ways."""

    @pytest.mark.asyncio
    async def test_reindex_writes_the_current_document(
        self,
        service: JournalIndexingService,
        meili_index: MagicMock,
    ) -> None:
        """The document written is the freshly fetched one, tag ids and all."""
        document = _journal_document()
        with patch.object(
            service,
            "_fetch_complete_journal_data",
            new=AsyncMock(return_value=document),
        ):
            await service.process_event(_tag_event("JournalTagAssigned"))

        meili_index.update_documents.assert_called_once_with([document])

    @pytest.mark.asyncio
    async def test_reindex_preserves_the_row_updated_at(
        self,
        service: JournalIndexingService,
        meili_index: MagicMock,
    ) -> None:
        """The document keeps the row's ``updated_at``, not the event time.

        ``_index_journal_updated`` overwrites it with ``occurred_at``. A tag change
        does not touch ``journals.updated_at``, and ``updated_at`` is a sortable
        search attribute, so copying the event time would order search results by
        a value no row holds.
        """
        with patch.object(
            service,
            "_fetch_complete_journal_data",
            new=AsyncMock(return_value=_journal_document()),
        ):
            await service.process_event(_tag_event("JournalTagAssigned"))

        (written,) = meili_index.update_documents.call_args.args[0]
        assert written["updated_at"] == ROW_UPDATED_AT

    @pytest.mark.asyncio
    async def test_reindex_skips_a_journal_it_cannot_fetch(
        self,
        service: JournalIndexingService,
        meili_index: MagicMock,
    ) -> None:
        """A journal that no longer exists writes nothing and does not raise.

        The tag path has no fallback document to fall back to — a tag event carries
        no title or user id — and a journal deleted between the tag write and the
        relay has already had its document removed by ``JournalDeleted``.
        """
        with patch.object(
            service, "_fetch_complete_journal_data", new=AsyncMock(return_value=None)
        ):
            await service.process_event(_tag_event("JournalTagAssigned"))

        meili_index.update_documents.assert_not_called()
        meili_index.add_documents.assert_not_called()
