"""Integration tests for conditional writes through the MCP tools.

MCP tools have no HTTP headers, so the token REST carries in ``ETag`` /
``If-Match`` travels here as ``version`` on a read and ``expected_version`` on
a write. The precondition itself is the same one the REST surface uses; these
tests cover the parameter contract and the refusal an AI client sees.

A concurrent writer is simulated by nudging the row's ``updated_at`` — see the
REST suite for why a second real write cannot move the tag under this fixture.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.contact_seeding import seed_contact
from tests.integration.mcp.http_helpers import (
    call_mcp_tool,
)
from tests.integration.tasks.task_seeding import USER_ID


async def call_tool(client: Any, name: str, arguments: dict[str, Any]) -> Any:
    """Call one MCP tool and return its decoded payload."""
    return await call_mcp_tool(client, name, arguments)


async def simulate_concurrent_write(
    connection: AsyncConnection, table: str, row_id: int
) -> None:
    """Move a row's ``updated_at`` on, as another writer's commit would."""
    await connection.execute(
        text(
            f"UPDATE {table} SET updated_at = updated_at + interval '1 second' "  # noqa: S608 - fixed table names
            "WHERE id = :row_id"
        ),
        {"row_id": row_id},
    )


@pytest.fixture
async def journal_id(clean_database: AsyncConnection) -> int:
    now = datetime.now(UTC)
    result = await clean_database.execute(
        text(
            """
            INSERT INTO journals (user_id, title, content,
                                  event_date_range_start, event_date_range_end)
            VALUES (:user_id, 'Original title', 'Original content', :start, :end)
            RETURNING id
            """
        ),
        {"user_id": USER_ID, "start": now, "end": now + timedelta(hours=1)},
    )
    return int(result.scalar_one())


@pytest.fixture
async def contact_id(clean_database: AsyncConnection) -> int:
    return await seed_contact(clean_database, first_name="Ada", last_name="Lovelace")


@pytest.mark.integration
class TestJournalVersions:
    """``get_journal`` / ``update_journal_entry`` version round trip."""

    @pytest.mark.asyncio
    async def test_get_journal_reports_a_version(
        self, authenticated_lifespan_client, journal_id: int
    ):
        async with authenticated_lifespan_client() as client:
            payload = await call_tool(client, "get_journal", {"journal_id": journal_id})

        assert payload["version"]

    @pytest.mark.asyncio
    async def test_matching_version_is_written(
        self, authenticated_lifespan_client, journal_id: int
    ):
        async with authenticated_lifespan_client() as client:
            read = await call_tool(client, "get_journal", {"journal_id": journal_id})

            payload = await call_tool(
                client,
                "update_journal_entry",
                {
                    "journal_id": journal_id,
                    "request": {
                        "title": "Updated title",
                        "expected_version": read["version"],
                    },
                },
            )

        assert payload["title"] == "Updated title"

    @pytest.mark.asyncio
    async def test_stale_version_is_refused_with_a_recoverable_answer(
        self, authenticated_lifespan_client, journal_id: int, clean_database
    ):
        """The refusal has to tell the model what to do, not just that it failed."""
        async with authenticated_lifespan_client() as client:
            read = await call_tool(client, "get_journal", {"journal_id": journal_id})
            await simulate_concurrent_write(clean_database, "journals", journal_id)

            payload = await call_tool(
                client,
                "update_journal_entry",
                {
                    "journal_id": journal_id,
                    "request": {
                        "title": "Updated title",
                        "expected_version": read["version"],
                    },
                },
            )

            assert payload["code"] == "PRECONDITION_FAILED"
            assert "re-read" in payload["message"].lower()
            after = await call_tool(client, "get_journal", {"journal_id": journal_id})

        # The version to retry with is in the refusal, and nothing was written.
        assert payload["current_version"] == after["version"]
        assert after["title"] == "Original title"

    @pytest.mark.asyncio
    async def test_omitted_version_writes_as_before(
        self, authenticated_lifespan_client, journal_id: int, clean_database
    ):
        """The parameter is optional: existing AI callers are unaffected."""
        await simulate_concurrent_write(clean_database, "journals", journal_id)

        async with authenticated_lifespan_client() as client:
            payload = await call_tool(
                client,
                "update_journal_entry",
                {"journal_id": journal_id, "request": {"title": "Updated title"}},
            )

        assert payload["title"] == "Updated title"

    @pytest.mark.asyncio
    async def test_stale_version_refuses_before_replacing_tags(
        self, authenticated_lifespan_client, journal_id: int, clean_database
    ):
        """A conflict on a composite update must not half-apply it.

        ``update_journal_entry`` replaces types, tags and relationships in the
        same unit of work as the core fields, so a refusal has to happen before
        any of them are touched.
        """
        async with authenticated_lifespan_client() as client:
            read = await call_tool(client, "get_journal", {"journal_id": journal_id})
            await simulate_concurrent_write(clean_database, "journals", journal_id)

            await call_tool(
                client,
                "update_journal_entry",
                {
                    "journal_id": journal_id,
                    "request": {
                        "tags": ["should-not-exist"],
                        "expected_version": read["version"],
                    },
                },
            )

            after = await call_tool(client, "get_journal", {"journal_id": journal_id})

        assert after["tags"] == []


@pytest.mark.integration
class TestContactVersions:
    """``get_contact`` / ``update_contact`` version round trip."""

    @pytest.mark.asyncio
    async def test_get_contact_reports_a_version(
        self, authenticated_lifespan_client, contact_id: int
    ):
        async with authenticated_lifespan_client() as client:
            payload = await call_tool(client, "get_contact", {"contact_id": contact_id})

        assert payload["version"]

    @pytest.mark.asyncio
    async def test_matching_version_is_written(
        self, authenticated_lifespan_client, contact_id: int
    ):
        async with authenticated_lifespan_client() as client:
            read = await call_tool(client, "get_contact", {"contact_id": contact_id})

            payload = await call_tool(
                client,
                "update_contact",
                {
                    "request": {
                        "contact_id": contact_id,
                        "first_name": "Augusta",
                        "expected_version": read["version"],
                    }
                },
            )

        assert payload["name"].startswith("Augusta")

    @pytest.mark.asyncio
    async def test_stale_version_is_refused(
        self, authenticated_lifespan_client, contact_id: int, clean_database
    ):
        async with authenticated_lifespan_client() as client:
            read = await call_tool(client, "get_contact", {"contact_id": contact_id})
            await simulate_concurrent_write(clean_database, "contacts", contact_id)

            payload = await call_tool(
                client,
                "update_contact",
                {
                    "request": {
                        "contact_id": contact_id,
                        "first_name": "Augusta",
                        "expected_version": read["version"],
                    }
                },
            )

            after = await call_tool(client, "get_contact", {"contact_id": contact_id})

        assert payload["code"] == "PRECONDITION_FAILED"
        assert payload["current_version"] == after["version"]
        assert after["name"].startswith("Ada")
