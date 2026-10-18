"""MCP ``update_contact`` changes what it names and leaves every other field.

The tool used to rebuild the whole contact from a read of its own, leaving out
the fields it has no parameter for - so renaming a contact over MCP cleared its
photo and its favourite flag, and any field changed between that read and the
write went back to its old value (#1557).
"""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.contact_seeding import seed_contact
from tests.integration.mcp.http_helpers import call_mcp_tool


@pytest.fixture
async def contact_id(clean_database: AsyncConnection) -> int:
    contact_id = await seed_contact(
        clean_database, first_name="Ada", last_name="Lovelace"
    )
    await clean_database.execute(
        text(
            "UPDATE contacts SET company = 'Analytical Engines Ltd', "
            "job_title = 'Programmer', photo_url = '/api/contacts/avatar', "
            "is_favourite = true WHERE id = :id"
        ),
        {"id": contact_id},
    )
    return contact_id


async def _stored(connection: AsyncConnection, contact_id: int) -> dict[str, Any]:
    row = (
        await connection.execute(
            text(
                "SELECT first_name, last_name, company, job_title, photo_url, "
                "is_favourite FROM contacts WHERE id = :id"
            ),
            {"id": contact_id},
        )
    ).one()
    return dict(row._mapping)


@pytest.mark.integration
class TestUpdateContactChangesOnlyWhatItNames:
    @pytest.mark.asyncio
    async def test_a_rename_keeps_every_field_it_does_not_name(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        contact_id: int,
    ) -> None:
        async with authenticated_lifespan_client() as client:
            await call_mcp_tool(
                client,
                "update_contact",
                {"request": {"contact_id": contact_id, "first_name": "Augusta"}},
            )

        assert await _stored(clean_database, contact_id) == {
            "first_name": "Augusta",
            "last_name": "Lovelace",
            "company": "Analytical Engines Ltd",
            "job_title": "Programmer",
            "photo_url": "/api/contacts/avatar",
            "is_favourite": True,
        }

    @pytest.mark.asyncio
    async def test_an_empty_company_clears_it_and_an_empty_name_does_not(
        self,
        authenticated_lifespan_client: Any,
        clean_database: AsyncConnection,
        contact_id: int,
    ) -> None:
        async with authenticated_lifespan_client() as client:
            await call_mcp_tool(
                client,
                "update_contact",
                {
                    "request": {
                        "contact_id": contact_id,
                        "last_name": "",
                        "company": "",
                    }
                },
            )

        stored = await _stored(clean_database, contact_id)
        assert (stored["last_name"], stored["company"]) == ("Lovelace", "")
