"""
Integration tests for the search re-index endpoint.

Tests the POST /api/search/reindex endpoint with a real database
and mocked MeiliSearch client to verify that all contacts and journals
are read from PostgreSQL and pushed to the search index.
"""

from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@pytest_asyncio.fixture
async def sample_contacts(async_connection: AsyncConnection) -> list[int]:
    """Create sample contacts in the database and return their IDs."""
    ids = []
    for i in range(3):
        result = await async_connection.execute(
            text("""
                INSERT INTO contacts (first_name, last_name)
                VALUES (:first_name, :last_name)
                RETURNING id
            """),
            {"first_name": f"Contact{i + 1}", "last_name": f"Last{i + 1}"},
        )
        row = result.fetchone()
        assert row is not None
        ids.append(int(row[0]))
    return ids


@pytest_asyncio.fixture
async def sample_journals(async_connection: AsyncConnection) -> list[int]:
    """Create sample journals in the database and return their IDs."""
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    ids = []
    for i in range(2):
        result = await async_connection.execute(
            text("""
                INSERT INTO journals (user_id, title, content,
                                      event_date_range_start, event_date_range_end)
                VALUES (:user_id, :title, :content, :start, :end)
                RETURNING id
            """),
            {
                "user_id": "test-user-123",
                "title": f"Journal {i + 1}",
                "content": f"Content for journal {i + 1}",
                "start": now,
                "end": now + timedelta(hours=1),
            },
        )
        row = result.fetchone()
        assert row is not None
        ids.append(int(row[0]))
    return ids


def _make_mock_meilisearch_client() -> MagicMock:
    """Create a mock MeiliSearch client with all required methods."""
    client = MagicMock()
    mock_index = MagicMock()
    client.index.return_value = mock_index

    mock_task = MagicMock()
    mock_task.task_uid = "test-task"
    mock_index.delete_all_documents.return_value = mock_task
    mock_index.add_documents.return_value = mock_task
    mock_index.get_stats.return_value = {"numberOfDocuments": 0}

    client.create_index.return_value = mock_task
    client.wait_for_task.return_value = None

    return client


@pytest.mark.integration
class TestReindexEndpoint:
    """Integration tests for the re-index API endpoint."""

    @pytest.mark.asyncio
    async def test_reindex_all_indexes_contacts_and_journals(
        self,
        authenticated_client,
        sample_contacts: list[int],
        sample_journals: list[int],
    ) -> None:
        """Test that POST /api/search/reindex indexes all contacts and journals."""
        mock_client = _make_mock_meilisearch_client()

        with patch(
            "app.infrastructure.search.reindex_service.get_meilisearch_client",
            return_value=mock_client,
        ):
            response = await authenticated_client.post("/api/search/reindex")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["contacts_indexed"] == 3
        assert data["journals_indexed"] == 2
        assert data["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_reindex_contacts_only(
        self,
        authenticated_client,
        sample_contacts: list[int],
        sample_journals: list[int],
    ) -> None:
        """Test re-indexing only contacts via entity_type parameter."""
        mock_client = _make_mock_meilisearch_client()

        with patch(
            "app.infrastructure.search.reindex_service.get_meilisearch_client",
            return_value=mock_client,
        ):
            response = await authenticated_client.post(
                "/api/search/reindex?entity_type=contacts"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["contacts_indexed"] == 3
        assert data["journals_indexed"] == 0

    @pytest.mark.asyncio
    async def test_reindex_journals_only(
        self,
        authenticated_client,
        sample_contacts: list[int],
        sample_journals: list[int],
    ) -> None:
        """Test re-indexing only journals via entity_type parameter."""
        mock_client = _make_mock_meilisearch_client()

        with patch(
            "app.infrastructure.search.reindex_service.get_meilisearch_client",
            return_value=mock_client,
        ):
            response = await authenticated_client.post(
                "/api/search/reindex?entity_type=journals"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["contacts_indexed"] == 0
        assert data["journals_indexed"] == 2

    @pytest.mark.asyncio
    async def test_reindex_with_empty_database(
        self,
        authenticated_client,
    ) -> None:
        """Test re-indexing with no data in the database."""
        mock_client = _make_mock_meilisearch_client()

        with patch(
            "app.infrastructure.search.reindex_service.get_meilisearch_client",
            return_value=mock_client,
        ):
            response = await authenticated_client.post("/api/search/reindex")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["contacts_indexed"] == 0
        assert data["journals_indexed"] == 0

    @pytest.mark.asyncio
    async def test_reindex_contacts_includes_contact_methods_and_tags(
        self,
        authenticated_client,
        async_connection: AsyncConnection,
    ) -> None:
        """Test that re-indexed contacts include methods, notes, and tags."""
        # Create a contact with methods and tags
        result = await async_connection.execute(
            text("""
                INSERT INTO contacts (first_name, last_name, company, job_title)
                VALUES ('Alice', 'Wonderland', 'Acme Corp', 'Engineer')
                RETURNING id
            """)
        )
        contact_row = result.fetchone()
        assert contact_row is not None
        contact_id = int(contact_row[0])

        # Add a contact method
        await async_connection.execute(
            text("""
                INSERT INTO contact_methods
                    (contact_id, method_type, value, label, is_primary)
                VALUES (:cid, 'email', 'alice@acme.com', 'Work', true)
            """),
            {"cid": contact_id},
        )

        # Add a tag
        tag_result = await async_connection.execute(
            text("INSERT INTO tags (name) VALUES ('engineering') RETURNING id")
        )
        tag_row = tag_result.fetchone()
        assert tag_row is not None
        tag_id = int(tag_row[0])
        await async_connection.execute(
            text("""
                INSERT INTO contact_tags (contact_id, tag_id)
                VALUES (:cid, :tid)
            """),
            {"cid": contact_id, "tid": tag_id},
        )

        # Add a note
        await async_connection.execute(
            text("""
                INSERT INTO contact_notes (contact_id, content)
                VALUES (:cid, 'Brilliant engineer')
            """),
            {"cid": contact_id},
        )

        mock_client = _make_mock_meilisearch_client()
        mock_index = mock_client.index.return_value

        with patch(
            "app.infrastructure.search.reindex_service.get_meilisearch_client",
            return_value=mock_client,
        ):
            response = await authenticated_client.post(
                "/api/search/reindex?entity_type=contacts"
            )

        assert response.status_code == 200
        assert response.json()["contacts_indexed"] == 1

        # Verify the document pushed to MeiliSearch has the right data
        add_docs_call = mock_index.add_documents.call_args
        assert add_docs_call is not None
        documents = add_docs_call[0][0]
        assert len(documents) == 1

        doc = documents[0]
        assert doc["first_name"] == "Alice"
        assert doc["last_name"] == "Wonderland"
        assert doc["company"] == "Acme Corp"
        assert doc["email"] == "alice@acme.com"
        assert doc["emails"] == ["alice@acme.com"]
        assert doc["tags"] == ["engineering"]
        assert doc["notes_content"] == "Brilliant engineer"
        assert doc["entity_type"] == "contact"

    @pytest.mark.asyncio
    async def test_reindex_requires_authentication(
        self,
        async_connection: AsyncConnection,
        test_settings,
    ) -> None:
        """Test that the reindex endpoint requires authentication."""
        from httpx import ASGITransport, AsyncClient

        from app.main import create_app

        app = create_app(settings=test_settings)
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/search/reindex")

        # Without session cookie, we expect a redirect or 401
        assert response.status_code in (302, 401, 403)
