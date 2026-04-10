"""
Integration tests for MCP review items tools.

Tests the full MCP review queue tools with real database integration.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from core_shared.models.journals.review_item import ReviewItem, ReviewReason
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.review_item_repository import SqlReviewItemRepository
from tests.integration.mcp.http_helpers import (
    extract_mcp_json_payload,
    initialize_mcp_session,
    mcp_headers,
)


class TestReviewItemsToolsIntegration:
    """Integration tests for MCP review items tools with real services."""

    @pytest_asyncio.fixture
    async def sample_test_journals(
        self, clean_database: AsyncConnection
    ) -> tuple[int, int]:
        """Create sample journals for testing and return their IDs."""
        now = datetime.now(UTC)
        query = text("""
            INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, :content, :start, :end)
            RETURNING id
        """)

        result1 = await clean_database.execute(
            query,
            {
                "user_id": "current_user",
                "title": "Source Journal",
                "content": "Source content",
                "start": now,
                "end": now,
            },
        )
        row1 = result1.fetchone()
        assert row1 is not None
        source_id = int(row1[0])

        result2 = await clean_database.execute(
            query,
            {
                "user_id": "current_user",
                "title": "Candidate Journal",
                "content": "Candidate content",
                "start": now,
                "end": now,
            },
        )
        row2 = result2.fetchone()
        assert row2 is not None
        candidate_id = int(row2[0])

        return source_id, candidate_id

    @pytest.mark.asyncio
    async def test_list_review_items_mcp_tool(
        self,
        authenticated_lifespan_client,
        sample_test_journals: tuple[int, int],
        clean_database: AsyncConnection,
    ) -> None:
        """Test listing review items via the MCP tool."""
        source_id, candidate_id = sample_test_journals

        # Manually seed a review item into the database for 'current_user'
        # (the auth user used by authenticated_lifespan_client)
        repo = SqlReviewItemRepository(clean_database)
        item = ReviewItem(
            user_id="current_user",
            source_journal_id=source_id,
            candidate_journal_id=candidate_id,
            reason=ReviewReason("duplicate_journal"),
            confidence_score=0.9,
            details={},
        )
        await repo.create(item)

        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)

            response = await authenticated_client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "list_review_items",
                        "arguments": {
                            # Setting user_id_override since in tests the context might not be fully populated
                            # Wait, the mcp http helper in `authenticated_lifespan_client` sets user auth
                            # However, to be completely sure it matches the inserted data we can pass override.
                            "user_id_override": "current_user"
                        },
                    },
                },
                headers=mcp_headers(session_id),
            )

            assert response.status_code == 200

            # extract_mcp_json_payload unwraps the text content from the MCP JSON-RPC response
            payload = extract_mcp_json_payload(response.text)

            assert "error" not in payload
            assert "data" in payload
            assert payload["meta"]["total_count"] == 1

            items = payload["data"]
            assert len(items) == 1
            assert items[0]["reason"] == "duplicate_journal"
            assert items[0]["confidence_score"] == 0.9

            # verify title enrichment
            assert items[0]["source_journal"]["title"] == "Source Journal"
            assert items[0]["candidate_journal"]["title"] == "Candidate Journal"
