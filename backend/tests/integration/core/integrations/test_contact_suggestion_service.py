"""Integration tests for ContactSuggestionService.

Accepting a suggestion makes the email a contact's -- a new contact or an
existing one -- and links that contact to every journal the email was recorded
on, with the status and role the integration reported.
"""

import pytest
from core_shared.models.contacts.entities import MethodType
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.history import Provenance
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.integrations.adapters.sql.contact_suggestion_ignore_repository import (
    SqlContactSuggestionIgnoreRepository,
)
from app.core.integrations.adapters.sql.unmatched_participant_email_repository import (
    SqlUnmatchedParticipantEmailRepository,
)
from app.core.integrations.services.contact_suggestion_service import (
    ContactSuggestionService,
    ExistingContactTarget,
    NewContactTarget,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.services.journal_contact_service import JournalContactService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.contacts.contact_service_harness import (
    RecordingEventPublisher,
    build_contact_service,
)
from tests.integration.core.integrations.contact_suggestion_seeding import (
    OTHER_USER_ID,
    USER_ID,
    create_contact,
    create_journal,
    journal_relationships,
    record_unmatched,
    seed_participant,
    unmatched_journal_ids,
)


@pytest.fixture
def contact_events() -> RecordingEventPublisher:
    return RecordingEventPublisher()


@pytest.fixture
def service(
    async_connection: AsyncConnection, contact_events: RecordingEventPublisher
) -> ContactSuggestionService:
    return ContactSuggestionService(
        unmatched_repo=SqlUnmatchedParticipantEmailRepository(async_connection),
        ignore_repo=SqlContactSuggestionIgnoreRepository(async_connection),
        contact_service=build_contact_service(async_connection, contact_events),
        journal_contact_service=JournalContactService(
            SqlJournalContactRelationshipRepository(async_connection),
            OutboxEventPublisher(async_connection),
        ),
    )


async def _emails_of(connection: AsyncConnection, contact_id: int) -> list[str]:
    result = await connection.execute(
        text(
            "SELECT value FROM contact_methods"
            " WHERE contact_id = :id AND method_type = 'email' ORDER BY id"
        ),
        {"id": contact_id},
    )
    return [row.value for row in result.fetchall()]


@pytest.mark.integration
class TestListSuggestions:
    async def test_uses_the_five_event_threshold(
        self, service: ContactSuggestionService, async_connection: AsyncConnection
    ) -> None:
        await seed_participant(async_connection, "five@x.com", 5)
        await seed_participant(async_connection, "four@x.com", 4)

        suggestions = await service.list_suggestions(USER_ID)

        assert [s.email for s in suggestions] == ["five@x.com"]


@pytest.mark.integration
class TestAcceptAsNewContact:
    async def test_creates_contact_and_links_every_journal(
        self, service: ContactSuggestionService, async_connection: AsyncConnection
    ) -> None:
        journal_ids = await seed_participant(
            async_connection, "jane@x.com", 5, status="ATTENDING"
        )

        accepted = await service.accept(
            USER_ID,
            " Jane@X.com ",
            NewContactTarget(first_name="Jane", last_name="Smith"),
            transaction=async_connection,
            provenance=Provenance.UI,
        )

        contact = accepted.contact
        assert accepted.linked_journal_count == 5
        assert contact.id is not None
        assert (contact.first_name, contact.last_name) == ("Jane", "Smith")
        assert await _emails_of(async_connection, contact.id) == ["jane@x.com"]
        assert await journal_relationships(
            async_connection, contact.id
        ) == dict.fromkeys(journal_ids, ("INVITEE", "ATTENDING", None))
        assert await unmatched_journal_ids(async_connection, "jane@x.com") == set()

    async def test_leaves_other_users_journals_alone(
        self, service: ContactSuggestionService, async_connection: AsyncConnection
    ) -> None:
        theirs = await create_journal(async_connection, user_id=OTHER_USER_ID)
        await record_unmatched(async_connection, theirs, "jane@x.com")

        accepted = await service.accept(
            USER_ID,
            "jane@x.com",
            NewContactTarget(first_name="Jane"),
            transaction=async_connection,
            provenance=Provenance.UI,
        )

        contact = accepted.contact
        assert accepted.linked_journal_count == 0
        assert contact.id is not None
        assert await journal_relationships(async_connection, contact.id) == {}
        assert await unmatched_journal_ids(async_connection, "jane@x.com") == {theirs}

    async def test_accepting_clears_an_ignore(
        self, service: ContactSuggestionService, async_connection: AsyncConnection
    ) -> None:
        await service.ignore(
            USER_ID,
            "jane@x.com",
            transaction=async_connection,
            provenance=Provenance.UI,
        )

        await service.accept(
            USER_ID,
            "jane@x.com",
            NewContactTarget(first_name="Jane"),
            transaction=async_connection,
            provenance=Provenance.UI,
        )

        assert await service.list_ignored(USER_ID) == []


@pytest.mark.integration
class TestAcceptIntoExistingContact:
    async def test_adds_email_without_changing_the_primary_one(
        self, service: ContactSuggestionService, async_connection: AsyncConnection
    ) -> None:
        contact_id = await create_contact(
            async_connection, first_name="Jane", email="jane@home.com"
        )
        journal_ids = await seed_participant(async_connection, "jane@work.com", 5)

        contact = (
            await service.accept(
                USER_ID,
                "jane@work.com",
                ExistingContactTarget(contact_id=contact_id),
                transaction=async_connection,
                provenance=Provenance.UI,
            )
        ).contact

        assert contact.id == contact_id
        primary = [
            m.value
            for m in contact.methods or []
            if m.method_type == MethodType.EMAIL and m.is_primary
        ]
        assert primary == ["jane@home.com"]
        assert await _emails_of(async_connection, contact_id) == [
            "jane@home.com",
            "jane@work.com",
        ]
        assert set(await journal_relationships(async_connection, contact_id)) == set(
            journal_ids
        )

    async def test_adds_only_the_email_and_saves_nothing_else(
        self,
        service: ContactSuggestionService,
        async_connection: AsyncConnection,
        contact_events: RecordingEventPublisher,
    ) -> None:
        """The email is added as a method, not by saving a copy of the contact
        read earlier, which would undo edits made since that read."""
        contact_id = await create_contact(async_connection, first_name="Jane")

        await service.accept(
            USER_ID,
            "jane@x.com",
            ExistingContactTarget(contact_id=contact_id),
            transaction=async_connection,
            provenance=Provenance.UI,
        )

        assert [e.event_type for e in contact_events.events] == ["ContactMethodAdded"]
        assert await _emails_of(async_connection, contact_id) == ["jane@x.com"]

    async def test_email_already_held_is_not_duplicated(
        self, service: ContactSuggestionService, async_connection: AsyncConnection
    ) -> None:
        contact_id = await create_contact(
            async_connection, first_name="Jane", email="Jane@Work.com"
        )

        await service.accept(
            USER_ID,
            "jane@work.com",
            ExistingContactTarget(contact_id=contact_id),
            transaction=async_connection,
            provenance=Provenance.UI,
        )

        assert await _emails_of(async_connection, contact_id) == ["Jane@Work.com"]

    async def test_journal_already_linked_to_the_contact_is_kept(
        self, service: ContactSuggestionService, async_connection: AsyncConnection
    ) -> None:
        contact_id = await create_contact(async_connection, first_name="Jane")
        [journal_id] = await seed_participant(async_connection, "jane@x.com", 1)
        await async_connection.execute(
            text(
                """
                INSERT INTO journal_contact_relationships
                    (journal_id, contact_id, relationship_type, status)
                VALUES (:journal_id, :contact_id, 'INVITEE', 'DECLINED')
                """
            ),
            {"journal_id": journal_id, "contact_id": contact_id},
        )

        accepted = await service.accept(
            USER_ID,
            "jane@x.com",
            ExistingContactTarget(contact_id=contact_id),
            transaction=async_connection,
            provenance=Provenance.UI,
        )

        assert accepted.linked_journal_count == 0
        assert await journal_relationships(async_connection, contact_id) == {
            journal_id: ("INVITEE", "DECLINED", None)
        }
        assert await unmatched_journal_ids(async_connection, "jane@x.com") == set()

    async def test_unknown_contact_raises_and_keeps_the_suggestion(
        self, service: ContactSuggestionService, async_connection: AsyncConnection
    ) -> None:
        journal_ids = await seed_participant(async_connection, "jane@x.com", 5)

        with pytest.raises(ContactNotFoundError):
            await service.accept(
                USER_ID,
                "jane@x.com",
                ExistingContactTarget(contact_id=999_999),
                transaction=async_connection,
                provenance=Provenance.UI,
            )

        assert await unmatched_journal_ids(async_connection, "jane@x.com") == set(
            journal_ids
        )


@pytest.mark.integration
class TestIgnore:
    async def test_ignoring_again_reports_the_stored_entry(
        self, service: ContactSuggestionService, async_connection: AsyncConnection
    ) -> None:
        """A UI ignore of an address already ignored from MCP reports the
        provenance that is stored, not the one it asked for."""
        first = await service.ignore(
            USER_ID,
            "noisy@x.com",
            transaction=async_connection,
            provenance=Provenance.MCP,
        )
        again = await service.ignore(
            USER_ID,
            "noisy@x.com",
            transaction=async_connection,
            provenance=Provenance.UI,
        )

        assert (first.provenance, again.provenance) == (
            Provenance.MCP,
            Provenance.MCP,
        )

    async def test_ignored_email_leaves_suggestions_until_restored(
        self, service: ContactSuggestionService, async_connection: AsyncConnection
    ) -> None:
        await seed_participant(async_connection, "noisy@x.com", 5)

        await service.ignore(
            USER_ID,
            "Noisy@X.com",
            transaction=async_connection,
            provenance=Provenance.UI,
        )
        assert await service.list_suggestions(USER_ID) == []
        assert [i.email for i in await service.list_ignored(USER_ID)] == ["noisy@x.com"]

        assert await service.unignore(
            USER_ID, "noisy@x.com", transaction=async_connection
        )
        assert [s.email for s in await service.list_suggestions(USER_ID)] == [
            "noisy@x.com"
        ]


@pytest.mark.integration
class TestMalformedEmails:
    """Rejected exactly where a ``ContactMethod`` would reject them, so an
    address the service accepts can always reach a contact."""

    @pytest.mark.parametrize(
        "email",
        ["not-an-email", "@x.com", "a b@x.com", "a@b", "a@b@c.com"],
    )
    async def test_accept_and_ignore_reject_them(
        self,
        service: ContactSuggestionService,
        async_connection: AsyncConnection,
        email: str,
    ) -> None:
        with pytest.raises(ContactValidationError):
            await service.accept(
                USER_ID,
                email,
                NewContactTarget(first_name="Jane"),
                transaction=async_connection,
                provenance=Provenance.UI,
            )
        with pytest.raises(ContactValidationError):
            await service.ignore(
                USER_ID, email, transaction=async_connection, provenance=Provenance.MCP
            )

        assert await service.list_ignored(USER_ID) == []
