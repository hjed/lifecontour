"""POST /api/search/backfill/journals: real database, mocked MeiliSearch."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from meilisearch.models.document import DocumentsResults
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.search.journal_indexing_service import JournalIndexingService
from tests.integration.contact_seeding import TEST_USER_ID

pytestmark = pytest.mark.integration

ENDPOINT = "/api/search/backfill/journals"
CLIENT_FACTORY = (
    "app.infrastructure.search.search_backfill_service.get_meilisearch_client"
)


@pytest.fixture
def test_settings(test_settings):
    """Override test_settings to enable the maintenance endpoints."""
    return test_settings.model_copy(update={"enable_reindex_endpoint": True})


async def _seed_journal(connection: AsyncConnection, title: str) -> int:
    now = datetime.now(UTC)
    result = await connection.execute(
        text("""
            INSERT INTO journals (user_id, title, content,
                                  event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, 'body', :now, :now)
            RETURNING id
        """),
        {"user_id": TEST_USER_ID, "title": title, "now": now},
    )
    return int(result.scalar_one())


def _client(indexed: list[dict[str, Any]]) -> MagicMock:
    """A MeiliSearch client whose journals index holds ``indexed``."""
    client = MagicMock()
    client.wait_for_task.return_value = MagicMock(status="succeeded")
    index = client.index.return_value
    index.get_documents.return_value = DocumentsResults(
        {"results": indexed, "offset": 0, "limit": 1000, "total": len(indexed)}
    )
    index.add_documents.return_value = MagicMock(task_uid=1)
    return client


@pytest.mark.asyncio
async def test_only_absent_and_ownerless_journals_are_written(
    authenticated_client, async_connection: AsyncConnection
) -> None:
    owned = await _seed_journal(async_connection, "Owned")
    ownerless = await _seed_journal(async_connection, "Ownerless")
    absent = await _seed_journal(async_connection, "Absent")
    client = _client([{"id": owned, "user_id": TEST_USER_ID}, {"id": ownerless}])

    with patch(CLIENT_FACTORY, return_value=client):
        response = await authenticated_client.post(ENDPOINT)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["examined"] == 3
    assert body["documents_written"] == 2
    index = client.index.return_value
    written = index.add_documents.call_args[0][0]
    assert [document["id"] for document in written] == [ownerless, absent]
    index.delete_all_documents.assert_not_called()


@pytest.mark.asyncio
async def test_a_journal_that_could_not_be_built_is_a_503_naming_it(
    authenticated_client, async_connection: AsyncConnection
) -> None:
    journal_id = await _seed_journal(async_connection, "Unbuildable")

    with (
        patch(CLIENT_FACTORY, return_value=_client([])),
        patch.object(
            JournalIndexingService,
            "build_journal_document",
            side_effect=ValueError("bad row"),
        ),
    ):
        response = await authenticated_client.post(ENDPOINT)

    assert response.status_code == 503
    assert str(journal_id) in response.text


@pytest.mark.asyncio
async def test_endpoint_is_404_when_the_flag_is_off(
    async_connection: AsyncConnection, test_settings, test_user
) -> None:
    from tests.integration.conftest import _authenticated_client_context

    disabled = test_settings.model_copy(update={"enable_reindex_endpoint": False})
    async with _authenticated_client_context(
        async_connection, disabled, test_user
    ) as client:
        response = await client.post(ENDPOINT)

    assert response.status_code == 404
