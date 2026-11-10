"""
Unit tests for ReindexService.

Tests the bulk re-indexing service that rebuilds MeiliSearch indices
from PostgreSQL data.
"""

from collections.abc import Mapping
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from meilisearch.errors import MeilisearchError

from app.infrastructure.search.indexed_entities import ReindexIncompleteError
from app.infrastructure.search.journal_indexing_service import JournalIndexingService
from app.infrastructure.search.meilisearch_client import SearchTaskFailedError
from app.infrastructure.search.reindex_service import (
    ReindexResult,
    ReindexService,
    SingleReindexResult,
)
from app.infrastructure.search.search_indexer import SearchIndexer


def _builder(
    outcomes: Mapping[int, dict[str, object] | Exception | None],
) -> AsyncMock:
    """A document builder that answers per id, raising any exception it is given."""

    async def build(entity_id: int) -> dict[str, object] | None:
        outcome = outcomes[entity_id]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return AsyncMock(side_effect=build)


class TestReindexService:
    """Test cases for ReindexService."""

    @pytest.fixture
    def mock_meilisearch_client(self) -> MagicMock:
        """Create a mock MeiliSearch client."""
        client = MagicMock()
        # By default, every task succeeds
        client.wait_for_task.return_value = MagicMock(status="succeeded")
        return client

    @pytest.fixture
    def mock_db_connection(self) -> AsyncMock:
        """Create a mock async database connection."""
        return AsyncMock()

    @pytest.fixture
    def service(
        self, mock_meilisearch_client: MagicMock, mock_db_connection: AsyncMock
    ) -> ReindexService:
        """Create a ReindexService instance with mock dependencies."""
        with patch(
            "app.infrastructure.search.reindex_service.get_meilisearch_client",
            return_value=mock_meilisearch_client,
        ):
            return ReindexService(db_connection=mock_db_connection)

    def _setup_index_creation(self, mock_client: MagicMock) -> MagicMock:
        """Helper to set up mock index creation and return mock index."""
        mock_index = MagicMock()
        mock_client.index.return_value = mock_index

        mock_task = MagicMock()
        mock_task.task_uid = "create-task"
        mock_client.create_index.return_value = mock_task
        mock_index.update_settings.return_value = mock_task
        mock_index.add_documents.return_value = mock_task
        mock_index.delete_all_documents.return_value = mock_task
        return mock_index

    def _mock_id_pages(self, mock_conn: AsyncMock, ids: list[int]) -> None:
        """Set up the keyset query: one page of ids, then an empty page."""
        first_page = MagicMock()
        first_page.fetchall.return_value = [MagicMock(id=i) for i in ids]
        last_page = MagicMock()
        last_page.fetchall.return_value = []
        mock_conn.execute = AsyncMock(side_effect=[first_page, last_page])

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reindex_contacts_writes_the_indexers_documents(
        self,
        service: ReindexService,
        mock_meilisearch_client: MagicMock,
        mock_db_connection: AsyncMock,
    ) -> None:
        """Contacts are built by the indexer, so the two can never drift."""
        mock_index = self._setup_index_creation(mock_meilisearch_client)
        self._mock_id_pages(mock_db_connection, [1, 2])
        documents = {1: {"id": 1, "user_id": "a"}, 2: {"id": 2, "user_id": "a"}}

        with patch.object(SearchIndexer, "build_contact_document", _builder(documents)):
            result = await service.reindex_contacts()

        assert isinstance(result, SingleReindexResult)
        assert result.count == 2
        assert result.duration_ms >= 0
        mock_index.delete_all_documents.assert_called_once()
        mock_index.add_documents.assert_called_once_with(list(documents.values()))

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reindex_journals_writes_the_indexers_documents(
        self,
        service: ReindexService,
        mock_meilisearch_client: MagicMock,
        mock_db_connection: AsyncMock,
    ) -> None:
        """Journals are built by the indexer too."""
        mock_index = self._setup_index_creation(mock_meilisearch_client)
        self._mock_id_pages(mock_db_connection, [100])
        documents = {100: {"id": 100, "user_id": "a"}}

        with patch.object(
            JournalIndexingService, "build_journal_document", _builder(documents)
        ):
            result = await service.reindex_journals()

        assert result.count == 1
        mock_index.delete_all_documents.assert_called_once()
        mock_index.add_documents.assert_called_once_with(list(documents.values()))

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reindex_all_returns_combined_result(
        self,
        service: ReindexService,
    ) -> None:
        """Test that reindex_all returns a ReindexResult with both counts."""
        with (
            patch.object(
                service,
                "reindex_contacts",
                return_value=SingleReindexResult(count=5, duration_ms=100),
            ),
            patch.object(
                service,
                "reindex_journals",
                return_value=SingleReindexResult(count=3, duration_ms=50),
            ),
        ):
            result = await service.reindex_all()

        assert isinstance(result, ReindexResult)
        assert result.contacts_indexed == 5
        assert result.journals_indexed == 3
        assert result.duration_ms >= 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reindex_all_still_runs_journals_after_a_contact_failure(
        self,
        service: ReindexService,
    ) -> None:
        """Every entity is attempted, and every failure is reported together."""
        with (
            patch.object(
                service,
                "reindex_contacts",
                side_effect=ReindexIncompleteError({"contacts": [1]}),
            ),
            patch.object(
                service,
                "reindex_journals",
                side_effect=ReindexIncompleteError({"journals": [9]}),
            ) as reindex_journals,
            pytest.raises(ReindexIncompleteError) as raised,
        ):
            await service.reindex_all()

        reindex_journals.assert_awaited_once()
        assert raised.value.failed_ids == {"contacts": [1], "journals": [9]}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reindex_contacts_with_empty_database(
        self,
        service: ReindexService,
        mock_meilisearch_client: MagicMock,
        mock_db_connection: AsyncMock,
    ) -> None:
        """Test re-indexing contacts when the database has no contacts."""
        mock_index = self._setup_index_creation(mock_meilisearch_client)

        # Keyset pagination returns empty on first page
        id_result = MagicMock()
        id_result.fetchall.return_value = []
        mock_db_connection.execute = AsyncMock(return_value=id_result)

        result = await service.reindex_contacts()

        assert result.count == 0
        assert result.duration_ms >= 0
        mock_index.delete_all_documents.assert_called_once()
        mock_index.add_documents.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_contact_deleted_mid_run_is_skipped_without_error(
        self,
        service: ReindexService,
        mock_meilisearch_client: MagicMock,
        mock_db_connection: AsyncMock,
    ) -> None:
        """``None`` means the row has gone, which is not a failure."""
        mock_index = self._setup_index_creation(mock_meilisearch_client)
        self._mock_id_pages(mock_db_connection, [1, 2])
        alice = {"id": 1, "user_id": "a"}

        with patch.object(
            SearchIndexer, "build_contact_document", _builder({1: alice, 2: None})
        ):
            result = await service.reindex_contacts()

        assert result.count == 1
        mock_index.add_documents.assert_called_once_with([alice])

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_contact_that_cannot_be_built_fails_the_run_after_the_rest(
        self,
        service: ReindexService,
        mock_meilisearch_client: MagicMock,
        mock_db_connection: AsyncMock,
    ) -> None:
        """One bad contact must neither hide the failure nor stop the others."""
        mock_index = self._setup_index_creation(mock_meilisearch_client)
        self._mock_id_pages(mock_db_connection, [1, 2])
        bob = {"id": 2, "user_id": "a"}

        with (
            patch.object(
                SearchIndexer,
                "build_contact_document",
                _builder({1: ValueError("bad row"), 2: bob}),
            ),
            pytest.raises(ReindexIncompleteError) as raised,
        ):
            await service.reindex_contacts()

        assert raised.value.failed_ids == {"contacts": [1]}
        mock_index.add_documents.assert_called_once_with([bob])

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_document_meilisearch_rejects_fails_the_run(
        self,
        service: ReindexService,
        mock_meilisearch_client: MagicMock,
        mock_db_connection: AsyncMock,
    ) -> None:
        """The batch fails, the retry isolates the document, and the run reports it."""
        self._setup_index_creation(mock_meilisearch_client)
        self._mock_id_pages(mock_db_connection, [1])
        mock_meilisearch_client.wait_for_task.side_effect = [
            MagicMock(status="succeeded"),  # settings
            MagicMock(status="succeeded"),  # delete all
            MagicMock(status="failed", error={"code": "bad"}),  # batch
            MagicMock(status="failed", error={"code": "bad"}),  # retry
        ]

        with (
            patch.object(
                SearchIndexer,
                "build_contact_document",
                _builder({1: {"id": 1, "user_id": "a"}}),
            ),
            pytest.raises(ReindexIncompleteError) as raised,
        ):
            await service.reindex_contacts()

        assert raised.value.failed_ids == {"contacts": [1]}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_a_failed_delete_stops_the_run(
        self,
        service: ReindexService,
        mock_meilisearch_client: MagicMock,
        mock_db_connection: AsyncMock,
    ) -> None:
        """Adding onto an index that did not clear would hide the failure."""
        mock_index = self._setup_index_creation(mock_meilisearch_client)
        mock_meilisearch_client.wait_for_task.side_effect = [
            MagicMock(status="succeeded"),  # settings
            MagicMock(status="failed", error={"code": "bad"}),  # delete all
        ]

        with pytest.raises(SearchTaskFailedError):
            await service.reindex_contacts()

        mock_index.add_documents.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ensure_index_exists_creates_index_when_missing(
        self,
        service: ReindexService,
        mock_meilisearch_client: MagicMock,
    ) -> None:
        """Test that _ensure_index_exists creates the index when it doesn't exist."""
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index

        # get_stats raises MeilisearchError — index doesn't exist
        mock_index.get_stats.side_effect = MeilisearchError("index not found")

        mock_task = MagicMock()
        mock_task.task_uid = "create-task"
        mock_meilisearch_client.create_index.return_value = mock_task
        mock_index.update_settings.return_value = mock_task

        test_settings = {"searchableAttributes": ["name"]}
        await service._ensure_index_exists("test_index", test_settings)

        # Verify index was created
        mock_meilisearch_client.create_index.assert_called_once_with(
            "test_index", {"primaryKey": "id"}
        )
        # Verify settings were applied
        mock_index.update_settings.assert_called_once_with(test_settings)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ensure_index_exists_updates_settings_on_existing_index(
        self,
        service: ReindexService,
        mock_meilisearch_client: MagicMock,
    ) -> None:
        """Test that _ensure_index_exists updates settings even when index exists."""
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index

        # get_stats succeeds — index already exists
        mock_index.get_stats.return_value = {"numberOfDocuments": 10}

        mock_task = MagicMock()
        mock_task.task_uid = "update-task"
        mock_index.update_settings.return_value = mock_task

        test_settings = {"searchableAttributes": ["name"]}
        await service._ensure_index_exists("test_index", test_settings)

        # Verify index was NOT created (already exists)
        mock_meilisearch_client.create_index.assert_not_called()
        # Verify settings were still applied
        mock_index.update_settings.assert_called_once_with(test_settings)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reindex_result_dataclass(self) -> None:
        """Test ReindexResult dataclass properties."""
        result = ReindexResult(
            contacts_indexed=10, journals_indexed=5, duration_ms=1234
        )
        assert result.contacts_indexed == 10
        assert result.journals_indexed == 5
        assert result.duration_ms == 1234

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_single_reindex_result_dataclass(self) -> None:
        """Test SingleReindexResult dataclass properties."""
        result = SingleReindexResult(count=10, duration_ms=500)
        assert result.count == 10
        assert result.duration_ms == 500
