"""The whole contact document the search indexer builds, pinned field by field.

**Why a golden test and not a set of targeted assertions.** ITER18-004 Phase 10
moves the importance signals — favourite, the two 30-day counts and the
last-activity instant — out of ``_fetch_complete_contact_data`` and into a shared
read the dashboard can use, and its acceptance criterion is that the *documents
are unchanged*. A refactor can only be proved not to change an output against a
pin taken **before** it, so this file is written first and asserts the complete
returned mapping rather than the fields the refactor happens to touch: a field
this test does not name is a field the refactor could silently drop.

``journal_mentions`` is the one key compared order-insensitively. The journals
query carries no ``ORDER BY``, so its order is whatever the plan returns and is
not a property of the document; sorting it here pins the *contents* without
inventing a guarantee the production code does not make.

The timestamps are read back from the database rather than restated, because the
document renders whatever the driver hands back and the point of the pin is the
document, not this test's opinion about how Postgres formats an instant.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.search.search_indexer import SearchIndexer

pytestmark = pytest.mark.asyncio

CONTACT_ID = 4001
RELATED_CONTACT_ID = 4002


async def _seed_full_contact(connection: AsyncConnection, *, now: datetime) -> None:
    """Populate every field the contact document reads, for one contact.

    Both journals straddle the 30-day window, as do the two ``contact`` history
    rows, so the counts are pinned at a known number rather than at "however
    many rows exist". The activity history covers **all five** entity types the
    production predicate matches — the contact itself and its method, address,
    note and tag — because a type left unseeded is a branch a later extraction
    could drop while this suite still passed. Every timestamp sits before
    ``contacts.updated_at`` so the last-activity instant has a single
    unambiguous answer.
    """
    await connection.execute(
        text("""
            INSERT INTO contacts (
                id, first_name, last_name, middle_name, nick_name,
                company, job_title, is_favourite, created_at, updated_at
            )
            VALUES (
                :id, 'Ada', 'Lovelace', 'Byron', 'Countess',
                'Analytical Engines', 'Mathematician', true, :created_at, :now
            )
        """),
        {"id": CONTACT_ID, "created_at": now - timedelta(days=365), "now": now},
    )
    await connection.execute(
        text("""
            INSERT INTO contacts (id, first_name, last_name, created_at, updated_at)
            VALUES (:id, 'Charles', 'Babbage', :now, :now)
        """),
        {"id": RELATED_CONTACT_ID, "now": now},
    )

    # Ordered by is_primary DESC then created_at ASC, so the primary email leads
    # and the alternate one follows the primary phone.
    for method_id, method_type, value, is_primary, offset_days in (
        (1, "email", "ada@example.com", True, 30),
        (2, "phone", "+61400000000", True, 29),
        (3, "email", "ada.alt@example.com", False, 28),
    ):
        await connection.execute(
            text("""
                INSERT INTO contact_methods (
                    id, contact_id, method_type, value, is_primary,
                    created_at, updated_at
                )
                VALUES (:id, :contact_id, :method_type, :value, :is_primary,
                        :created_at, :created_at)
            """),
            {
                "id": method_id,
                "contact_id": CONTACT_ID,
                "method_type": method_type,
                "value": value,
                "is_primary": is_primary,
                "created_at": now - timedelta(days=offset_days),
            },
        )

    # No document field renders an address; it exists so the contact has an
    # address child for the activity history below to point at.
    await connection.execute(
        text("""
            INSERT INTO contact_addresses (
                id, contact_id, street_line_1, country_code, created_at, updated_at
            )
            VALUES (1, :contact_id, '1 Test Street', 'AU', :now, :now)
        """),
        {"contact_id": CONTACT_ID, "now": now},
    )

    # Ordered by created_at DESC and joined with a single space.
    for note_id, content, offset_days in (
        (1, "Older note.", 20),
        (2, "Newer note.", 10),
    ):
        await connection.execute(
            text("""
                INSERT INTO contact_notes (id, contact_id, content, created_at, updated_at)
                VALUES (:id, :contact_id, :content, :created_at, :created_at)
            """),
            {
                "id": note_id,
                "contact_id": CONTACT_ID,
                "content": content,
                "created_at": now - timedelta(days=offset_days),
            },
        )

    for tag_id, name in ((1, "colleagues"), (2, "analytical")):
        await connection.execute(
            text("""
                INSERT INTO tags (id, name, created_at, updated_at)
                VALUES (:id, :name, :now, :now)
            """),
            {"id": tag_id, "name": name, "now": now},
        )
        await connection.execute(
            text("""
                INSERT INTO contact_tags (contact_id, tag_id, created_at)
                VALUES (:contact_id, :tag_id, :now)
            """),
            {"contact_id": CONTACT_ID, "tag_id": tag_id, "now": now},
        )

    # Exactly one relationship: the query is a UNION ALL with no ORDER BY, so a
    # second one would make the list's order a coin toss.
    await connection.execute(
        text("""
            INSERT INTO contact_relationships (
                id, from_contact_id, to_contact_id, relationship_type,
                to_user, created_at, updated_at
            )
            VALUES (1, :from_id, :to_id, 'friend', false, :now, :now)
        """),
        {"from_id": CONTACT_ID, "to_id": RELATED_CONTACT_ID, "now": now},
    )

    await connection.execute(
        text("""
            INSERT INTO contact_summaries (
                contact_id, summary_text, is_disabled, created_at, updated_at
            )
            VALUES (:contact_id, 'Ada is a long-standing collaborator.', false,
                    :now, :now)
        """),
        {"contact_id": CONTACT_ID, "now": now},
    )

    await connection.execute(
        text("""
            INSERT INTO contact_important_dates (
                contact_id, date_type, precision, year, month, day,
                created_at, updated_at
            )
            VALUES (:contact_id, 'birthday', 'day_month', null, 12, 10, :now, :now)
        """),
        {"contact_id": CONTACT_ID, "now": now},
    )

    for journal_id, title, offset_days in (
        (1, "Recent Meeting", 5),
        (2, "Old Meeting", 40),
    ):
        created_at = now - timedelta(days=offset_days)
        await connection.execute(
            text("""
                INSERT INTO journals (
                    id, user_id, title, content,
                    event_date_range_start, event_date_range_end,
                    created_at, updated_at
                )
                VALUES (:id, 'user1', :title, 'Notes', :created_at, :created_at,
                        :created_at, :created_at)
            """),
            {"id": journal_id, "title": title, "created_at": created_at},
        )
        await connection.execute(
            text("""
                INSERT INTO journal_contact_relationships
                    (journal_id, contact_id, relationship_type)
                VALUES (:journal_id, :contact_id, 'MENTION')
            """),
            {"journal_id": journal_id, "contact_id": CONTACT_ID},
        )

    for field_name, offset_days in (("first_name", 10), ("company", 40)):
        await connection.execute(
            text("""
                INSERT INTO field_history
                    (entity_id, entity_type, field_name, new_value, created_at)
                VALUES (:entity_id, 'contact', :field_name, 'changed', :created_at)
            """),
            {
                "entity_id": CONTACT_ID,
                "field_name": field_name,
                "created_at": now - timedelta(days=offset_days),
            },
        )

    # A change to any of the contact's children is activity on the contact, and
    # the activity count has always included all four types. Each id below is
    # genuinely one of this contact's own children, so the count holds both
    # under today's predicate and under the corrected one in #1396 — the pin
    # asserts the behaviour, not the bug.
    for entity_type, entity_id in (
        ("contact_method", 1),
        ("contact_address", 1),
        ("contact_note", 1),
        ("contact_tag", 1),
    ):
        await connection.execute(
            text("""
                INSERT INTO field_history
                    (entity_id, entity_type, field_name, new_value, created_at)
                VALUES (:entity_id, :entity_type, 'field', 'changed', :created_at)
            """),
            {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "created_at": now - timedelta(days=3),
            },
        )


async def _stored_timestamps(
    connection: AsyncConnection, contact_id: int
) -> tuple[datetime, datetime]:
    """The contact's ``created_at`` and ``updated_at`` as the database holds them."""
    row = (
        await connection.execute(
            text("SELECT created_at, updated_at FROM contacts WHERE id = :id"),
            {"id": contact_id},
        )
    ).one()
    return row.created_at, row.updated_at


async def test_contact_document_is_unchanged(
    async_connection: AsyncConnection,
) -> None:
    """Every field of the indexed contact document, for a fully populated contact."""
    now = datetime.now(UTC)
    await _seed_full_contact(async_connection, now=now)
    created_at, updated_at = await _stored_timestamps(async_connection, CONTACT_ID)

    indexer = SearchIndexer(db_connection=async_connection)
    document = await indexer._fetch_complete_contact_data(CONTACT_ID)

    assert document is not None
    normalised: dict[str, Any] = {
        **document,
        "journal_mentions": sorted(document["journal_mentions"]),
    }
    assert normalised == {
        "id": CONTACT_ID,
        "first_name": "Ada",
        "last_name": "Lovelace",
        "middle_name": "Byron",
        "nick_name": "Countess",
        "company": "Analytical Engines",
        "job_title": "Mathematician",
        "full_name": "Ada Lovelace",
        "email": "ada@example.com",
        "emails": ["ada@example.com", "ada.alt@example.com"],
        "phone": "+61400000000",
        "phones": ["+61400000000"],
        "notes_content": "Newer note. Older note.",
        "tags": ["analytical", "colleagues"],
        "relationships": ["Friend of Charles Babbage"],
        "entity_type": "contact",
        "is_favourite": True,
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
        "summary_text": "Ada is a long-standing collaborator.",
        "important_dates": ["Birthday (December 10)"],
        "journal_mentions": ["Old Meeting", "Recent Meeting"],
        "has_summary": True,
        "last_activity_date": updated_at.isoformat(),
        "journal_count_30d": 1,
        "activity_count_30d": 5,
    }


async def test_last_activity_date_follows_the_latest_journal(
    async_connection: AsyncConnection,
) -> None:
    """A journal newer than the contact row moves the last-activity instant.

    The pin above fixes the case where ``contacts.updated_at`` is the newest of
    the three sources; this and the test below fix the two branches where it is
    not, which a single golden document cannot show. All three matter because
    this file's whole job is to be the pin a later extraction cannot slip past:
    a source left unasserted here is a source that extraction could drop while
    the suite still passed.
    """
    now = datetime.now(UTC)
    await _seed_full_contact(async_connection, now=now)
    newer_journal_at = now + timedelta(hours=1)
    await async_connection.execute(
        text("UPDATE journals SET created_at = :created_at WHERE id = 1"),
        {"created_at": newer_journal_at},
    )
    stored = (
        await async_connection.execute(
            text("SELECT created_at FROM journals WHERE id = 1")
        )
    ).scalar_one()

    indexer = SearchIndexer(db_connection=async_connection)
    document = await indexer._fetch_complete_contact_data(CONTACT_ID)

    assert document is not None
    assert document["last_activity_date"] == stored.isoformat()


async def test_last_activity_date_follows_the_latest_recorded_change(
    async_connection: AsyncConnection,
) -> None:
    """A ``field_history`` row newer than either other source moves it too.

    The third of the three branches. Without it the suite would pass for an
    extraction that computed the instant from the contact row and its journals
    alone, which is exactly the silent regression the pin exists to catch.
    """
    now = datetime.now(UTC)
    await _seed_full_contact(async_connection, now=now)
    await async_connection.execute(
        text("""
            UPDATE field_history
            SET created_at = :created_at
            WHERE entity_type = 'contact'
              AND entity_id = :entity_id
              AND field_name = 'first_name'
        """),
        {"created_at": now + timedelta(hours=1), "entity_id": CONTACT_ID},
    )
    stored = (
        await async_connection.execute(
            text("""
                SELECT created_at FROM field_history
                WHERE entity_type = 'contact'
                  AND entity_id = :entity_id
                  AND field_name = 'first_name'
            """),
            {"entity_id": CONTACT_ID},
        )
    ).scalar_one()

    indexer = SearchIndexer(db_connection=async_connection)
    document = await indexer._fetch_complete_contact_data(CONTACT_ID)

    assert document is not None
    assert document["last_activity_date"] == stored.isoformat()
