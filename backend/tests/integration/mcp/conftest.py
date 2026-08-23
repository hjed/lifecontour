"""Fixtures shared by the mounted-MCP integration tests."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from meilisearch import Client as MeiliSearchClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.config import get_settings
from app.infrastructure.events.outbox_repository import OutboxEvent
from app.infrastructure.search.journal_indexing_service import JournalIndexingService
from app.infrastructure.search.meilisearch_client import (
    get_index_name,
    get_meilisearch_client,
)


@pytest.fixture
def app_uses_test_meilisearch(monkeypatch: pytest.MonkeyPatch, test_settings):
    """Point the app's own ``SearchService`` at the test MeiliSearch.

    The mounted app builds ``SearchService()`` from the cached ``get_settings()``
    (environment) and the lru_cached client factory, so without this a real search
    through the MCP tools would hit the default dev URL and fail.
    """
    monkeypatch.setenv("MEILISEARCH_URL", test_settings.meilisearch_url)
    monkeypatch.setenv("MEILISEARCH_API_KEY", test_settings.meilisearch_api_key)
    # Both the settings and the client factory are lru_cached, so an earlier
    # test may have pinned the default URL; clear both before and after.
    get_settings.cache_clear()
    get_meilisearch_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_meilisearch_client.cache_clear()


@pytest_asyncio.fixture
async def index_journal(
    clean_database: AsyncConnection, test_settings, app_uses_test_meilisearch
) -> Callable[[int], Awaitable[None]]:
    """Index one already-inserted journal into the test MeiliSearch.

    Journals written straight to SQL in a test are never indexed (indexing is
    event-driven), and the index is not rolled back with the database, so this
    empties the journals index first — stale documents from earlier sessions
    reuse the same ids — and then indexes on demand through the real
    ``JournalIndexingService`` so documents look exactly as they do in prod.
    """
    client = MeiliSearchClient(
        url=test_settings.meilisearch_url, api_key=test_settings.meilisearch_api_key
    )
    service = JournalIndexingService(db_connection=clean_database, client=client)
    index_name = get_index_name("journals")
    service._ensure_journals_index_exists(index_name)
    task = client.index(index_name).delete_all_documents()
    client.wait_for_task(task.task_uid)

    async def _index(journal_id: int) -> None:
        now = datetime.now(UTC)
        await service.process_event(
            OutboxEvent(
                id=journal_id,
                event_id=f"test-index-{journal_id}",
                aggregate_id=journal_id,
                event_type="JournalCreated",
                event_data={"journal_id": journal_id},
                occurred_at=now,
                retry_count=0,
                created_at=now,
            )
        )

    return _index
