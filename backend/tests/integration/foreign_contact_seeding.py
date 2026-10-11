"""Another user's contact, furnished for the cross-user isolation suites.

The REST suite (``api/test_contact_ownership.py``) and the MCP suite
(``mcp/test_mcp_contact_ownership.py``) ask the same question of different
surfaces: acting as the test user, name another user's contact and expect
what an absent id gets. Both need the same contact — with every child row a
real one carries, so each request names ids that exist and can be refused
only for ownership — and the same proof that a refusal changed nothing.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime

from core_shared.models.contacts.entities import (
    ContactAddress,
    ContactMethod,
    ContactNote,
    ContactRelationship,
    ContactSummary,
    ImportantDate,
    MethodType,
    RelationshipType,
    Tag,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.contacts.value_objects import TagName
from core_shared.models.journals import (
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from core_shared.models.journals.attendee_status import AttendeeStatus
from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import (
    SqlContactRelationshipRepository,
    SqlContactRepository,
    SqlContactSummaryRepository,
    SqlTagRepository,
)
from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.models import FieldHistoryEntry
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.contact_seeding import OTHER_USER_ID, TEST_USER_ID, seed_contact
from tests.integration.tasks.task_seeding import (
    create_journal,
    create_task,
    link_contact,
)

# The foreign contact's private text, every string seeded on it. Each is
# asserted absent from every response: a refusal that still echoed a name, an
# email or a linked person would leak what it refused.
OTHER_FIRST_NAME = "Theodora"
OTHER_LAST_NAME = "Blackwood-Quince"
OTHER_PARTNER_NAME = "Ignatius"
OTHER_EMAIL = "theodora@foreign.example"
OTHER_STREET = "3 Stone Lane"
OTHER_NOTE = "Keeps the spare key under the third stone."
OTHER_SUMMARY = "Met at the hut; owes me a rope."
OTHER_FORMER_NAME = "Dora Quince"
OTHER_JOURNAL_TITLE = "Scrambled the north ridge"
OTHER_TASK_TEXT = "Return the borrowed crampons"
IMMICH_PERSON_ID = "person-theirs"
OTHER_TEXT = (
    OTHER_FIRST_NAME,
    OTHER_LAST_NAME,
    OTHER_PARTNER_NAME,
    OTHER_EMAIL,
    OTHER_STREET,
    OTHER_NOTE,
    OTHER_SUMMARY,
    OTHER_FORMER_NAME,
    OTHER_JOURNAL_TITLE,
    OTHER_TASK_TEXT,
    IMMICH_PERSON_ID,
)

# The caller's own contact: the legitimate other half of a merge or a
# relationship. It shares the foreign contact's favourite flag and tag, so
# only the owner filter can tell the two apart in a list.
OWN_FIRST_NAME = "Sarah"

TAG_NAME = "climbing-partners"
UNASSIGNED_TAG_NAME = "unassigned"

# Everything a refused request must leave identical. Whole tables rather than
# the foreign contact's rows alone: a refused merge or relationship must not
# touch the caller's own contact either. The outbox and edit-event tables
# catch a deferred write: no event consumers run, so a refused request that
# enqueued a history, summary or search update would otherwise leave every
# other table unchanged. Written out as whole statements so nothing here
# builds SQL by string formatting.
UNCHANGED_ROWS: dict[str, TextClause] = {
    "contacts": text("SELECT to_jsonb(t) FROM contacts t"),
    "methods": text("SELECT to_jsonb(t) FROM contact_methods t"),
    "addresses": text("SELECT to_jsonb(t) FROM contact_addresses t"),
    "notes": text("SELECT to_jsonb(t) FROM contact_notes t"),
    "important_dates": text("SELECT to_jsonb(t) FROM contact_important_dates t"),
    "tag_assignments": text("SELECT to_jsonb(t) FROM contact_tags t"),
    "tags": text("SELECT to_jsonb(t) FROM tags t"),
    "relationships": text("SELECT to_jsonb(t) FROM contact_relationships t"),
    "summaries": text("SELECT to_jsonb(t) FROM contact_summaries t"),
    "history": text("SELECT to_jsonb(t) FROM field_history t"),
    "links": text("SELECT to_jsonb(t) FROM sync_metadata t"),
    "outbox": text("SELECT to_jsonb(t) FROM outbox_events t"),
    "edit_events": text("SELECT to_jsonb(t) FROM contact_edit_event t"),
    # A merge re-points the contact's journal and task links.
    "journals": text("SELECT to_jsonb(t) FROM journals t"),
    "journal_links": text("SELECT to_jsonb(t) FROM journal_contact_relationships t"),
    "tasks": text("SELECT to_jsonb(t) FROM tasks t"),
    "task_links": text("SELECT to_jsonb(t) FROM task_contacts t"),
}

# Seeded rows carry a timestamp from before the request. Seeding and request
# share one transaction, and now() is that transaction's start, so a refused
# request that touched updated_at would otherwise write the value already there.
SEEDED_LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)
BACKDATE_SEEDED_ROWS = tuple(
    text(statement)
    for statement in (
        "UPDATE contacts SET updated_at = :then",
        "UPDATE contact_methods SET updated_at = :then",
        "UPDATE contact_addresses SET updated_at = :then",
        "UPDATE contact_notes SET updated_at = :then",
        "UPDATE contact_important_dates SET updated_at = :then",
        "UPDATE contact_relationships SET updated_at = :then",
        "UPDATE contact_summaries SET updated_at = :then",
        "UPDATE tags SET updated_at = :then",
        "UPDATE sync_metadata SET updated_at = :then",
        "UPDATE journals SET updated_at = :then",
        "UPDATE tasks SET updated_at = :then",
    )
)
EVERY_UPDATED_AT = text(
    """
    SELECT updated_at FROM contacts UNION SELECT updated_at FROM contact_methods
    UNION SELECT updated_at FROM contact_addresses
    UNION SELECT updated_at FROM contact_notes
    UNION SELECT updated_at FROM contact_important_dates
    UNION SELECT updated_at FROM contact_relationships
    UNION SELECT updated_at FROM contact_summaries
    UNION SELECT updated_at FROM tags UNION SELECT updated_at FROM sync_metadata
    UNION SELECT updated_at FROM journals UNION SELECT updated_at FROM tasks
    """
)

# Queues that only an insert can disturb, so they may start empty. Every other
# table holds seeded rows, or a refused request that moved or deleted one
# would compare an empty table with an empty table.
EMPTY_UNTIL_WRITTEN = frozenset({"outbox", "edit_events"})

# The owned tables whose foreign rows the owner's replay hands to the caller.
_OWNED_TABLES = (
    text("UPDATE contacts SET user_id = :me WHERE user_id = :them"),
    text("UPDATE sync_metadata SET user_id = :me WHERE user_id = :them"),
    text("UPDATE field_history SET user_id = :me WHERE user_id = :them"),
    text("UPDATE journals SET user_id = :me WHERE user_id = :them"),
    text("UPDATE tasks SET user_id = :me WHERE user_id = :them"),
)


@dataclass(frozen=True)
class ForeignContact:
    """Another user's contact, with every child row a real one carries.

    The ids travel together because each request needs a different one, and all
    of them name rows that genuinely exist — otherwise the endpoint would have
    refused the request on its own account.
    """

    contact_id: int
    partner_id: int
    method_id: int
    address_id: int
    note_id: int
    date_id: int
    tag_id: int
    unassigned_tag_id: int
    relationship_id: int
    own_contact_id: int

    def placeholders(self) -> dict[str, str]:
        return {
            "contact_id": str(self.contact_id),
            "partner_id": str(self.partner_id),
            "method_id": str(self.method_id),
            "address_id": str(self.address_id),
            "note_id": str(self.note_id),
            "date_id": str(self.date_id),
            "tag_id": str(self.tag_id),
            "unassigned_tag_id": str(self.unassigned_tag_id),
            "relationship_id": str(self.relationship_id),
            "own_contact_id": str(self.own_contact_id),
        }


async def snapshot(
    connection: AsyncConnection, rows: dict[str, TextClause] = UNCHANGED_ROWS
) -> dict[str, list[str]]:
    """Every row a contact write could reach, as comparable JSON.

    Stricter than counting rows: it catches a rewritten name, a flipped
    favourite and a disabled summary, none of which move a count.
    """
    state: dict[str, list[str]] = {}
    for name, query in rows.items():
        result = await connection.execute(query)
        state[name] = sorted(str(row[0]) for row in result.fetchall())
    return state


def assert_nothing_leaked(body: str, *, supplied: Collection[object] = ()) -> None:
    """The response names nothing seeded on the foreign contact.

    ``supplied`` is what the caller itself sent, which a refusal may echo
    without revealing anything (an external id it looked up, say).
    """
    for fragment in OTHER_TEXT:
        if fragment in supplied:
            continue
        assert fragment not in body, (
            f"the response names the foreign contact ({fragment!r})"
        )


async def hand_foreign_rows_to_caller(connection: AsyncConnection) -> None:
    """Make the caller the owner of everything the foreign fixture seeded."""
    for statement in _OWNED_TABLES:
        await connection.execute(statement, {"me": TEST_USER_ID, "them": OTHER_USER_ID})


async def _link_to_immich(connection: AsyncConnection, contact_id: int) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO sync_metadata (
                user_id, internal_id, integration_source, external_id,
                last_synced_at, version_hash, sync_status, retry_count,
                internal_entity_type, external_entity_type, created_at, updated_at
            ) VALUES (
                :uid, :iid, 'immich', :eid, now(), 'h', 'success', 0,
                'contact', 'person', now(), now()
            )
            """
        ),
        {"uid": OTHER_USER_ID, "iid": contact_id, "eid": IMMICH_PERSON_ID},
    )


async def _tag(repo: SqlTagRepository, name: str) -> int:
    tag = await repo.save(Tag(name=TagName(name)))
    assert tag.id is not None
    return tag.id


async def seed_foreign_contact(async_connection: AsyncConnection) -> ForeignContact:
    """Another user's contact, furnished the way a real one would be.

    Also seeds the caller's own contact, a favourite carrying the same tag, and
    backdates every ``updated_at`` (see :data:`SEEDED_LONG_AGO`).
    """
    repo = SqlContactRepository(async_connection)
    contact_id = await seed_contact(
        async_connection,
        user_id=OTHER_USER_ID,
        first_name=OTHER_FIRST_NAME,
        last_name=OTHER_LAST_NAME,
        is_favourite=True,
    )
    partner_id = await seed_contact(
        async_connection, user_id=OTHER_USER_ID, first_name=OTHER_PARTNER_NAME
    )

    method = await repo.add_method(
        contact_id,
        ContactMethod(
            method_type=MethodType.EMAIL,
            value=OTHER_EMAIL,
            contact_id=contact_id,
            is_primary=True,
        ),
    )
    address = await repo.add_address(
        contact_id,
        ContactAddress(
            street_line_1=OTHER_STREET, country_code="AU", contact_id=contact_id
        ),
    )
    note = await repo.add_note(
        contact_id, ContactNote(content=OTHER_NOTE, contact_id=contact_id)
    )
    important_date = await repo.add_important_date(
        contact_id,
        ImportantDate(
            contact_id=contact_id,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.FULL,
            year=1985,
            month=3,
            day=14,
        ),
    )

    tag_repo = SqlTagRepository(async_connection)
    tag_id = await _tag(tag_repo, TAG_NAME)
    unassigned_tag_id = await _tag(tag_repo, UNASSIGNED_TAG_NAME)
    await repo.assign_tag(contact_id, tag_id)

    relationship = await SqlContactRelationshipRepository(async_connection).create(
        ContactRelationship(
            from_contact_id=contact_id,
            to_contact_id=partner_id,
            relationship_type=RelationshipType.PARTNER,
        )
    )
    await SqlContactSummaryRepository(async_connection).upsert(
        ContactSummary(contact_id=contact_id, summary_text=OTHER_SUMMARY)
    )
    await _link_to_immich(async_connection, contact_id)
    await SqlFieldHistoryRepository(async_connection).record_change(
        FieldHistoryEntry(
            entity_type="contact",
            entity_id=contact_id,
            field_name="first_name",
            old_value=OTHER_FORMER_NAME,
            new_value=OTHER_FIRST_NAME,
            user_id=OTHER_USER_ID,
        )
    )

    journal_id = await create_journal(
        SqlJournalRepository(async_connection),
        title=OTHER_JOURNAL_TITLE,
        user_id=OTHER_USER_ID,
    )
    await SqlJournalContactRelationshipRepository(async_connection).create(
        JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
            status=AttendeeStatus.NO_REPLY,
        )
    )
    task_id = await create_task(
        async_connection,
        creating_journal_id=journal_id,
        due_journal_id=journal_id,
        text=OTHER_TASK_TEXT,
        user_id=OTHER_USER_ID,
    )
    await link_contact(async_connection, task_id=task_id, contact_id=contact_id)

    own_contact_id = await seed_contact(
        async_connection, first_name=OWN_FIRST_NAME, is_favourite=True
    )
    await repo.assign_tag(own_contact_id, tag_id)

    for backdate in BACKDATE_SEEDED_ROWS:
        await async_connection.execute(backdate, {"then": SEEDED_LONG_AGO})

    assert method.id is not None
    assert address.id is not None
    assert note.id is not None
    assert important_date.id is not None
    assert relationship.id is not None
    return ForeignContact(
        contact_id=contact_id,
        partner_id=partner_id,
        method_id=method.id,
        address_id=address.id,
        note_id=note.id,
        date_id=important_date.id,
        tag_id=tag_id,
        unassigned_tag_id=unassigned_tag_id,
        relationship_id=relationship.id,
        own_contact_id=own_contact_id,
    )
