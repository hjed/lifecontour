"""Contact suggestions for recurring participants who are not yet contacts.

Inbound sync records, per journal, the participant emails it could not resolve
to a contact. An email recorded on enough of a user's journals is suggested as
a contact; the user can make it one -- as a new contact or on an existing
one -- or ignore it for good.
"""

from dataclasses import dataclass, replace
from typing import assert_never

import structlog
from core_shared.models.contacts.entities import Contact, ContactMethod, MethodType
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.history import Provenance
from core_shared.models.journals.journal_contact_relationship import (
    JournalContactRelationship,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.contacts.services.contact_service import ContactService
from app.core.contacts.services.contact_subentity_sync import SubResourceMerge
from app.core.integrations.adapters.sql.contact_suggestion_ignore_repository import (
    SqlContactSuggestionIgnoreRepository,
)
from app.core.integrations.adapters.sql.unmatched_participant_email_repository import (
    SqlUnmatchedParticipantEmailRepository,
)
from app.core.integrations.models.unmatched_participant import (
    ContactSuggestion,
    IgnoredContactSuggestion,
)
from app.core.journal.services.journal_contact_service import JournalContactService
from app.infrastructure.unit_of_work import savepoint, transactional

logger = structlog.get_logger()

CONTACT_SUGGESTION_MIN_EVENTS = 5
"""How many of a user's journals an email must be on to be suggested."""


@dataclass(frozen=True)
class NewContactTarget:
    """Accept a suggestion by creating a contact with these names."""

    first_name: str
    last_name: str | None = None


@dataclass(frozen=True)
class ExistingContactTarget:
    """Accept a suggestion by adding the email to this contact."""

    contact_id: int


AcceptTarget = NewContactTarget | ExistingContactTarget


@dataclass(frozen=True)
class AcceptedContactSuggestion:
    """The contact now holding the email, and how many journals were linked."""

    contact: Contact
    linked_journal_count: int


def normalise_email(email: str) -> str:
    """The form participant emails are recorded and ignored in."""
    return email.strip().lower()


class ContactSuggestionService:
    """Lists, accepts and ignores contact suggestions for a user."""

    def __init__(
        self,
        unmatched_repo: SqlUnmatchedParticipantEmailRepository,
        ignore_repo: SqlContactSuggestionIgnoreRepository,
        contact_service: ContactService,
        journal_contact_service: JournalContactService,
    ) -> None:
        self.unmatched_repo = unmatched_repo
        self.ignore_repo = ignore_repo
        self.contact_service = contact_service
        self.journal_contact_service = journal_contact_service

    async def list_suggestions(self, user_id: str) -> list[ContactSuggestion]:
        """Emails on enough of the user's journals, most-seen first."""
        return await self.unmatched_repo.list_candidates(
            user_id, CONTACT_SUGGESTION_MIN_EVENTS
        )

    async def list_ignored(self, user_id: str) -> list[IgnoredContactSuggestion]:
        """The emails the user has asked never to have suggested."""
        return await self.ignore_repo.list_ignored(user_id)

    @transactional
    async def accept(
        self,
        user_id: str,
        email: str,
        target: AcceptTarget,
        transaction: AsyncConnection,
        provenance: Provenance,
    ) -> AcceptedContactSuggestion:
        """Make ``email`` a contact's and link it to the journals it was seen on.

        Works whether or not the email is currently suggested: a suggestion can
        change between being listed and being accepted, and there is simply
        nothing to link when the email was never recorded.

        Raises:
            ContactNotFoundError: If ``target`` names a contact that does not
                exist. Nothing is written.
        """
        email = normalise_email(email)
        contact = await self._contact_holding(email, target, transaction, provenance)
        if contact.id is None:
            raise ContactValidationError("id", "Contact ID is required after save")

        linked = 0
        for row in await self.unmatched_repo.list_for_email(user_id, email):
            try:
                async with savepoint(transaction):
                    await self.journal_contact_service.add_contact_to_journal(
                        JournalContactRelationship(
                            journal_id=row.journal_id,
                            contact_id=contact.id,
                            relationship_type=row.relationship_type,
                            status=row.status,
                            role=row.role,
                        ),
                        transaction=transaction,
                    )
                linked += 1
            except IntegrityError:
                # Already linked, perhaps with a status someone set by hand:
                # that link is the better record, so it is kept as it is.
                logger.info(
                    "Contact already linked to journal, keeping the link",
                    journal_id=row.journal_id,
                    contact_id=contact.id,
                )

        await self.unmatched_repo.delete_for_email(user_id, email)
        await self.ignore_repo.unignore(user_id, email)
        return AcceptedContactSuggestion(contact=contact, linked_journal_count=linked)

    @transactional
    async def ignore(
        self,
        user_id: str,
        email: str,
        transaction: AsyncConnection,
        provenance: Provenance,
    ) -> None:
        """Never suggest ``email`` to the user again, until it is unignored."""
        await self.ignore_repo.ignore(user_id, normalise_email(email), provenance)

    @transactional
    async def unignore(
        self, user_id: str, email: str, transaction: AsyncConnection
    ) -> bool:
        """Let ``email`` be suggested again; whether it was ignored."""
        return await self.ignore_repo.unignore(user_id, normalise_email(email))

    async def _contact_holding(
        self,
        email: str,
        target: AcceptTarget,
        transaction: AsyncConnection,
        provenance: Provenance,
    ) -> Contact:
        changed_by = provenance.value
        match target:
            case NewContactTarget(first_name=first_name, last_name=last_name):
                return await self.contact_service.create_contact(
                    Contact(
                        first_name=first_name,
                        last_name=last_name,
                        methods=[
                            ContactMethod(
                                method_type=MethodType.EMAIL,
                                value=email,
                                contact_id=0,
                                is_primary=True,
                            )
                        ],
                    ),
                    transaction,
                    changed_by=changed_by,
                    source=provenance,
                )
            case ExistingContactTarget(contact_id=contact_id):
                stored = await self.contact_service.get_contact_by_id(contact_id)
                if stored is None:
                    raise ContactNotFoundError(contact_id)
                # Every list left as None, so only the named email changes.
                return await self.contact_service.update_contact(
                    replace(
                        stored,
                        methods=None,
                        addresses=None,
                        notes=None,
                        tags=None,
                        relationships=None,
                        important_dates=None,
                        summary=None,
                    ),
                    transaction,
                    changed_by=changed_by,
                    source=provenance,
                    subresource_merge=SubResourceMerge(
                        added_methods=[(MethodType.EMAIL, email)]
                    ),
                )
            case _:
                assert_never(target)
