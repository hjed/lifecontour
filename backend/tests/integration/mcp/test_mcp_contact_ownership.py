"""Every MCP tool that names a contact answers for another user's as for none.

The MCP counterpart of ``api/test_contact_ownership.py``. Acting as the test
user, each tool is handed another user's contact and then an id that does not
exist, and must give the same answer to both: the same payload once the two ids
are masked, naming nothing of the foreign contact, and changing nothing.

**Compared with itself, not with a shape.** MCP tools refuse in different
words — a contact not-found, a validation error, a ``ValueError`` — and that is
fine. What must not happen is a foreign id answered differently from a missing
one, which would confirm it exists.

**Every call is otherwise valid.** ``test_the_same_call_succeeds_for_the_owner``
replays each call after handing the foreign rows to the caller, so a refusal
cannot come from a bad argument or a second foreign id.

**The table is checked against the server.** The coverage guard reads every
registered tool's input schema; a tool that grows a contact-id argument fails
until it is listed here or in ``COVERED_ELSEWHERE`` with its reason.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest
from core_shared.models.contacts.entities import ImportantDate
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.history import Provenance
from core_shared.models.journals import JournalContactRelationship
from core_shared.models.journals.attendee_status import AttendeeStatus
from core_shared.models.journals.journal_relationship_types import (
    JournalContactRelationshipType,
)
from fastmcp import Client
from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import SqlContactRepository
from app.core.integrations.adapters.sql.contact_suggestion_ignore_repository import (
    SqlContactSuggestionIgnoreRepository,
)
from app.core.integrations.adapters.sql.unmatched_participant_email_repository import (
    SqlUnmatchedParticipantEmailRepository,
)
from app.core.integrations.models.unmatched_participant import (
    UnmatchedParticipantEmail,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.timezone_utils import resolve_timezone
from app.mcp.server import create_mcp_server
from tests.integration.contact_seeding import OTHER_USER_ID, TEST_USER_ID
from tests.integration.foreign_contact_seeding import (
    BACKDATE_SEEDED_ROWS,
    EMPTY_UNTIL_WRITTEN,
    IMMICH_PERSON_ID,
    OTHER_FIRST_NAME,
    OTHER_JOURNAL_TITLE,
    OWN_FIRST_NAME,
    SEEDED_LONG_AGO,
    TAG_NAME,
    UNCHANGED_ROWS,
    ForeignContact,
    assert_nothing_leaked,
    hand_foreign_rows_to_caller,
    seed_foreign_contact,
    snapshot,
)
from tests.integration.mcp.http_helpers import call_mcp_tool
from tests.integration.tasks.task_seeding import create_journal, create_task

# What an absent id looks like, for each kind of id a call can vary.
MISSING_ID = 999_999
MISSING_PERSON_ID = "person-nobody"

# A participant email the foreign contact's journal saw and nobody holds.
SUGGESTED_EMAIL = "rope.partner@suggested.example"
# An email the other user asked never to have suggested.
THEIR_IGNORED_EMAIL = "ignored@theirs.example"
THEIR_ATHLETE_ID = "athlete-theirs"

# The contact tables plus everything the integration tools here can reach.
MCP_UNCHANGED_ROWS: dict[str, TextClause] = {
    **UNCHANGED_ROWS,
    "conflicts": text("SELECT to_jsonb(t) FROM pending_entity_mappings t"),
    "suggestions": text(
        "SELECT to_jsonb(t) FROM journal_unmatched_participant_emails t"
    ),
    "suggestion_ignores": text("SELECT to_jsonb(t) FROM contact_suggestion_ignores t"),
    "athlete_mappings": text("SELECT to_jsonb(t) FROM strava_athlete_mappings t"),
}
MCP_BACKDATE_ROWS = (
    *BACKDATE_SEEDED_ROWS,
    text("UPDATE pending_entity_mappings SET updated_at = :then"),
    text("UPDATE journal_unmatched_participant_emails SET updated_at = :then"),
    text("UPDATE strava_athlete_mappings SET updated_at = :then"),
)
_MCP_ONLY_UPDATED_AT = text(
    """
    SELECT updated_at FROM pending_entity_mappings
    UNION SELECT updated_at FROM journal_unmatched_participant_emails
    UNION SELECT updated_at FROM strava_athlete_mappings
    """
)
_HAND_INTEGRATION_ROWS_TO_CALLER = (
    text("UPDATE pending_entity_mappings SET user_id = :me WHERE user_id = :them"),
    text("UPDATE strava_athlete_mappings SET user_id = :me WHERE user_id = :them"),
)
_SEED_CONFLICT = text(
    """
    INSERT INTO pending_entity_mappings
        (user_id, integration_source, external_entity_id,
         external_entity_name, candidate_contact_ids, status)
    VALUES (:user_id, 'immich', :person_id, 'Ada Lovelace', '[]'::jsonb, 'unresolved')
    RETURNING id
    """
)
_SEED_ATHLETE_MAPPING = text(
    """
    INSERT INTO strava_athlete_mappings
        (user_id, strava_athlete_id, strava_athlete_name, contact_id)
    VALUES (:user_id, :athlete_id, 'Their Athlete', :contact_id)
    """
)


@dataclass(frozen=True)
class OwnedState:
    """The foreign contact plus what the MCP tools need besides it.

    The caller's journals, task and Immich conflict are the legitimate other
    half of a link; the other user's conflict, suggestion, ignore and athlete
    mapping are what a refused call must leave alone.
    """

    contact: ForeignContact
    own_journal_id: int
    own_future_journal_id: int
    own_task_id: int
    own_conflict_id: int
    their_conflict_id: int

    def values(self) -> dict[str, int | str]:
        ids: dict[str, int | str] = {
            name: int(value) for name, value in self.contact.placeholders().items()
        }
        return {
            **ids,
            "own_journal_id": self.own_journal_id,
            "own_future_journal_id": self.own_future_journal_id,
            "own_task_id": self.own_task_id,
            "own_conflict_id": self.own_conflict_id,
            "their_conflict_id": self.their_conflict_id,
            "person_id": IMMICH_PERSON_ID,
        }


@dataclass(frozen=True)
class CrossUserCall:
    """One MCP call naming another user's row.

    ``arguments`` holds ``"{name}"`` placeholders, filled from
    :meth:`OwnedState.values`. ``varies`` is the one placeholder swapped for an
    absent value in the comparison call; every other id is the caller's own or
    shared by both calls. ``label`` tells two calls of one tool apart.
    """

    tool: str
    arguments: dict[str, Any]
    varies: str = "contact_id"
    label: str = ""
    # False only where the owner's replay cannot succeed for a reason that is
    # not ownership; each such entry says why.
    replays: bool = True

    @property
    def id(self) -> str:
        return f"{self.tool}[{self.label}]" if self.label else self.tool

    def missing_value(self) -> int | str:
        return MISSING_PERSON_ID if self.varies == "person_id" else MISSING_ID

    def filled(self, values: dict[str, int | str]) -> dict[str, Any]:
        filled: dict[str, Any] = _fill(self.arguments, values)
        return filled


_PLACEHOLDER = re.compile(r"^\{(\w+)\}$")


def _fill(value: Any, values: dict[str, int | str]) -> Any:
    """Replace every ``"{name}"`` string, at any depth, with its typed value."""
    if isinstance(value, dict):
        return {key: _fill(item, values) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill(item, values) for item in value]
    if isinstance(value, str) and (match := _PLACEHOLDER.match(value)):
        return values[match.group(1)]
    return value


# Each call is refused for the foreign contact exactly as for a missing one.
CROSS_USER_CALLS: tuple[CrossUserCall, ...] = (
    CrossUserCall("get_contact", {"contact_id": "{contact_id}"}),
    CrossUserCall(
        "update_contact",
        {"request": {"contact_id": "{contact_id}", "first_name": "Rewritten"}},
    ),
    CrossUserCall(
        "merge_contacts",
        {
            "survivor_contact_id": "{contact_id}",
            "source_contact_id": "{own_contact_id}",
        },
        label="theirs survives",
    ),
    # The source is owner-checked too: a merge would copy their methods and
    # notes into a contact the caller can open, then delete theirs.
    CrossUserCall(
        "merge_contacts",
        {
            "survivor_contact_id": "{own_contact_id}",
            "source_contact_id": "{contact_id}",
        },
        label="theirs absorbed",
    ),
    CrossUserCall("toggle_contact_favourite", {"contact_id": "{contact_id}"}),
    CrossUserCall(
        "set_contact_field_archived",
        {
            "contact_id": "{contact_id}",
            "kind": "email",
            "field_id": "{method_id}",
            "archived": True,
        },
    ),
    # Their email named through the caller's own contact. Not replayed: handed
    # to the caller it is still not a value of this contact.
    CrossUserCall(
        "set_contact_field_archived",
        {
            "contact_id": "{own_contact_id}",
            "kind": "email",
            "field_id": "{method_id}",
            "archived": True,
        },
        varies="method_id",
        label="their email",
        replays=False,
    ),
    CrossUserCall("get_contact_relationships", {"contact_id": "{contact_id}"}),
    CrossUserCall(
        "add_contact_relationship",
        {
            "request": {
                "contact_id": "{contact_id}",
                "target_contact_id": "{own_contact_id}",
                "relationship_type": "friend",
            }
        },
        label="from theirs",
    ),
    CrossUserCall(
        "add_contact_relationship",
        {
            "request": {
                "contact_id": "{own_contact_id}",
                "target_contact_id": "{contact_id}",
                "relationship_type": "friend",
            }
        },
        label="to theirs",
    ),
    CrossUserCall(
        "update_contact_relationship",
        {
            "request": {
                "contact_id": "{contact_id}",
                "relationship_id": "{relationship_id}",
                "relationship_type": "sibling",
            }
        },
    ),
    # Their relationship named through the caller's own contact. Not replayed:
    # handed to the caller it is still not a relationship of this contact.
    CrossUserCall(
        "update_contact_relationship",
        {
            "request": {
                "contact_id": "{own_contact_id}",
                "relationship_id": "{relationship_id}",
                "relationship_type": "sibling",
            }
        },
        varies="relationship_id",
        label="their relationship",
        replays=False,
    ),
    CrossUserCall(
        "remove_contact_relationship",
        {"contact_id": "{contact_id}", "relationship_id": "{relationship_id}"},
    ),
    CrossUserCall(
        "remove_contact_relationship",
        {"contact_id": "{own_contact_id}", "relationship_id": "{relationship_id}"},
        varies="relationship_id",
        label="their relationship",
        replays=False,
    ),
    CrossUserCall(
        "get_contact_by_external_id",
        {"source": "immich", "external_id": "{person_id}"},
        varies="person_id",
    ),
    CrossUserCall("get_contact_journals", {"contact_id": "{contact_id}"}),
    CrossUserCall(
        "link_journal_to_contact",
        {
            "journal_id": "{own_journal_id}",
            "contact_id": "{contact_id}",
            "relationship_type": "PARTICIPANT",
        },
    ),
    CrossUserCall(
        "create_task",
        {
            "creating_journal_id": "{own_journal_id}",
            "due_journal_id": "{own_future_journal_id}",
            "text": "Lend them the rope",
            "contact_ids": ["{contact_id}"],
        },
    ),
    CrossUserCall(
        "link_task_to_contact",
        {"task_id": "{own_task_id}", "contact_id": "{contact_id}"},
    ),
    CrossUserCall(
        "resolve_immich_conflict",
        {
            "conflict_id": "{own_conflict_id}",
            "action": "link",
            "contact_id": "{contact_id}",
        },
    ),
    CrossUserCall(
        "resolve_immich_conflict",
        {
            "conflict_id": "{their_conflict_id}",
            "action": "link",
            "contact_id": "{own_contact_id}",
        },
        varies="their_conflict_id",
        label="their conflict",
    ),
    CrossUserCall(
        "accept_contact_suggestion",
        {"email": SUGGESTED_EMAIL, "contact_id": "{contact_id}"},
    ),
)

# Filters that answer an unknown contact with nothing rather than an error.
# The foreign contact must get the same nothing; the owner, something.
NO_RESULT_CALLS: tuple[CrossUserCall, ...] = (
    CrossUserCall("get_strava_athlete_mappings", {"contact_id": "{contact_id}"}),
)

# Tools taking a contact id that are deliberately not in the tables above.
COVERED_ELSEWHERE: dict[str, str] = {
    "unlink_task_from_contact": (
        "keyed on the task, which is owner-checked first; the REST counterpart "
        "is exempt from test_contact_ownership.py for the same reason"
    ),
    "search_journals": (
        "the contact is a filter within the caller's own journals; the search "
        "is owner-filtered before it applies"
    ),
    # Their contact_relationships argument is an untyped list, so the schema
    # guard cannot see it; listed so the gap is on record.
    "create_journal_entry": (
        "silently skips a foreign or missing contact link; the journal "
        "participant rule is Phase 11's cross-entity check"
    ),
    "update_journal_entry": (
        "silently skips a foreign or missing contact link; the journal "
        "participant rule is Phase 11's cross-entity check"
    ),
}


async def _their_journal_id(
    connection: AsyncConnection, contact: ForeignContact
) -> int:
    """The other user's journal, the one their contact took part in."""
    journal_id: int = (
        await connection.execute(
            text(
                "SELECT journal_id FROM journal_contact_relationships "
                "WHERE contact_id = :id"
            ),
            {"id": contact.contact_id},
        )
    ).scalar_one()
    return journal_id


async def _seed_mcp_state(connection: AsyncConnection) -> OwnedState:
    contact = await seed_foreign_contact(connection)
    journals = SqlJournalRepository(connection)
    own_journal_id = await create_journal(journals, user_id=TEST_USER_ID)
    own_future_journal_id = await create_journal(
        journals, days_offset=7, user_id=TEST_USER_ID
    )
    own_task_id = await create_task(
        connection,
        creating_journal_id=own_journal_id,
        due_journal_id=own_future_journal_id,
        user_id=TEST_USER_ID,
    )
    own_conflict_id = (
        await connection.execute(
            _SEED_CONFLICT, {"user_id": TEST_USER_ID, "person_id": "person-mine"}
        )
    ).scalar_one()
    their_conflict_id = (
        await connection.execute(
            _SEED_CONFLICT, {"user_id": OTHER_USER_ID, "person_id": "person-pending"}
        )
    ).scalar_one()

    # The foreign contact's journal saw the suggested email.
    their_journal_id = await _their_journal_id(connection, contact)
    await SqlUnmatchedParticipantEmailRepository(connection).replace_for_journal(
        their_journal_id,
        [
            UnmatchedParticipantEmail(
                journal_id=their_journal_id,
                email=SUGGESTED_EMAIL,
                relationship_type=JournalContactRelationshipType.PARTICIPANT,
            )
        ],
    )
    await SqlContactSuggestionIgnoreRepository(connection).ignore(
        OTHER_USER_ID, THEIR_IGNORED_EMAIL, Provenance.UI
    )
    await connection.execute(
        _SEED_ATHLETE_MAPPING,
        {
            "user_id": OTHER_USER_ID,
            "athlete_id": THEIR_ATHLETE_ID,
            "contact_id": contact.contact_id,
        },
    )

    for backdate in MCP_BACKDATE_ROWS:
        await connection.execute(backdate, {"then": SEEDED_LONG_AGO})
    return OwnedState(
        contact=contact,
        own_journal_id=own_journal_id,
        own_future_journal_id=own_future_journal_id,
        own_task_id=own_task_id,
        own_conflict_id=own_conflict_id,
        their_conflict_id=their_conflict_id,
    )


@pytest.fixture
async def owned_state(async_connection: AsyncConnection) -> OwnedState:
    return await _seed_mcp_state(async_connection)


async def _hand_everything_to_caller(connection: AsyncConnection) -> None:
    await hand_foreign_rows_to_caller(connection)
    for statement in _HAND_INTEGRATION_ROWS_TO_CALLER:
        await connection.execute(statement, {"me": TEST_USER_ID, "them": OTHER_USER_ID})


async def _call(
    authenticated_lifespan_client: Callable[..., Any],
    tool: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    async with authenticated_lifespan_client() as client:
        return await call_mcp_tool(client, tool, arguments)


def _masked(payload: dict[str, Any], *ids: int | str) -> str:
    """The payload as text, with each named id replaced by ``<id>``.

    Word boundaries keep a short id from rewriting a longer number that
    happens to contain it.
    """
    body = repr(sorted(payload.items()))
    for value in ids:
        body = re.sub(rf"\b{re.escape(str(value))}\b", "<id>", body)
    return body


def _supplied(call: CrossUserCall, values: dict[str, int | str]) -> set[int | str]:
    """The argument values the call itself sent."""
    return set(values.values()) & set(_flat_values(call.filled(values)))


def _flat_values(value: Any) -> list[object]:
    if isinstance(value, dict):
        return [item for nested in value.values() for item in _flat_values(nested)]
    if isinstance(value, list):
        return [item for nested in value for item in _flat_values(nested)]
    return [value]


def _is_error(payload: dict[str, Any]) -> bool:
    return "error" in payload


@pytest.mark.integration
class TestMcpContactOwnershipIsEnforced:
    """No MCP tool acts on, or reveals, a contact the caller does not own."""

    @pytest.mark.parametrize("call", CROSS_USER_CALLS, ids=lambda call: call.id)
    async def test_another_users_contact_reads_as_an_absent_one(
        self,
        call: CrossUserCall,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
        owned_state: OwnedState,
    ) -> None:
        """The same refusal as a missing id, naming nothing, changing nothing."""
        values = owned_state.values()
        foreign_value = values[call.varies]
        before = await snapshot(async_connection, MCP_UNCHANGED_ROWS)

        foreign = await _call(
            authenticated_lifespan_client, call.tool, call.filled(values)
        )
        after_foreign = await snapshot(async_connection, MCP_UNCHANGED_ROWS)
        missing = await _call(
            authenticated_lifespan_client,
            call.tool,
            call.filled({**values, call.varies: call.missing_value()}),
        )

        assert _is_error(foreign), f"{call.id} acted on another user's row: {foreign}"
        masked = _masked(foreign, foreign_value, call.missing_value())
        assert masked == _masked(missing, foreign_value, call.missing_value())
        # On the unmasked payload: masking a small id could erase a digit of
        # leaked text along with it.
        assert_nothing_leaked(repr(foreign), supplied=_supplied(call, values))
        assert after_foreign == before

    @pytest.mark.parametrize("call", NO_RESULT_CALLS, ids=lambda call: call.id)
    async def test_another_users_contact_filters_to_nothing(
        self,
        call: CrossUserCall,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
        owned_state: OwnedState,
    ) -> None:
        values = owned_state.values()
        foreign_value = values[call.varies]
        before = await snapshot(async_connection, MCP_UNCHANGED_ROWS)

        foreign = await _call(
            authenticated_lifespan_client, call.tool, call.filled(values)
        )
        missing = await _call(
            authenticated_lifespan_client,
            call.tool,
            call.filled({**values, call.varies: call.missing_value()}),
        )

        masked = _masked(foreign, foreign_value, call.missing_value())
        assert masked == _masked(missing, foreign_value, call.missing_value())
        assert THEIR_ATHLETE_ID not in repr(foreign)
        assert_nothing_leaked(repr(foreign), supplied=_supplied(call, values))
        assert await snapshot(async_connection, MCP_UNCHANGED_ROWS) == before

    @pytest.mark.parametrize(
        "call",
        [call for call in CROSS_USER_CALLS if call.replays],
        ids=lambda call: call.id,
    )
    async def test_the_same_call_succeeds_for_the_owner(
        self,
        call: CrossUserCall,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
        owned_state: OwnedState,
    ) -> None:
        """Handed the rows, the caller's identical call goes through.

        This gives each refusal above its weight: a call the owner could not
        make either would be refused whether or not ownership was checked.
        """
        await _hand_everything_to_caller(async_connection)

        payload = await _call(
            authenticated_lifespan_client, call.tool, call.filled(owned_state.values())
        )

        assert not _is_error(payload), f"{call.id} failed for the owner: {payload}"

    @pytest.mark.parametrize("call", NO_RESULT_CALLS, ids=lambda call: call.id)
    async def test_the_same_filter_finds_the_owners_rows(
        self,
        call: CrossUserCall,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
        owned_state: OwnedState,
    ) -> None:
        await _hand_everything_to_caller(async_connection)

        payload = await _call(
            authenticated_lifespan_client, call.tool, call.filled(owned_state.values())
        )

        assert THEIR_ATHLETE_ID in repr(payload)

    @pytest.mark.parametrize(
        "call",
        [
            call
            for call in CROSS_USER_CALLS
            if call.tool.endswith("_contact_relationship")
            and call.tool != "add_contact_relationship"
            and call.varies == "contact_id"
        ],
        ids=lambda call: call.id,
    )
    async def test_a_relationship_is_reached_through_a_proven_contact(
        self,
        call: CrossUserCall,
        authenticated_lifespan_client: Callable[..., Any],
        owned_state: OwnedState,
    ) -> None:
        """The contact is proved before its relationship is looked at.

        As over REST: naming their contact answers that the contact is not
        found, not that the relationship is foreign to it.
        """
        payload = await _call(
            authenticated_lifespan_client, call.tool, call.filled(owned_state.values())
        )

        assert payload["error"] == "Contact not found", payload

    async def test_every_snapshotted_table_starts_with_rows(
        self, async_connection: AsyncConnection, owned_state: OwnedState
    ) -> None:
        """An empty table cannot show that a refused call moved or deleted a row."""
        state = await snapshot(async_connection, MCP_UNCHANGED_ROWS)

        assert {name for name, rows in state.items() if not rows} <= EMPTY_UNTIL_WRITTEN

    async def test_seeded_integration_rows_predate_the_call(
        self, async_connection: AsyncConnection, owned_state: OwnedState
    ) -> None:
        """The contact tables' backdating is asserted by the REST suite."""
        rows = (await async_connection.execute(_MCP_ONLY_UPDATED_AT)).scalars().all()

        assert set(rows) == {SEEDED_LONG_AGO}


async def _link_your_contact_to_both_journals(
    connection: AsyncConnection, owned_state: OwnedState
) -> int:
    """Link your contact to your journal and to theirs; return theirs."""
    their_journal_id = await _their_journal_id(connection, owned_state.contact)
    links = SqlJournalContactRelationshipRepository(connection)
    for journal_id in (owned_state.own_journal_id, their_journal_id):
        await links.create(
            JournalContactRelationship(
                journal_id=journal_id,
                contact_id=owned_state.contact.own_contact_id,
                relationship_type=JournalContactRelationshipType.PARTICIPANT,
                status=AttendeeStatus.NO_REPLY,
            )
        )
    return their_journal_id


async def _seed_birthday_today(connection: AsyncConnection, contact_id: int) -> None:
    """A birthday on the caller's today, resolved as the service resolves it."""
    zone = resolve_timezone(
        await SqlUserSettingsRepository(connection).get_timezone(TEST_USER_ID)
    )
    today = datetime.now(zone).date()
    await SqlContactRepository(connection).add_important_date(
        contact_id,
        ImportantDate(
            contact_id=contact_id,
            date_type=ImportantDateType.FIRST_MET,
            precision=DatePrecision.FULL,
            year=2010,
            month=today.month,
            day=today.day,
        ),
    )


@pytest.mark.integration
class TestMcpContactListsHoldOnlyYourContacts:
    """Their contact matches as well as yours; only yours is listed."""

    async def test_list_contacts_holds_only_your_contacts(
        self,
        authenticated_lifespan_client: Callable[..., Any],
        owned_state: OwnedState,
    ) -> None:
        payload = await _call(authenticated_lifespan_client, "list_contacts", {})

        listed = repr(payload)
        assert OWN_FIRST_NAME in listed
        assert_nothing_leaked(listed)

    async def test_your_contacts_journals_hold_only_your_journals(
        self,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
        owned_state: OwnedState,
    ) -> None:
        """A link from your contact to their journal names nothing of theirs."""
        own_contact_id = owned_state.contact.own_contact_id
        await _link_your_contact_to_both_journals(async_connection, owned_state)

        payload = await _call(
            authenticated_lifespan_client,
            "get_contact_journals",
            {"contact_id": own_contact_id},
        )

        assert [str(result["id"]) for result in payload["results"]] == [
            str(owned_state.own_journal_id)
        ]
        assert_nothing_leaked(repr(payload))

    async def test_their_newer_journal_does_not_use_up_the_limit(
        self,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
        owned_state: OwnedState,
    ) -> None:
        """The limit counts your journals, not links you cannot see."""
        own_contact_id = owned_state.contact.own_contact_id
        their_journal_id = await _link_your_contact_to_both_journals(
            async_connection, owned_state
        )
        # Links are read newest first: theirs is the newest.
        await async_connection.execute(
            text(
                "UPDATE journal_contact_relationships "
                "SET created_at = created_at + interval '1 day' "
                "WHERE contact_id = :contact AND journal_id = :journal"
            ),
            {"contact": own_contact_id, "journal": their_journal_id},
        )

        payload = await _call(
            authenticated_lifespan_client,
            "get_contact_journals",
            {"contact_id": own_contact_id, "limit": 1},
        )

        assert [str(result["id"]) for result in payload["results"]] == [
            str(owned_state.own_journal_id)
        ]

    async def test_the_owner_sees_the_contacts_journals(
        self,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
        owned_state: OwnedState,
    ) -> None:
        """Handed the contact and its journal, the caller reads the journal."""
        await _hand_everything_to_caller(async_connection)

        payload = await _call(
            authenticated_lifespan_client,
            "get_contact_journals",
            {"contact_id": owned_state.contact.contact_id},
        )

        assert OTHER_JOURNAL_TITLE in repr(payload)

    async def test_upcoming_dates_hold_only_your_contacts(
        self,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
        owned_state: OwnedState,
    ) -> None:
        """Both contacts have a date today; only the caller's is listed."""
        await _seed_birthday_today(async_connection, owned_state.contact.contact_id)
        await _seed_birthday_today(async_connection, owned_state.contact.own_contact_id)

        payload = await _call(
            authenticated_lifespan_client,
            "list_upcoming_important_dates",
            {"days_ahead": 1},
        )

        listed = repr(payload)
        assert OWN_FIRST_NAME in listed
        assert OTHER_FIRST_NAME not in listed
        assert_nothing_leaked(listed)


def _contact_id_properties(schema: Any) -> set[str]:
    """Every property, at any depth, whose name says it holds a contact id."""
    found: set[str] = set()
    if isinstance(schema, dict):
        for name in schema.get("properties", {}):
            if re.search(r"(^|_)contact_ids?$", name):
                found.add(name)
        for value in schema.values():
            found |= _contact_id_properties(value)
    elif isinstance(schema, list):
        for value in schema:
            found |= _contact_id_properties(value)
    return found


async def _registered_tools() -> dict[str, dict[str, Any]]:
    async with Client(create_mcp_server()) as client:
        return {tool.name: tool.input_schema for tool in await client.list_tools()}


@pytest.mark.integration
class TestMcpOwnershipCoverageIsComplete:
    """The call tables are checked against the server, not against memory."""

    async def test_the_guard_sees_nested_and_list_arguments(self) -> None:
        """A request model's field and a list of ids are found, not only args."""
        tools = await _registered_tools()

        assert _contact_id_properties(tools["update_contact"]) == {"contact_id"}
        assert _contact_id_properties(tools["create_task"]) == {"contact_ids"}
        assert _contact_id_properties(tools["merge_contacts"]) == {
            "survivor_contact_id",
            "source_contact_id",
        }

    async def test_every_tool_taking_a_contact_id_is_covered(self) -> None:
        tools = await _registered_tools()
        takes_a_contact = {
            name for name, schema in tools.items() if _contact_id_properties(schema)
        }
        tested = {call.tool for call in (*CROSS_USER_CALLS, *NO_RESULT_CALLS)}

        uncovered = takes_a_contact - tested - set(COVERED_ELSEWHERE)

        assert not uncovered, (
            "these tools take a contact id but have no ownership test: "
            f"{sorted(uncovered)}. Add each to CROSS_USER_CALLS, or to "
            "COVERED_ELSEWHERE with the reason it does not belong there."
        )

    async def test_the_tables_do_not_name_tools_the_server_lacks(self) -> None:
        tools = set(await _registered_tools())
        named = {call.tool for call in (*CROSS_USER_CALLS, *NO_RESULT_CALLS)} | set(
            COVERED_ELSEWHERE
        )

        assert not named - tools, f"no longer registered: {sorted(named - tools)}"


MISSING_TAG_ID = 999_999


@pytest.mark.integration
@pytest.mark.asyncio
class TestMcpContactTagsAreTheActingUsers:
    """The contact tag tools see and change only the acting user's tags.

    The foreign contact carries its owner's tag and the caller's contact the
    caller's own, so a refused write that touched an assignment, a contact or
    the outbox shows in the whole-table snapshot, not only in ``tags``.
    """

    async def test_listing_shows_only_your_tags(
        self,
        authenticated_lifespan_client: Callable[..., Any],
        owned_state: OwnedState,
    ) -> None:
        payload = await _call(authenticated_lifespan_client, "list_contact_tags", {})

        assert [tag["id"] for tag in payload["tags"]] == [
            str(owned_state.contact.own_tag_id)
        ]

    @pytest.mark.parametrize(
        ("tool", "arguments"),
        [
            ("update_contact_tag", {"tag_id": "{tag}", "name": "renamed"}),
            ("delete_contact_tag", {"tag_id": "{tag}"}),
            ("merge_contact_tags", {"source_id": "{tag}", "target_id": "{mine}"}),
            ("merge_contact_tags", {"source_id": "{mine}", "target_id": "{tag}"}),
        ],
    )
    async def test_their_tag_answers_as_a_missing_one_and_changes_nothing(
        self,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
        owned_state: OwnedState,
        tool: str,
        arguments: dict[str, str],
    ) -> None:
        theirs = owned_state.contact.tag_id
        mine = owned_state.contact.own_tag_id

        async def call(tag_id: int) -> dict[str, Any]:
            filled = {
                name: value.format(tag=tag_id, mine=mine)
                for name, value in arguments.items()
            }
            return await _call(authenticated_lifespan_client, tool, filled)

        before = await snapshot(async_connection, MCP_UNCHANGED_ROWS)
        foreign = await call(theirs)
        after_foreign = await snapshot(async_connection, MCP_UNCHANGED_ROWS)
        missing = await call(MISSING_TAG_ID)

        assert _is_error(foreign), f"{tool} acted on another user's tag: {foreign}"
        assert _masked(foreign, theirs, MISSING_TAG_ID) == _masked(
            missing, theirs, MISSING_TAG_ID
        )
        assert TAG_NAME not in repr(foreign)
        assert after_foreign == before

    async def test_a_tag_name_they_hold_gives_your_contact_your_own_tag(
        self,
        authenticated_lifespan_client: Callable[..., Any],
        async_connection: AsyncConnection,
        owned_state: OwnedState,
    ) -> None:
        own_contact_id = owned_state.contact.own_contact_id

        payload = await _call(
            authenticated_lifespan_client,
            "update_contact",
            {"request": {"contact_id": own_contact_id, "tags": [TAG_NAME]}},
        )

        assert not _is_error(payload), payload
        held = await async_connection.execute(
            text(
                "SELECT t.id, t.name, t.user_id FROM contact_tags ct "
                "JOIN tags t ON t.id = ct.tag_id WHERE ct.contact_id = :id"
            ),
            {"id": own_contact_id},
        )
        # The tag set is replaced by the named tag: a new one of the caller's,
        # not the foreign tag of that name (nor the contact's previous tag).
        assert [
            (row.name, row.user_id, row.id == owned_state.contact.tag_id)
            for row in held
        ] == [(TAG_NAME, TEST_USER_ID, False)]
