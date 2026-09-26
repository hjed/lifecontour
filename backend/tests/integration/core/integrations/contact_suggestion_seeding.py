"""Seeding for contact-suggestion tests.

A suggestion is an email recorded in ``journal_unmatched_participant_emails``
on enough of a user's journals. Inbound sync is what writes those rows, and its
own tests cover that (``test_unmatched_participant_capture.py``); the
suggestion tests only need the rows to exist, so they are written directly.

``USER_ID`` is the owner the authenticated test client and the MCP session act
as, so rows seeded here are visible to the API and MCP tests too.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

USER_ID = "test-user-123"
OTHER_USER_ID = "test-user-456"


async def create_journal(
    connection: AsyncConnection,
    *,
    user_id: str = USER_ID,
    days_ago: int = 1,
    title: str = "Team sync",
) -> int:
    """A journal ``days_ago`` days in the past, returning its id."""
    start = datetime.now(UTC) - timedelta(days=days_ago)
    journal_id = (
        await connection.execute(
            text(
                """
                INSERT INTO journals
                    (user_id, title, content, event_date_range_start,
                     event_date_range_end)
                VALUES (:user_id, :title, '', :start, :end)
                RETURNING id
                """
            ),
            {
                "user_id": user_id,
                "title": title,
                "start": start,
                "end": start + timedelta(hours=1),
            },
        )
    ).scalar_one()
    return int(journal_id)


async def record_unmatched(
    connection: AsyncConnection,
    journal_id: int,
    email: str,
    *,
    display_name: str | None = None,
    relationship_type: str = "INVITEE",
    status: str | None = None,
    role: str | None = None,
) -> None:
    """Record ``email`` as an unmatched participant of ``journal_id``."""
    await connection.execute(
        text(
            """
            INSERT INTO journal_unmatched_participant_emails
                (journal_id, email, display_name, relationship_type, status, role)
            VALUES
                (:journal_id, :email, :display_name, :relationship_type,
                 :status, :role)
            """
        ),
        {
            "journal_id": journal_id,
            "email": email,
            "display_name": display_name,
            "relationship_type": relationship_type,
            "status": status,
            "role": role,
        },
    )


async def seed_participant(
    connection: AsyncConnection,
    email: str,
    journal_count: int,
    *,
    user_id: str = USER_ID,
    display_name: str | None = None,
    status: str | None = None,
) -> list[int]:
    """``email`` as an unmatched participant on ``journal_count`` new journals.

    Journal ``i`` is dated ``i + 1`` days ago, so the most recent is yesterday.
    """
    journal_ids: list[int] = []
    for i in range(journal_count):
        journal_id = await create_journal(connection, user_id=user_id, days_ago=i + 1)
        await record_unmatched(
            connection,
            journal_id,
            email,
            display_name=display_name,
            status=status,
        )
        journal_ids.append(journal_id)
    return journal_ids


async def create_contact(
    connection: AsyncConnection,
    *,
    first_name: str = "Known",
    email: str | None = None,
    archived: bool = False,
) -> int:
    """A contact, optionally holding ``email``, returning its id.

    The email is the primary one, or - with ``archived`` - an archived one.
    """
    contact_id = int(
        (
            await connection.execute(
                text(
                    "INSERT INTO contacts (first_name) VALUES (:first_name)"
                    " RETURNING id"
                ),
                {"first_name": first_name},
            )
        ).scalar_one()
    )
    if email is not None:
        await connection.execute(
            text(
                """
                INSERT INTO contact_methods
                    (contact_id, method_type, value, is_primary, is_archived)
                VALUES (:contact_id, 'email', :email, :is_primary, :is_archived)
                """
            ),
            {
                "contact_id": contact_id,
                "email": email,
                "is_primary": not archived,
                "is_archived": archived,
            },
        )
    return contact_id


async def unmatched_journal_ids(connection: AsyncConnection, email: str) -> set[int]:
    """The journals ``email`` is still recorded as unmatched on."""
    result = await connection.execute(
        text(
            "SELECT journal_id FROM journal_unmatched_participant_emails"
            " WHERE email = :email"
        ),
        {"email": email},
    )
    return {row.journal_id for row in result.fetchall()}


async def journal_relationships(
    connection: AsyncConnection, contact_id: int
) -> dict[int, tuple[str, str | None, str | None]]:
    """``journal_id -> (relationship_type, status, role)`` for the contact."""
    result = await connection.execute(
        text(
            """
            SELECT journal_id, relationship_type, status, role
            FROM journal_contact_relationships
            WHERE contact_id = :contact_id
            """
        ),
        {"contact_id": contact_id},
    )
    return {
        row.journal_id: (row.relationship_type, row.status, row.role)
        for row in result.fetchall()
    }
