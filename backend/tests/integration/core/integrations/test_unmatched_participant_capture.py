"""Integration tests for recording participant emails that match no contact.

Inbound journal sync resolves each participant email to a contact. The ones it
cannot resolve are kept per journal in ``journal_unmatched_participant_emails``
so recurring unknown participants can later be suggested as contacts. These
tests drive ``JournalOutboxEventProcessor`` with real adapters and read the
table directly, so they assert what the sync wrote rather than what a read path
makes of it.
"""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.core.integrations.journal_sync_seeding import (
    build_processor,
    create_calendar,
    sync_event,
)


def _invitee(email: str, **extra: Any) -> dict[str, Any]:
    return {"email": email, "relationship_type": "INVITEE", **extra}


async def _unmatched_rows(
    connection: AsyncConnection, journal_id: int
) -> dict[str, dict[str, Any]]:
    result = await connection.execute(
        text(
            """
            SELECT email, display_name, relationship_type, status, role
            FROM journal_unmatched_participant_emails
            WHERE journal_id = :journal_id
            """
        ),
        {"journal_id": journal_id},
    )
    return {row.email: dict(row._mapping) for row in result.fetchall()}


async def _create_contact_with_email(connection: AsyncConnection, email: str) -> int:
    contact_id = (
        await connection.execute(
            text("INSERT INTO contacts (first_name) VALUES ('Known') RETURNING id")
        )
    ).scalar_one()
    await connection.execute(
        text(
            """
            INSERT INTO contact_methods (contact_id, method_type, value)
            VALUES (:contact_id, 'email', :email)
            """
        ),
        {"contact_id": contact_id, "email": email},
    )
    return int(contact_id)


async def _linked_contact_ids(connection: AsyncConnection, journal_id: int) -> set[int]:
    result = await connection.execute(
        text(
            "SELECT contact_id FROM journal_contact_relationships"
            " WHERE journal_id = :journal_id"
        ),
        {"journal_id": journal_id},
    )
    return {row.contact_id for row in result.fetchall()}


@pytest.mark.integration
class TestUnmatchedParticipantCapture:
    async def test_created_event_records_only_unknown_non_self_emails(
        self, async_connection: AsyncConnection
    ) -> None:
        known_id = await _create_contact_with_email(async_connection, "known@x.com")
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)

        result = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id="evt-capture-1",
                contact_relationships=[
                    _invitee(
                        "Jane.Smith@X.com",
                        display_name="Jane Smith",
                        status="ATTENDING",
                        role="ORGANISER",
                    ),
                    _invitee("known@x.com", status="ATTENDING"),
                    _invitee("me@x.com", is_self=True),
                ],
            )
        )

        journal_id = result["journal_id"]
        rows = await _unmatched_rows(async_connection, journal_id)
        assert rows == {
            "jane.smith@x.com": {
                "email": "jane.smith@x.com",
                "display_name": "Jane Smith",
                "relationship_type": "INVITEE",
                "status": "ATTENDING",
                "role": "ORGANISER",
            }
        }
        assert await _linked_contact_ids(async_connection, journal_id) == {known_id}

    async def test_update_replaces_the_journals_unmatched_emails(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id="evt-capture-2",
                contact_relationships=[
                    _invitee("leaving@x.com"),
                    _invitee("staying@x.com", status="NO_REPLY"),
                ],
            )
        )
        journal_id = created["journal_id"]

        await processor.process_event(
            sync_event(
                "journal_event.updated",
                calendar_id=calendar_id,
                external_event_id="evt-capture-2",
                existing_journal_id=journal_id,
                etag='"etag-2"',
                contact_relationships=[
                    _invitee("staying@x.com", status="DECLINED", display_name="Stay"),
                    _invitee("joining@x.com"),
                ],
            )
        )

        rows = await _unmatched_rows(async_connection, journal_id)
        assert set(rows) == {"staying@x.com", "joining@x.com"}
        assert rows["staying@x.com"]["status"] == "DECLINED"
        assert rows["staying@x.com"]["display_name"] == "Stay"

    async def test_email_that_now_resolves_is_linked_and_no_longer_recorded(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        attendees = [_invitee("new.friend@x.com", status="ATTENDING")]
        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id="evt-capture-3",
                contact_relationships=attendees,
            )
        )
        journal_id = created["journal_id"]
        assert set(await _unmatched_rows(async_connection, journal_id)) == {
            "new.friend@x.com"
        }

        contact_id = await _create_contact_with_email(
            async_connection, "new.friend@x.com"
        )
        await processor.process_event(
            sync_event(
                "journal_event.updated",
                calendar_id=calendar_id,
                external_event_id="evt-capture-3",
                existing_journal_id=journal_id,
                etag='"etag-2"',
                contact_relationships=attendees,
            )
        )

        assert await _unmatched_rows(async_connection, journal_id) == {}
        assert await _linked_contact_ids(async_connection, journal_id) == {contact_id}
