"""MCP ``update_contact`` changes only what it is asked to (issue #1524).

The tool used to hand the service a sub-resource list holding only what the
caller mentioned, and the service treats a list as the whole desired state: so
``email=`` deleted the contact's phone, and ``notes=`` — described as
"additional notes to add" — deleted every note already there. The tool now
builds the whole desired state from the contact it has already read, and the
service's reconcile turns a matched edit into a real edit with history.
"""

import json
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.mcp.http_helpers import call_mcp_tool


async def _call(
    authenticated_lifespan_client: Callable[..., Any],
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    async with authenticated_lifespan_client() as client:
        return await call_mcp_tool(client, name, arguments)


async def _create(
    authenticated_lifespan_client: Callable[..., Any], **fields: Any
) -> int:
    payload = await _call(
        authenticated_lifespan_client,
        "create_contact",
        {"request": {"first_name": "Merge", "last_name": "Test", **fields}},
    )
    return int(payload["id"])


async def _update(
    authenticated_lifespan_client: Callable[..., Any],
    contact_id: int,
    **fields: Any,
) -> dict[str, Any]:
    return await _call(
        authenticated_lifespan_client,
        "update_contact",
        {"request": {"contact_id": contact_id, **fields}},
    )


async def _methods(conn: AsyncConnection, contact_id: int) -> list[tuple[Any, ...]]:
    result = await conn.execute(
        text(
            "SELECT id, method_type, value, is_primary FROM contact_methods "
            "WHERE contact_id = :cid ORDER BY method_type, id"
        ),
        {"cid": contact_id},
    )
    return [tuple(r) for r in result.fetchall()]


async def _notes(conn: AsyncConnection, contact_id: int) -> list[tuple[Any, ...]]:
    result = await conn.execute(
        text(
            "SELECT id, content FROM contact_notes WHERE contact_id = :cid ORDER BY id"
        ),
        {"cid": contact_id},
    )
    return [tuple(r) for r in result.fetchall()]


async def _dates(conn: AsyncConnection, contact_id: int) -> list[tuple[Any, ...]]:
    result = await conn.execute(
        text(
            "SELECT id, date_type, year FROM contact_important_dates "
            "WHERE contact_id = :cid ORDER BY id"
        ),
        {"cid": contact_id},
    )
    return [tuple(r) for r in result.fetchall()]


async def _outbox(conn: AsyncConnection, event_type: str) -> list[dict[str, Any]]:
    result = await conn.execute(
        text("SELECT event_data FROM outbox_events WHERE event_type = :et ORDER BY id"),
        {"et": event_type},
    )
    return [
        json.loads(row[0]) if isinstance(row[0], str) else row[0]
        for row in result.fetchall()
    ]


@pytest.mark.integration
class TestUpdateContactMergesMethods:
    @pytest.mark.asyncio
    async def test_updating_the_email_keeps_the_phone(
        self,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
    ) -> None:
        contact_id = await _create(
            authenticated_lifespan_client,
            email="merge.before@example.com",
            phone="+61412345678",
        )
        before = await _methods(async_connection, contact_id)
        phone_row = next(m for m in before if m[1] == "phone")

        await _update(
            authenticated_lifespan_client,
            contact_id,
            email="merge.after@example.com",
        )

        after = await _methods(async_connection, contact_id)
        assert phone_row in after
        assert [m[2] for m in after if m[1] == "email"] == ["merge.after@example.com"]

    @pytest.mark.asyncio
    async def test_updating_the_email_edits_the_stored_method_in_place(
        self,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
    ) -> None:
        """So the feed can say what the email was, not only that it changed."""
        contact_id = await _create(
            authenticated_lifespan_client, email="inplace.before@example.com"
        )
        (email_id, *_) = (await _methods(async_connection, contact_id))[0]
        await async_connection.execute(text("DELETE FROM outbox_events"))

        await _update(
            authenticated_lifespan_client,
            contact_id,
            email="inplace.after@example.com",
        )

        assert [m[0] for m in await _methods(async_connection, contact_id)] == [
            email_id
        ]
        (updated,) = await _outbox(async_connection, "ContactUpdated")
        assert updated["changed_fields"][f"method_{email_id}_value"] == [
            "inplace.before@example.com",
            "inplace.after@example.com",
        ]
        assert updated["source"] == "mcp"

    @pytest.mark.asyncio
    async def test_a_phone_is_added_beside_an_existing_email(
        self,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
    ) -> None:
        contact_id = await _create(
            authenticated_lifespan_client, email="addphone@example.com"
        )

        await _update(authenticated_lifespan_client, contact_id, phone="+61412345678")

        types = sorted(m[1] for m in await _methods(async_connection, contact_id))
        assert types == ["email", "phone"]


@pytest.mark.integration
class TestUpdateContactAppendsNotes:
    @pytest.mark.asyncio
    async def test_a_note_is_added_beside_the_existing_ones(
        self,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
    ) -> None:
        contact_id = await _create(
            authenticated_lifespan_client, notes="Met at the conference"
        )
        (stored,) = await _notes(async_connection, contact_id)

        await _update(
            authenticated_lifespan_client, contact_id, notes="Follows cricket"
        )

        notes = await _notes(async_connection, contact_id)
        assert notes[0] == stored
        assert [n[1] for n in notes] == ["Met at the conference", "Follows cricket"]

    @pytest.mark.asyncio
    async def test_other_fields_leave_the_notes_alone(
        self,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
    ) -> None:
        contact_id = await _create(
            authenticated_lifespan_client, notes="Met at the conference"
        )
        stored = await _notes(async_connection, contact_id)

        await _update(authenticated_lifespan_client, contact_id, company="Acme")

        assert await _notes(async_connection, contact_id) == stored


@pytest.mark.integration
class TestUpdateContactEditsImportantDates:
    @pytest.mark.asyncio
    async def test_editing_a_date_keeps_its_row_and_publishes_the_edit(
        self,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
    ) -> None:
        """The asymmetry #1524 was filed for: the REST PUT of a date wrote
        ``year: 1990 -> 1991`` to the feed and this wrote nothing."""
        birthday = {
            "date_type": "birthday",
            "precision": "full",
            "month": 5,
            "day": 15,
        }
        contact_id = await _create(
            authenticated_lifespan_client,
            important_dates=[{**birthday, "year": 1990}],
        )
        (date_id, _, _) = (await _dates(async_connection, contact_id))[0]
        await async_connection.execute(text("DELETE FROM outbox_events"))

        await _update(
            authenticated_lifespan_client,
            contact_id,
            important_dates=[{**birthday, "year": 1991}],
        )

        assert await _dates(async_connection, contact_id) == [
            (date_id, "birthday", 1991)
        ]
        (edit,) = await _outbox(async_connection, "ImportantDateUpdated")
        assert edit["date_id"] == date_id
        assert edit["changed_fields"] == {"year": [1990, 1991]}
        assert edit["source"] == "mcp"
        assert await _outbox(async_connection, "ImportantDateAdded") == []
