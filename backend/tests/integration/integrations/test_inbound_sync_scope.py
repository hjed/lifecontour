"""Inbound contact syncs change only the fields their source owns.

A sync event names its scope: the contact fields and important-date types the
source owns. Everything else - a nickname Google was never asked for, the
avatar Immich set, a first-met date no provider models - keeps its stored
value. An event naming no scope (queued before scopes existed) overwrites the
contact whole, as before.
"""

from __future__ import annotations

from typing import Any

import pytest
from core_shared.models.contacts.important_date_types import ImportantDateType
from core_shared.models.contacts.sync_scope import ContactSyncField, ContactSyncScope
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.outbox_event_processor import OutboxEventProcessor
from tests.integration.contact_seeding import TEST_USER_ID, seed_contact
from tests.integration.integrations.link_consolidation_helpers import (
    build_contact_service,
)

EXTERNAL_ID = "people/cScoped"

GOOGLE_LIKE = ContactSyncScope(
    fields=frozenset(
        {
            ContactSyncField.FIRST_NAME,
            ContactSyncField.LAST_NAME,
            ContactSyncField.MIDDLE_NAME,
            ContactSyncField.COMPANY,
            ContactSyncField.JOB_TITLE,
            ContactSyncField.IS_FAVOURITE,
            ContactSyncField.METHODS,
            ContactSyncField.ADDRESSES,
            ContactSyncField.NOTES,
            ContactSyncField.TAGS,
        }
    ),
    important_date_types=frozenset(
        {ImportantDateType.BIRTHDAY, ImportantDateType.MARRIAGE_ANNIVERSARY}
    ),
)

IMMICH_LIKE = ContactSyncScope(
    fields=frozenset({ContactSyncField.PHOTO_URL}),
    important_date_types=frozenset({ImportantDateType.BIRTHDAY}),
)


def _event(
    event_type: str,
    contact_data: dict[str, Any],
    scope: ContactSyncScope | None,
    *,
    source: str = "google",
) -> OutboxEvent:
    return OutboxEvent.create_contact_sync_event(
        contact_data={"user_id": TEST_USER_ID, **contact_data},
        integration_source=source,
        external_id=EXTERNAL_ID,
        sync_type=event_type.split(".")[1],
        etag="etag-new",
        user_id=TEST_USER_ID,
        sync_scope=scope,
    )


def _birthday(day: int) -> dict[str, Any]:
    return {
        "date_type": "birthday",
        "precision": "day_month",
        "month": 4,
        "day": day,
    }


async def _seed(conn: AsyncConnection, *, source: str = "google") -> int:
    """Bob: every scalar set, an email, a birthday, an anniversary, a first-met."""
    contact_id = await seed_contact(
        conn,
        first_name="Robert",
        last_name="Smith",
        middle_name="James",
        nick_name="Bob",
        company="Acme",
        job_title="Engineer",
        photo_url="/api/contacts/avatar",
        is_favourite=True,
    )
    await conn.execute(
        text(
            "INSERT INTO contact_methods (contact_id, method_type, value, is_primary) "
            "VALUES (:c, 'email', 'bob@example.com', true)"
        ),
        {"c": contact_id},
    )
    await conn.execute(
        text(
            "INSERT INTO contact_important_dates "
            "(contact_id, date_type, precision, month, day) VALUES "
            "(:c, 'birthday', 'day_month', 4, 1), "
            "(:c, 'marriage_anniversary', 'day_month', 5, 2), "
            "(:c, 'first_met', 'day_month', 6, 3)"
        ),
        {"c": contact_id},
    )
    await conn.execute(
        text(
            "INSERT INTO sync_metadata "
            "(user_id, internal_id, integration_source, external_id, "
            "last_synced_at, version_hash, sync_status, internal_entity_type, "
            "external_entity_type) "
            "VALUES (:u, :c, :s, :eid, now(), 'etag-old', 'success', "
            "'contact', 'person')"
        ),
        {"u": TEST_USER_ID, "c": contact_id, "s": source, "eid": EXTERNAL_ID},
    )
    return contact_id


async def _contact(conn: AsyncConnection, contact_id: int) -> Any:
    return (
        await conn.execute(
            text("SELECT * FROM contacts WHERE id = :id"), {"id": contact_id}
        )
    ).one()


async def _dates(conn: AsyncConnection, contact_id: int) -> dict[str, int]:
    rows = await conn.execute(
        text(
            "SELECT date_type, day FROM contact_important_dates WHERE contact_id = :c"
        ),
        {"c": contact_id},
    )
    return {row.date_type: row.day for row in rows}


async def _emails(conn: AsyncConnection, contact_id: int) -> set[str]:
    rows = await conn.execute(
        text("SELECT value FROM contact_methods WHERE contact_id = :c"),
        {"c": contact_id},
    )
    return {row.value for row in rows}


def _processor(conn: AsyncConnection) -> OutboxEventProcessor:
    return OutboxEventProcessor(build_contact_service(conn), conn)


GOOGLE_UPDATE: dict[str, Any] = {
    "first_name": "Rob",
    "last_name": "Smith",
    "company": "Initech",
    "methods": [
        {"method_type": "email", "value": "rob@example.com", "is_primary": True}
    ],
    "important_dates": [_birthday(9)],
}


@pytest.mark.integration
@pytest.mark.usefixtures("clean_database")
class TestInboundSyncScope:
    @pytest.mark.asyncio
    async def test_google_update_keeps_fields_google_does_not_own(
        self, async_connection: AsyncConnection
    ) -> None:
        contact_id = await _seed(async_connection)

        result = await _processor(async_connection).process_event(
            _event("contact.updated", GOOGLE_UPDATE, GOOGLE_LIKE)
        )

        assert result["status"] == "success"
        row = await _contact(async_connection, contact_id)
        # Owned by Google: applied, including the clears.
        assert (row.first_name, row.company) == ("Rob", "Initech")
        assert row.middle_name is None
        assert row.job_title is None
        assert row.is_favourite is False
        assert await _emails(async_connection, contact_id) == {"rob@example.com"}
        # Not owned by Google: kept.
        assert row.nick_name == "Bob"
        assert row.photo_url == "/api/contacts/avatar"
        assert await _dates(async_connection, contact_id) == {
            "birthday": 9,
            "first_met": 3,
        }

    @pytest.mark.asyncio
    async def test_google_with_no_dates_clears_only_its_date_types(
        self, async_connection: AsyncConnection
    ) -> None:
        contact_id = await _seed(async_connection)

        await _processor(async_connection).process_event(
            _event(
                "contact.updated",
                {**GOOGLE_UPDATE, "important_dates": []},
                GOOGLE_LIKE,
            )
        )

        assert await _dates(async_connection, contact_id) == {"first_met": 3}

    @pytest.mark.asyncio
    async def test_immich_update_changes_only_avatar_and_birthday(
        self, async_connection: AsyncConnection
    ) -> None:
        contact_id = await _seed(async_connection, source="immich")

        result = await _processor(async_connection).process_event(
            _event(
                "contact.updated",
                {
                    "first_name": "Robert James",
                    "last_name": None,
                    "photo_url": "/api/contacts/new-avatar",
                    "important_dates": [_birthday(7)],
                },
                IMMICH_LIKE,
                source="immich",
            )
        )

        assert result["status"] == "success"
        row = await _contact(async_connection, contact_id)
        assert row.photo_url == "/api/contacts/new-avatar"
        assert (row.first_name, row.last_name, row.middle_name) == (
            "Robert",
            "Smith",
            "James",
        )
        assert (row.nick_name, row.company, row.job_title) == (
            "Bob",
            "Acme",
            "Engineer",
        )
        assert row.is_favourite is True
        assert await _emails(async_connection, contact_id) == {"bob@example.com"}
        assert await _dates(async_connection, contact_id) == {
            "birthday": 7,
            "marriage_anniversary": 2,
            "first_met": 3,
        }

    @pytest.mark.asyncio
    async def test_create_reconciled_onto_an_existing_contact_is_scoped(
        self, async_connection: AsyncConnection
    ) -> None:
        contact_id = await seed_contact(
            async_connection, first_name="Robert", nick_name="Bob"
        )
        await async_connection.execute(
            text(
                "INSERT INTO contact_methods "
                "(contact_id, method_type, value, is_primary) "
                "VALUES (:c, 'email', 'rob@example.com', true)"
            ),
            {"c": contact_id},
        )

        result = await _processor(async_connection).process_event(
            _event("contact.created", GOOGLE_UPDATE, GOOGLE_LIKE)
        )

        assert result["contact_id"] == contact_id
        row = await _contact(async_connection, contact_id)
        assert row.first_name == "Rob"
        assert row.nick_name == "Bob"

    @pytest.mark.asyncio
    async def test_event_without_scope_still_overwrites_the_contact(
        self, async_connection: AsyncConnection
    ) -> None:
        contact_id = await _seed(async_connection)

        await _processor(async_connection).process_event(
            _event("contact.updated", GOOGLE_UPDATE, None)
        )

        row = await _contact(async_connection, contact_id)
        assert row.nick_name is None
        assert row.photo_url is None
        assert await _dates(async_connection, contact_id) == {"birthday": 9}
