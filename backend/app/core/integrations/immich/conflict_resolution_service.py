"""Resolving Immich person conflicts.

When Immich sync cannot tell which contact an Immich person is, it records a
conflict in ``pending_entity_mappings``. The user resolves it by linking the
person to one of their contacts, or by creating a contact from the person's
name. Either way the conflict is marked resolved and the canonical
``sync_metadata`` link is written, so the next sync finds the contact.

REST and MCP both resolve conflicts through this one service, which owns the
unit of work: the contact, the resolution and the link commit together or not
at all.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from core_shared.contact_name_matcher import ContactNameMatcher
from core_shared.exceptions import DomainError
from core_shared.models.contacts.entities import Contact
from core_shared.models.contacts.value_objects import Provenance
from core_shared.repositories.pending_entity_mapping_repository import (
    PendingEntityMappingRepository,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.contacts.models.repositories import ContactRepository
from app.core.contacts.services.contact_service import ContactService
from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.infrastructure.unit_of_work import transactional

IMMICH_SOURCE = "immich"
UNNAMED_FIRST_NAME = "Unnamed"


class ConflictResolutionAction(StrEnum):
    """How to resolve a conflict."""

    LINK = "link"
    CREATE = "create"


class ImmichConflictResolutionError(DomainError):
    """Base error for resolving an Immich conflict."""


class ImmichConflictNotFoundError(ImmichConflictResolutionError):
    """The conflict does not exist, is another user's, or is already resolved."""

    def __init__(self, conflict_id: int) -> None:
        super().__init__(f"Conflict {conflict_id} not found or already resolved", 404)
        self.conflict_id = conflict_id


class ImmichConflictContactRequiredError(ImmichConflictResolutionError):
    """A link was requested without naming the contact to link to."""

    def __init__(self) -> None:
        super().__init__("contact_id is required when action is 'link'", 400)


@dataclass(frozen=True)
class ResolvedImmichConflict:
    """A conflict after resolution, and the contact it now points to."""

    conflict_id: int
    contact_id: int
    external_entity_id: str
    external_entity_name: str | None
    candidate_contact_ids: list[int]
    status: str
    created_at: datetime | None


class ImmichConflictResolutionService:
    """Resolves a user's Immich person conflicts."""

    def __init__(
        self,
        *,
        conflict_repo: PendingEntityMappingRepository,
        contact_repo: ContactRepository,
        sync_metadata_repo: SyncMetadataRepository,
        contact_service: ContactService,
    ) -> None:
        self.conflict_repo = conflict_repo
        self.contact_repo = contact_repo
        self.sync_metadata_repo = sync_metadata_repo
        self.contact_service = contact_service

    @transactional
    async def resolve(
        self,
        conflict_id: int,
        action: ConflictResolutionAction,
        contact_id: int | None,
        *,
        user_id: str,
        provenance: Provenance,
        transaction: AsyncConnection,
    ) -> ResolvedImmichConflict:
        """Link the conflict's Immich person to a contact of ``user_id``'s.

        ``CREATE`` makes that contact from the person's name; ``LINK`` uses
        ``contact_id``, which must be the user's own.

        Raises:
            ImmichConflictNotFoundError: If the user has no unresolved Immich
                conflict with this id.
            ImmichConflictContactRequiredError: If linking without a contact.
            ContactNotFoundError: If linking to a contact the user does not own.
        """
        conflict = await self.conflict_repo.get_unresolved_by_id(
            conflict_id=conflict_id,
            user_id=user_id,
            integration_source=IMMICH_SOURCE,
        )
        if conflict is None:
            raise ImmichConflictNotFoundError(conflict_id)

        match action:
            case ConflictResolutionAction.CREATE:
                contact_id = await self._create_contact(
                    conflict["external_entity_name"],
                    user_id=user_id,
                    provenance=provenance,
                    transaction=transaction,
                )
            case ConflictResolutionAction.LINK:
                if contact_id is None:
                    raise ImmichConflictContactRequiredError()
                if not await self.contact_repo.contact_exists(
                    contact_id, user_id=user_id
                ):
                    raise ContactNotFoundError(contact_id)

        resolved = await self.conflict_repo.resolve(
            conflict_id=conflict_id, resolved_contact_id=contact_id
        )
        if resolved is None:
            raise ImmichConflictNotFoundError(conflict_id)

        await self.sync_metadata_repo.upsert_contact_link(
            contact_id=contact_id,
            user_id=user_id,
            external_system=IMMICH_SOURCE,
            external_entity_type="person",
            external_entity_id=conflict["external_entity_id"],
        )

        return ResolvedImmichConflict(
            conflict_id=resolved["id"],
            contact_id=contact_id,
            external_entity_id=resolved["external_entity_id"],
            external_entity_name=resolved["external_entity_name"],
            candidate_contact_ids=resolved["candidate_contact_ids"] or [],
            status=resolved["status"],
            created_at=resolved["created_at"],
        )

    async def _create_contact(
        self,
        name: str | None,
        *,
        user_id: str,
        provenance: Provenance,
        transaction: AsyncConnection,
    ) -> int:
        first_name, last_name = ContactNameMatcher.parse_name(name or "")
        saved = await self.contact_service.create_contact(
            contact=Contact(
                first_name=first_name or UNNAMED_FIRST_NAME,
                last_name=last_name or "",
                user_id=user_id,
            ),
            transaction=transaction,
            changed_by=provenance.value,
            source=provenance,
        )
        if saved.id is None:
            raise ImmichConflictResolutionError("Contact ID is required after save")
        return saved.id
