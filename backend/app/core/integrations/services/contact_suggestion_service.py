"""Contact suggestions for recurring participants who are not yet contacts.

Inbound sync records, per journal, the participant emails it could not resolve
to a contact. An email recorded on enough of a user's journals is suggested as
a contact; the user can make it one -- as a new contact or on an existing
one -- or ignore it for good.
"""

from dataclasses import dataclass
from typing import assert_never

import structlog
from core_shared.models.contacts.entities import Contact, ContactMethod, MethodType
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.contacts.value_objects import Email
from core_shared.models.history import Provenance
from core_shared.models.journals.journal_contact_relationship import (
    JournalContactRelationship,
)
from core_shared.models.participant_email import (
    MAX_PARTICIPANT_EMAIL_LENGTH,
    normalise_participant_email,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
    DuplicateEmailError,
)
from app.core.contacts.services.contact_service import ContactService
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


def canonical_email(email: str) -> str:
    """``email`` in the form participant emails are recorded and ignored in.

    Raises:
        ContactValidationError: If it is not shaped like an email address, so
            REST and MCP callers alike cannot store junk entries.
    """
    canonical = normalise_participant_email(email)
    if len(canonical) > MAX_PARTICIPANT_EMAIL_LENGTH:
        raise ContactValidationError("email", "must be an email address")
    try:
        # The same value object a ContactMethod validates with, so an address
        # accepted here cannot be refused when it reaches the contact.
        Email(canonical)
    except ValueError as error:
        raise ContactValidationError("email", "must be an email address") from error
    return canonical


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
            ContactValidationError: If ``email`` is not an email address.
        """
        email = canonical_email(email)
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
    ) -> IgnoredContactSuggestion:
        """Never suggest ``email`` to the user again, until it is unignored.

        Returns the stored entry, which keeps the provenance and creation time
        of the first ignore.

        Raises:
            ContactValidationError: If ``email`` is not an email address.
        """
        return await self.ignore_repo.ignore(
            user_id, canonical_email(email), provenance
        )

    @transactional
    async def unignore(
        self, user_id: str, email: str, transaction: AsyncConnection
    ) -> bool:
        """Let ``email`` be suggested again; whether it was ignored.

        Not validated, so an entry stored before validation existed can
        still be removed.
        """
        return await self.ignore_repo.unignore(
            user_id, normalise_participant_email(email)
        )

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
                return await self._add_email_to_contact(
                    contact_id, email, transaction, changed_by, provenance
                )
            case _:
                assert_never(target)

    async def _add_email_to_contact(
        self,
        contact_id: int,
        email: str,
        transaction: AsyncConnection,
        changed_by: str,
        provenance: Provenance,
    ) -> Contact:
        """Give the contact ``email`` unless it already holds it.

        Adds just the method, under the contact's lock, rather than saving the
        whole contact: a snapshot saved back would undo any edit made to the
        contact since it was read. The email becomes primary only when the
        contact has none.
        """
        stored = await self.contact_service.get_contact_by_id(contact_id)
        if stored is None:
            raise ContactNotFoundError(contact_id)
        emails = [m for m in stored.methods or [] if m.method_type == MethodType.EMAIL]
        if self._holds_email(stored, email):
            return stored
        try:
            await self.contact_service.add_contact_method(
                contact_id,
                ContactMethod(
                    method_type=MethodType.EMAIL,
                    value=email,
                    contact_id=contact_id,
                    is_primary=not emails,
                ),
                transaction,
                changed_by=changed_by,
                source=provenance,
            )
        except DuplicateEmailError:
            # The read above is not under the contact's lock, so a concurrent
            # accept of the same suggestion can add the email first. That is
            # the outcome this one wanted, as long as it landed on this
            # contact; on any other it is a genuine conflict.
            settled = await self.contact_service.get_contact_by_id(contact_id)
            if settled is None or not self._holds_email(settled, email):
                raise
            return settled
        updated = await self.contact_service.get_contact_by_id(contact_id)
        if updated is None:
            raise ContactNotFoundError(contact_id)
        return updated

    @staticmethod
    def _holds_email(contact: Contact, email: str) -> bool:
        """Whether ``contact`` already has ``email``, in any spelling."""
        return any(
            m.method_type == MethodType.EMAIL
            and normalise_participant_email(m.value) == email
            for m in contact.methods or []
        )
