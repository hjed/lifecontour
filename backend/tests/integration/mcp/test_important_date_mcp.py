"""
Integration tests for MCP important dates through contact tools.

Tests the MCP contact tools with real database to ensure important dates are correctly
handled via the integration API.
"""

import pytest

from tests.integration.mcp.http_helpers import (
    call_mcp_tool,
)


@pytest.mark.asyncio
async def test_important_dates_via_mounted_http_session(
    authenticated_lifespan_client,
    clean_database,
):
    """Mounted MCP HTTP calls should resolve and execute important dates operations correctly."""
    import typing

    async with authenticated_lifespan_client() as authenticated_client:

        async def call_mcp(
            name: str, args: dict[str, typing.Any]
        ) -> dict[str, typing.Any]:
            return await call_mcp_tool(authenticated_client, name, args)

        # 1. Create a new contact without important dates

        create_payload = await call_mcp(
            "create_contact",
            {
                "request": {
                    "first_name": "Jane",
                    "last_name": "Doe",
                }
            },
        )
        assert create_payload["name"] == "Jane Doe"
        c1_id = create_payload["id"]

        # 2. Update contact with an important date
        update_payload = await call_mcp(
            "update_contact",
            {
                "request": {
                    "contact_id": int(c1_id),
                    "first_name": "Jane",
                    "important_dates": [
                        {
                            "date_type": "birthday",
                            "precision": "full",
                            "year": 1990,
                            "month": 5,
                            "day": 15,
                        }
                    ],
                }
            },
        )

        assert update_payload["id"] == str(c1_id)
        assert len(update_payload["important_dates"]) == 1
        date = update_payload["important_dates"][0]
        assert date["date_type"] == "birthday"
        assert date["precision"] == "full"
        assert date["year"] == 1990
        assert date["month"] == 5
        assert date["day"] == 15
        assert "Birthday" in update_payload["summary"]

        # 3. Get the contact again to verify
        get_payload = await call_mcp("get_contact", {"contact_id": int(c1_id)})

        assert get_payload["id"] == str(c1_id)
        assert len(get_payload["important_dates"]) == 1
        date = get_payload["important_dates"][0]
        assert date["date_type"] == "birthday"
        assert date["precision"] == "full"
        assert date["year"] == 1990
        assert date["month"] == 5
        assert date["day"] == 15

        # 4. Create a new contact WITH important dates
        create_payload2 = await call_mcp(
            "create_contact",
            {
                "request": {
                    "first_name": "John",
                    "last_name": "Dates",
                    "important_dates": [
                        {
                            "date_type": "work_anniversary",
                            "precision": "year",
                            "year": 2020,
                        }
                    ],
                }
            },
        )

        assert create_payload2["name"] == "John Dates"
        assert len(create_payload2["important_dates"]) == 1
        date = create_payload2["important_dates"][0]
        assert date["date_type"] == "work_anniversary"
        assert date["precision"] == "year"
        assert date["year"] == 2020

        # 5. List contacts to ensure stability with important dates
        list_payload = await call_mcp("list_contacts", {"limit": 10})
        assert "data" not in list_payload  # Should be MCP response not JSON API
        assert list_payload["total_count"] >= 2
