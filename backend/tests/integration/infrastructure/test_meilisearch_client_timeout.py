"""The shared MeiliSearch client gives up on a server that stops answering.

Every SDK call is synchronous and runs in a worker thread, which cancelling the
caller cannot stop, so only an HTTP timeout releases the thread.
"""

import asyncio
import socket
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from meilisearch.errors import MeilisearchTimeoutError

from app.infrastructure.search.meilisearch_client import get_meilisearch_client

pytestmark = pytest.mark.integration


@pytest.fixture
def unresponsive_meilisearch() -> Iterator[None]:
    """Point the client at a server that accepts connections and never answers."""
    with socket.create_server(("127.0.0.1", 0)) as server:
        settings = MagicMock(
            meilisearch_url=f"http://127.0.0.1:{server.getsockname()[1]}",
            meilisearch_api_key="",
        )
        module = "app.infrastructure.search.meilisearch_client"
        get_meilisearch_client.cache_clear()
        with (
            patch(f"{module}.get_settings", return_value=settings),
            patch(f"{module}.HTTP_TIMEOUT_SECONDS", 1),
        ):
            yield
        get_meilisearch_client.cache_clear()


@pytest.mark.asyncio
@pytest.mark.usefixtures("unresponsive_meilisearch")
async def test_a_server_that_stops_answering_raises_a_timeout() -> None:
    index = get_meilisearch_client().index("contacts")

    with pytest.raises(MeilisearchTimeoutError):
        await asyncio.wait_for(
            asyncio.to_thread(index.get_filterable_attributes), timeout=30
        )
