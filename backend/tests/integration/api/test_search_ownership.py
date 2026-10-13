"""Search answers the acting user with their own documents only.

Two users each own a contact and a journal that match the same query. Both
users' documents are really indexed into the test MeiliSearch, so a missing
owner filter would return the other user's document. Acting as the test user,
every search surface must return the test user's documents (the positive
control, which proves the query matches at all) and nothing of the other
user's. The surfaces are the REST contact, global and suggestion endpoints and
the MCP ``search_contacts`` and ``global_search`` tools.

The other user's documents are recognised by a surname or title word that only
they carry, so the check holds whatever shape each surface renders a hit in.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.contact_seeding import OTHER_USER_ID, TEST_USER_ID, seed_contact
from tests.integration.mcp.http_helpers import call_mcp_tool

QUERY = "Zephyrine"
# Each owner's documents carry a word only they have.
MINE = "Albatross"
THEIRS = "Cormorant"


async def _insert_journal(conn: AsyncConnection, *, user_id: str, title: str) -> int:
    start = datetime(2025, 10, 13, 9, tzinfo=UTC)
    result = await conn.execute(
        text("""
            INSERT INTO journals
                (user_id, title, content, event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, 'A walk.', :start, :end)
            RETURNING id
        """),
        {
            "user_id": user_id,
            "title": title,
            "start": start,
            "end": start + timedelta(hours=2),
        },
    )
    return int(result.scalar_one())


@pytest_asyncio.fixture
async def both_users_indexed(
    clean_database: AsyncConnection,
    index_contact: Callable[[int], Awaitable[None]],
    index_journal: Callable[[int], Awaitable[None]],
) -> None:
    """A matching contact and journal for each user, all of them indexed."""
    for user_id, word in ((TEST_USER_ID, MINE), (OTHER_USER_ID, THEIRS)):
        contact_id = await seed_contact(
            clean_database, user_id=user_id, first_name=QUERY, last_name=word
        )
        await index_contact(contact_id)
        journal_id = await _insert_journal(
            clean_database, user_id=user_id, title=f"{QUERY} {word}"
        )
        await index_journal(journal_id)


def _assert_only_mine(body: str) -> None:
    assert MINE in body, "the caller's own document was not found"
    assert THEIRS not in body, "another user's document was returned"


@pytest.mark.integration
@pytest.mark.meilisearch
@pytest.mark.usefixtures("both_users_indexed")
class TestRestSearchOwnership:
    @pytest.mark.asyncio
    async def test_contact_search(self, authenticated_lifespan_client: Any) -> None:
        async with authenticated_lifespan_client() as client:
            response = await client.get("/api/search/contacts", params={"q": QUERY})

        assert response.status_code == 200, response.text
        assert len(response.json()["data"]) == 1
        _assert_only_mine(response.text)

    @pytest.mark.asyncio
    async def test_global_search(self, authenticated_lifespan_client: Any) -> None:
        async with authenticated_lifespan_client() as client:
            response = await client.get("/api/search/global", params={"q": QUERY})

        assert response.status_code == 200, response.text
        assert response.json()["meta"]["results_by_type"] == {
            "contact": 1,
            "journal": 1,
        }
        _assert_only_mine(response.text)

    @pytest.mark.asyncio
    async def test_search_suggestions(self, authenticated_lifespan_client: Any) -> None:
        """Suggestions are not implemented yet, so there is no positive control."""
        async with authenticated_lifespan_client() as client:
            response = await client.get("/api/search/suggestions", params={"q": QUERY})

        assert response.status_code == 200, response.text
        assert THEIRS not in response.text


@pytest.mark.integration
@pytest.mark.meilisearch
@pytest.mark.usefixtures("both_users_indexed")
class TestMcpSearchOwnership:
    @pytest.mark.asyncio
    async def test_search_contacts(self, authenticated_lifespan_client: Any) -> None:
        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(client, "search_contacts", {"query": QUERY})

        assert "error" not in payload, payload
        _assert_only_mine(str(payload))

    @pytest.mark.asyncio
    async def test_global_search(self, authenticated_lifespan_client: Any) -> None:
        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(client, "global_search", {"query": QUERY})

        assert "error" not in payload, payload
        _assert_only_mine(str(payload))
