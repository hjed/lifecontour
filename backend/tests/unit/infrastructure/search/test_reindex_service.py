"""
Unit tests for ReindexService.

Tests the bulk re-indexing service that rebuilds MeiliSearch indices
from PostgreSQL data.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from meilisearch.errors import MeilisearchError

from app.infrastructure.search.reindex_service import (
    ReindexResult,
    ReindexService,
    SingleReindexResult,
)


class TestReindexService:
    """Test cases for ReindexService."""

    @pytest.fixture
    def mock_meilisearch_client(self) -> MagicMock:
        """Create a mock MeiliSearch client."""
        client = MagicMock()
        # By default, wait_for_task succeeds
        client.wait_for_task.return_value = None
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

    def _mock_contact_rows(self, mock_conn: AsyncMock, count: int = 2) -> None:
        """Set up mock DB to return contact rows with keyset pagination."""
        contact_rows = []
        for i in range(count):
            row = MagicMock()
            row.id = i + 1
            row.first_name = f"Contact{i + 1}"
            row.last_name = f"Last{i + 1}"
            row.middle_name = None
            row.nick_name = None
            row.company = None
            row.job_title = None
            row.is_favourite = False
            row.created_at = MagicMock()
            row.created_at.isoformat.return_value = "2024-01-01T00:00:00"
            row.updated_at = MagicMock()
            row.updated_at.isoformat.return_value = "2024-01-01T00:00:00"
            contact_rows.append(row)

        # Keyset pagination: first page returns all IDs, second page is empty
        contact_ids = [MagicMock(id=i + 1) for i in range(count)]
        id_result_page1 = MagicMock()
        id_result_page1.fetchall.return_value = contact_ids
        id_result_page2 = MagicMock()
        id_result_page2.fetchall.return_value = []

        methods_result = MagicMock()
        methods_result.fetchall.return_value = []
        notes_result = MagicMock()
        notes_result.fetchall.return_value = []
        tags_result = MagicMock()
        tags_result.fetchall.return_value = []

        # Build execute sequence:
        # 1. keyset page 1 (returns IDs)
        # 2-5 per contact: info, methods, notes, tags
        # N+1. keyset page 2 (empty - terminates loop)
        execute_returns = [id_result_page1]
        for i in range(count):
            info_result = MagicMock()
            info_result.fetchone.return_value = contact_rows[i]
            execute_returns.extend(
                [info_result, methods_result, notes_result, tags_result]
            )
        execute_returns.append(id_result_page2)

        mock_conn.execute = AsyncMock(side_effect=execute_returns)

    def _mock_journal_rows(self, mock_conn: AsyncMock, count: int = 2) -> None:
        """Set up mock DB to return journal rows with keyset pagination."""
        journal_rows = []
        for i in range(count):
            row = MagicMock()
            row.id = i + 100
            row.user_id = 1
            row.title = f"Journal {i + 1}"
            row.content = f"Content {i + 1}"
            row.event_date_range_start = None
            row.event_date_range_end = None
            row.parent_id = None
            row.created_at = MagicMock()
            row.created_at.isoformat.return_value = "2024-01-01T00:00:00"
            row.updated_at = MagicMock()
            row.updated_at.isoformat.return_value = "2024-01-01T00:00:00"
            journal_rows.append(row)

        journal_ids = [MagicMock(id=i + 100) for i in range(count)]
        id_result_page1 = MagicMock()
        id_result_page1.fetchall.return_value = journal_ids
        id_result_page2 = MagicMock()
        id_result_page2.fetchall.return_value = []

        execute_returns = [id_result_page1]
        for i in range(count):
            info_result = MagicMock()
            info_result.fetchone.return_value = journal_rows[i]
            types_result = MagicMock()
            types_result.fetchone.return_value = None  # No special types
            contacts_result = MagicMock()
            contacts_result.fetchall.return_value = []
            tags_result = MagicMock()
            tags_result.fetchall.return_value = []
            execute_returns.extend(
                [info_result, types_result, contacts_result, tags_result]
            )
        execute_returns.append(id_result_page2)

        mock_conn.execute = AsyncMock(side_effect=execute_returns)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reindex_contacts_fetches_all_and_pushes_to_meilisearch(
        self,
        service: ReindexService,
        mock_meilisearch_client: MagicMock,
        mock_db_connection: AsyncMock,
    ) -> None:
        """Test that reindex_contacts fetches all contacts and indexes them."""
        mock_index = self._setup_index_creation(mock_meilisearch_client)
        self._mock_contact_rows(mock_db_connection, count=2)

        with patch(
            "app.infrastructure.search.reindex_service.get_index_name",
            return_value="pms_contacts",
        ):
            result = await service.reindex_contacts()

        assert isinstance(result, SingleReindexResult)
        assert result.count == 2
        assert result.duration_ms >= 0
        mock_index.delete_all_documents.assert_called_once()
        mock_index.add_documents.assert_called_once()
        docs = mock_index.add_documents.call_args[0][0]
        assert len(docs) == 2
        assert docs[0]["first_name"] == "Contact1"
        assert docs[1]["first_name"] == "Contact2"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reindex_journals_fetches_all_and_pushes_to_meilisearch(
        self,
        service: ReindexService,
        mock_meilisearch_client: MagicMock,
        mock_db_connection: AsyncMock,
    ) -> None:
        """Test that reindex_journals fetches all journals and indexes them."""
        mock_index = self._setup_index_creation(mock_meilisearch_client)
        self._mock_journal_rows(mock_db_connection, count=2)

        with patch(
            "app.infrastructure.search.reindex_service.get_index_name",
            return_value="pms_journals",
        ):
            result = await service.reindex_journals()

        assert isinstance(result, SingleReindexResult)
        assert result.count == 2
        assert result.duration_ms >= 0
        mock_index.delete_all_documents.assert_called_once()
        mock_index.add_documents.assert_called_once()
        docs = mock_index.add_documents.call_args[0][0]
        assert len(docs) == 2
        assert docs[0]["title"] == "Journal 1"
        assert docs[1]["title"] == "Journal 2"

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

        with patch(
            "app.infrastructure.search.reindex_service.get_index_name",
            return_value="pms_contacts",
        ):
            result = await service.reindex_contacts()

        assert result.count == 0
        assert result.duration_ms >= 0
        mock_index.delete_all_documents.assert_called_once()
        mock_index.add_documents.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reindex_contacts_skips_unfetchable_contacts(
        self,
        service: ReindexService,
        mock_meilisearch_client: MagicMock,
        mock_db_connection: AsyncMock,
    ) -> None:
        """Test that contacts that can't be fetched are skipped."""
        mock_index = self._setup_index_creation(mock_meilisearch_client)

        # Keyset page 1: returns 2 IDs
        id_result_page1 = MagicMock()
        id_result_page1.fetchall.return_value = [
            MagicMock(id=1),
            MagicMock(id=2),
        ]
        # Keyset page 2: empty (terminates)
        id_result_page2 = MagicMock()
        id_result_page2.fetchall.return_value = []

        # Contact 1: has data
        contact_row = MagicMock()
        contact_row.id = 1
        contact_row.first_name = "Alice"
        contact_row.last_name = "Smith"
        contact_row.middle_name = None
        contact_row.nick_name = None
        contact_row.company = None
        contact_row.job_title = None
        contact_row.is_favourite = False
        contact_row.created_at = MagicMock()
        contact_row.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        contact_row.updated_at = MagicMock()
        contact_row.updated_at.isoformat.return_value = "2024-01-01T00:00:00"

        info_result1 = MagicMock()
        info_result1.fetchone.return_value = contact_row
        empty_list_result = MagicMock()
        empty_list_result.fetchall.return_value = []

        # Contact 2: not found
        info_result2 = MagicMock()
        info_result2.fetchone.return_value = None

        mock_db_connection.execute = AsyncMock(
            side_effect=[
                id_result_page1,
                info_result1,
                empty_list_result,
                empty_list_result,
                empty_list_result,  # contact 1
                info_result2,  # contact 2 - not found, stops here
                id_result_page2,  # keyset page 2 - terminates
            ]
        )

        with patch(
            "app.infrastructure.search.reindex_service.get_index_name",
            return_value="pms_contacts",
        ):
            result = await service.reindex_contacts()

        assert result.count == 1
        docs = mock_index.add_documents.call_args[0][0]
        assert len(docs) == 1
        assert docs[0]["first_name"] == "Alice"

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
