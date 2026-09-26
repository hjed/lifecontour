"""MCP reads and archives a contact's emails, phones and addresses by id."""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.mcp.http_helpers import call_mcp_tool


async def _insert_contact(conn: AsyncConnection) -> dict[str, int]:
    """A contact with a primary email, an archived phone and an archived address."""
    contact_id = (
        await conn.execute(
            text("INSERT INTO contacts (first_name) VALUES ('Ada') RETURNING id")
        )
    ).scalar_one()
    email_id = (
        await conn.execute(
            text(
                "INSERT INTO contact_methods (contact_id, method_type, value, is_primary) "
                "VALUES (:c, 'email', 'ada@example.com', true) RETURNING id"
            ),
            {"c": contact_id},
        )
    ).scalar_one()
    phone_id = (
        await conn.execute(
            text(
                "INSERT INTO contact_methods (contact_id, method_type, value, is_archived) "
                "VALUES (:c, 'phone', '+44 20 7946 0000', true) RETURNING id"
            ),
            {"c": contact_id},
        )
    ).scalar_one()
    address_id = (
        await conn.execute(
            text(
                "INSERT INTO contact_addresses "
                "(contact_id, street_line_1, locality, country_code, is_archived) "
                "VALUES (:c, '1 Childhood Rd', 'Bathurst', 'AU', true) RETURNING id"
            ),
            {"c": contact_id},
        )
    ).scalar_one()
    return {
        "contact": contact_id,
        "email": email_id,
        "phone": phone_id,
        "address": address_id,
    }


def _by_id(payload: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    """Fields keyed by ``(kind, id)``: methods and addresses number separately."""
    return {(field["kind"], field["id"]): field for field in payload["contact_fields"]}


class TestContactFieldsMcp:
    @pytest.mark.asyncio
    async def test_archived_values_are_left_out_by_default(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        ids = await _insert_contact(clean_database)

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client, "get_contact", {"contact_id": ids["contact"]}
            )

        assert _by_id(payload) == {
            ("email", ids["email"]): {
                "id": ids["email"],
                "kind": "email",
                "value": "ada@example.com",
                "label": None,
                "is_primary": True,
                "is_archived": False,
            }
        }

    @pytest.mark.asyncio
    async def test_include_archived_lists_them(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        ids = await _insert_contact(clean_database)

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "get_contact",
                {"contact_id": ids["contact"], "include_archived": True},
            )

        fields = _by_id(payload)
        assert fields["phone", ids["phone"]]["is_archived"] is True
        address = fields["address", ids["address"]]
        assert address["value"] == "1 Childhood Rd, Bathurst, AU"
        assert address["is_archived"] is True

    @pytest.mark.asyncio
    async def test_archiving_the_primary_email_demotes_it(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        ids = await _insert_contact(clean_database)

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "set_contact_field_archived",
                {
                    "contact_id": ids["contact"],
                    "kind": "email",
                    "field_id": ids["email"],
                    "archived": True,
                },
            )

        email = _by_id(payload)["email", ids["email"]]
        assert email["is_archived"] is True
        assert email["is_primary"] is False
        assert payload["email"] is None

    @pytest.mark.asyncio
    async def test_restoring_an_address(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        ids = await _insert_contact(clean_database)

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "set_contact_field_archived",
                {
                    "contact_id": ids["contact"],
                    "kind": "address",
                    "field_id": ids["address"],
                    "archived": False,
                },
            )

        assert _by_id(payload)["address", ids["address"]]["is_archived"] is False
        row = (
            await clean_database.execute(
                text("SELECT is_archived FROM contact_addresses WHERE id = :id"),
                {"id": ids["address"]},
            )
        ).scalar_one()
        assert row is False

    @pytest.mark.asyncio
    async def test_a_field_of_another_kind_is_not_found(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        """A phone id named as an email is refused, not archived."""
        ids = await _insert_contact(clean_database)

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "set_contact_field_archived",
                {
                    "contact_id": ids["contact"],
                    "kind": "email",
                    "field_id": ids["phone"],
                    "archived": False,
                },
            )

        assert f"No email with id {ids['phone']} found" in payload["message"]
        row = (
            await clean_database.execute(
                text("SELECT is_archived FROM contact_methods WHERE id = :id"),
                {"id": ids["phone"]},
            )
        ).scalar_one()
        assert row is True
