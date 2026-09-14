"""Integration tests for MCP browse_journals_by_date_window tool."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.mcp.http_helpers import (
    call_mcp_tool,
)


async def _insert_journal(
    conn: AsyncConnection,
    *,
    user_id: str,
    title: str,
    start: datetime,
    end: datetime | None = None,
) -> int:
    """Insert a journal row and return its ID."""
    if end is None:
        end = start + timedelta(hours=1)
    result = await conn.execute(
        text("""
            INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, :content, :start, :end)
            RETURNING id
        """),
        {
            "user_id": user_id,
            "title": title,
            "content": f"Content for {title}",
            "start": start,
            "end": end,
        },
    )
    row = result.fetchone()
    assert row is not None
    return int(row[0])


class TestBrowseJournalsByDateWindowIntegration:
    """Integration tests for the browse_journals_by_date_window MCP tool."""

    @pytest.mark.asyncio
    async def test_tool_is_registered(self) -> None:
        """The tool must appear in the MCP tool listing."""
        from fastmcp import FastMCP
        from fastmcp.client import Client

        from app.mcp.domains.journals.tools import register_journal_tools

        mcp: FastMCP[None] = FastMCP("TestServer")
        register_journal_tools(mcp)

        async with Client(mcp) as client:
            tools = await client.list_tools()
            tool_names = [t.name for t in tools]
            assert "browse_journals_by_date_window" in tool_names

    @pytest.mark.asyncio
    async def test_basic_window_query(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        """Creates journals across dates and verifies the window returns only journals within range."""
        now = datetime.now(UTC)
        today = now.date()

        # Journal inside the default window (today)
        await _insert_journal(
            clean_database,
            user_id="test-user-123",
            title="Today Journal",
            start=datetime.combine(today, datetime.min.time()).replace(tzinfo=UTC),
        )

        # Journal outside the window (30 days ago)
        old_date = today - timedelta(days=30)
        await _insert_journal(
            clean_database,
            user_id="test-user-123",
            title="Old Journal",
            start=datetime.combine(old_date, datetime.min.time()).replace(tzinfo=UTC),
        )

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "browse_journals_by_date_window",
                {
                    "anchor_date": today.isoformat(),
                },
                request_id=2,
            )

            assert "error" not in payload
            assert payload["total_count"] == 1
            titles = [r["title"] for r in payload["results"]]
            assert "Today Journal" in titles
            assert "Old Journal" not in titles

    @pytest.mark.asyncio
    async def test_empty_window(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        """Querying a window with no journals returns empty results."""
        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "browse_journals_by_date_window",
                {
                    "anchor_date": "2020-01-15",
                    "days_back": 1,
                    "days_forward": 1,
                },
                request_id=2,
            )

            assert "error" not in payload
            assert payload["total_count"] == 0
            assert payload["results"] == []
            assert payload["has_more"] is False

    @pytest.mark.asyncio
    async def test_pagination_within_window(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        """Verifies offset/limit pagination and has_more flag."""
        anchor = datetime(2026, 6, 15, tzinfo=UTC).date()

        # Create 5 journals on the anchor date
        for i in range(5):
            await _insert_journal(
                clean_database,
                user_id="test-user-123",
                title=f"Paginated Journal {i}",
                start=datetime.combine(anchor, datetime.min.time()).replace(tzinfo=UTC)
                + timedelta(hours=i),
            )

        async with authenticated_lifespan_client() as client:
            # First page (limit=2, offset=0)
            payload = await call_mcp_tool(
                client,
                "browse_journals_by_date_window",
                {
                    "anchor_date": anchor.isoformat(),
                    "limit": 2,
                    "offset": 0,
                },
                request_id=2,
            )

            assert "error" not in payload
            assert payload["total_count"] == 5
            assert len(payload["results"]) == 2
            assert payload["has_more"] is True

            # Second page (limit=2, offset=2)
            payload2 = await call_mcp_tool(
                client,
                "browse_journals_by_date_window",
                {
                    "anchor_date": anchor.isoformat(),
                    "limit": 2,
                    "offset": 2,
                },
                request_id=3,
            )

            assert len(payload2["results"]) == 2
            assert payload2["has_more"] is True

            # Last page (limit=2, offset=4)
            payload3 = await call_mcp_tool(
                client,
                "browse_journals_by_date_window",
                {
                    "anchor_date": anchor.isoformat(),
                    "limit": 2,
                    "offset": 4,
                },
                request_id=4,
            )

            assert len(payload3["results"]) == 1
            assert payload3["has_more"] is False

    @pytest.mark.asyncio
    async def test_invalid_anchor_date_returns_validation_error(
        self, authenticated_lifespan_client
    ) -> None:
        """Invalid anchor_date returns a validation error payload."""
        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "browse_journals_by_date_window",
                {
                    "anchor_date": "not-a-date",
                },
                request_id=2,
            )

            assert payload["error"] == "Validation error"
            assert "anchor_date" in payload["message"]

    @pytest.mark.asyncio
    async def test_window_boundaries(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        """Verifies window_start and window_end in the response."""
        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "browse_journals_by_date_window",
                {
                    "anchor_date": "2026-04-02",
                    "days_back": 2,
                    "days_forward": 4,
                },
                request_id=2,
            )

            assert payload["anchor_date"] == "2026-04-02"
            assert payload["window_start"] == "2026-03-31"
            assert payload["window_end"] == "2026-04-06"

    @pytest.mark.asyncio
    async def test_journals_on_window_end_day_are_included(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        """Journals occurring later on window_end day must not be excluded.

        Regression test: date-only end boundaries previously parsed as midnight
        (T00:00:00), which excluded journals with start times after midnight on
        the window_end date.
        """
        anchor = datetime(2026, 6, 15, tzinfo=UTC).date()

        # Journal at 18:00 on the window_end day (anchor + 4 = 2026-06-19)
        window_end_date = anchor + timedelta(days=4)
        await _insert_journal(
            clean_database,
            user_id="test-user-123",
            title="Evening Journal on End Day",
            start=datetime.combine(window_end_date, datetime.min.time()).replace(
                tzinfo=UTC
            )
            + timedelta(hours=18),
        )

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "browse_journals_by_date_window",
                {
                    "anchor_date": anchor.isoformat(),
                    "days_back": 2,
                    "days_forward": 4,
                },
                request_id=2,
            )

            assert "error" not in payload
            assert payload["total_count"] == 1
            titles = [r["title"] for r in payload["results"]]
            assert "Evening Journal on End Day" in titles
