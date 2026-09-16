"""
Integration tests for MCP review items tools.

Tests the full MCP review queue tools with real database integration. The
tools act for the authenticated user: another user's review items are neither
listed nor dismissable, and no argument lets a caller pick whose queue to read.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from core_shared.models.journals.review_item import ReviewItem, ReviewReason
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.review_item_repository import SqlReviewItemRepository
from tests.integration.mcp.http_helpers import (
    call_mcp_tool,
)

OTHER_USER_ID = "other-user-456"


async def _insert_journal(connection: AsyncConnection, user_id: str, title: str) -> int:
    now = datetime.now(UTC)
    result = await connection.execute(
        text("""
            INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, :content, :start, :end)
            RETURNING id
        """),
        {
            "user_id": user_id,
            "title": title,
            "content": f"{title} content",
            "start": now,
            "end": now,
        },
    )
    row = result.fetchone()
    assert row is not None
    return int(row[0])


async def _seed_review_item(connection: AsyncConnection, user_id: str) -> ReviewItem:
    """Seed a pending review item, with its two journals, owned by ``user_id``."""
    source_id = await _insert_journal(connection, user_id, "Source Journal")
    candidate_id = await _insert_journal(connection, user_id, "Candidate Journal")
    created_item, _ = await SqlReviewItemRepository(connection).create(
        ReviewItem(
            user_id=user_id,
            source_journal_id=source_id,
            candidate_journal_id=candidate_id,
            reason=ReviewReason("duplicate_journal"),
            confidence_score=0.9,
            details={},
        )
    )
    return created_item


@pytest_asyncio.fixture
async def own_review_item(
    clean_database: AsyncConnection, test_user: Any
) -> ReviewItem:
    return await _seed_review_item(clean_database, test_user.id)


@pytest_asyncio.fixture
async def other_users_review_item(clean_database: AsyncConnection) -> ReviewItem:
    return await _seed_review_item(clean_database, OTHER_USER_ID)


class TestReviewItemsToolsIntegration:
    """Integration tests for MCP review items tools with real services."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("other_users_review_item")
    async def test_list_review_items_returns_the_authenticated_users_items(
        self,
        authenticated_lifespan_client: Any,
        own_review_item: ReviewItem,
    ) -> None:
        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool(authenticated_client, "list_review_items", {})

        assert "error" not in payload
        assert payload["meta"]["total_count"] == 1

        items = payload["data"]
        assert [item["id"] for item in items] == [own_review_item.id]
        assert items[0]["reason"] == "duplicate_journal"
        assert items[0]["confidence_score"] == pytest.approx(0.9)
        assert items[0]["source_journal"]["title"] == "Source Journal"
        assert items[0]["candidate_journal"]["title"] == "Candidate Journal"

    @pytest.mark.asyncio
    async def test_dismiss_review_item_dismisses_the_authenticated_users_item(
        self,
        authenticated_lifespan_client: Any,
        own_review_item: ReviewItem,
        clean_database: AsyncConnection,
        test_user: Any,
    ) -> None:
        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool(
                authenticated_client,
                "dismiss_review_item",
                {"item_id": own_review_item.id},
            )

        assert "error" not in payload
        assert payload["success"] is True
        assert payload["status"] == "dismissed"

        repo = SqlReviewItemRepository(clean_database)
        assert await repo.find_pending_by_user(test_user.id) == []

    @pytest.mark.asyncio
    async def test_dismiss_review_item_cannot_dismiss_another_users_item(
        self,
        authenticated_lifespan_client: Any,
        other_users_review_item: ReviewItem,
        clean_database: AsyncConnection,
    ) -> None:
        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool(
                authenticated_client,
                "dismiss_review_item",
                {"item_id": other_users_review_item.id},
            )

        assert payload == {
            "error": f"Review item {other_users_review_item.id} not found."
        }

        repo = SqlReviewItemRepository(clean_database)
        pending = await repo.find_pending_by_user(OTHER_USER_ID)
        assert [item.id for item in pending] == [other_users_review_item.id]
