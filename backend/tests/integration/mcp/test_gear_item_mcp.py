"""
Integration tests for MCP gear item tools.
"""

import pytest
from core_shared.models.journals.gear_item import GearItem
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.gear_item_repository import SqlGearItemRepository
from tests.integration.mcp.http_helpers import (
    call_mcp_tool_sessionless,
)


class TestGearItemToolsIntegration:
    """Integration tests for MCP gear item tools with real services."""

    @pytest.mark.asyncio
    async def test_create_gear_item_mcp_tool(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        """Test creating a gear item via the MCP tool."""
        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client,
                "create_gear_item",
                {
                    "name": "Test Rope",
                    "model": "Model X",
                    "purchase_date": "2024-01-01",
                },
            )

            assert "error" not in payload

            item_data = payload
            assert item_data["name"] == "Test Rope"
            assert item_data["model"] == "Model X"
            assert item_data["purchase_date"] == "2024-01-01"

            # verify in database
            repo = SqlGearItemRepository(clean_database)
            # The test client authenticated as 'test_user_id' from the fixture
            # wait, authenticated_lifespan_client uses 'test_user_id' by default?
            # Actually, we can just find the item by id
            db_item = await repo.find_by_id(item_data["id"])
            assert db_item is not None
            assert db_item.name == "Test Rope"

    @pytest.mark.asyncio
    async def test_list_gear_items_mcp_tool(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        """Test listing gear items via the MCP tool."""
        # Create a test item manually
        repo = SqlGearItemRepository(clean_database)
        # We need to know the user_id that the client uses. The fixture usually uses "current_user"
        item = GearItem(
            user_id="test-user-123",
            name="Test Harness",
        )
        await repo.save(item)

        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client, "list_gear_items", {}
            )

            assert "error" not in payload
            assert "gear_items" in payload

            items = payload["gear_items"]
            assert len(items) >= 1
            # Check if our item is there
            names = [i["name"] for i in items]
            assert "Test Harness" in names

    @pytest.mark.asyncio
    async def test_get_gear_item_mcp_tool(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        """Test getting a gear item via the MCP tool."""
        repo = SqlGearItemRepository(clean_database)
        item = GearItem(
            user_id="test-user-123",
            name="Specific Item",
        )
        saved_item = await repo.save(item)
        assert saved_item.id is not None

        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client,
                "get_gear_item",
                {
                    "gear_item_id": saved_item.id,
                },
            )

            assert "error" not in payload

            assert payload["id"] == saved_item.id
            assert payload["name"] == "Specific Item"

    @pytest.mark.asyncio
    async def test_update_gear_item_mcp_tool(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        """Test updating a gear item via the MCP tool."""
        repo = SqlGearItemRepository(clean_database)
        item = GearItem(
            user_id="test-user-123",
            name="Old Name",
        )
        saved_item = await repo.save(item)
        assert saved_item.id is not None

        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool_sessionless(
                authenticated_client,
                "update_gear_item",
                {
                    "gear_item_id": saved_item.id,
                    "name": "New Name",
                    "model": "New Model",
                },
            )

            assert "error" not in payload

            assert payload["id"] == saved_item.id
            assert payload["name"] == "New Name"
            assert payload["model"] == "New Model"

            assert saved_item.id is not None
            # verify in database
            db_item = await repo.find_by_id(saved_item.id)
            assert db_item is not None
            assert db_item.name == "New Name"
            assert db_item.model == "New Model"
