"""Shared wiring for contact-service integration tests.

A ContactService assembled over the real repositories, and an event publisher
that keeps what it is given so a test can assert on the payload rather than on
the rows a projection eventually writes.
"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_field_history_repository import (
    SqlContactFieldHistoryRepository,
)
from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.contacts.adapters.sql.tag_repository import SqlTagRepository
from app.core.contacts.models.repositories import (
    ContactEventPublisher,
    DomainEventProtocol,
)
from app.core.contacts.services.address_validation_service import (
    AddressValidationService,
)
from app.core.contacts.services.contact_history_service import ContactHistoryService
from app.core.contacts.services.contact_service import ContactService
from app.core.contacts.services.contact_validation_service import (
    ContactValidationService,
)
from app.core.contacts.services.tag_hierarchy_service import TagHierarchyService


class RecordingEventPublisher(ContactEventPublisher):
    """Captures published events so a test can assert on the payload."""

    def __init__(self) -> None:
        self.events: list[DomainEventProtocol] = []

    async def publish(self, event: DomainEventProtocol) -> None:
        self.events.append(event)

    async def publish_batch(self, events: Sequence[DomainEventProtocol]) -> None:
        self.events.extend(events)

    def of_type(self, event_type: str) -> list[DomainEventProtocol]:
        """Every captured event of one type, in publication order."""
        return [e for e in self.events if e.event_type == event_type]

    def clear(self) -> None:
        """Forget everything so far, to assert on one save in isolation."""
        self.events.clear()


def build_contact_service(
    connection: AsyncConnection, event_publisher: ContactEventPublisher
) -> ContactService:
    """Assemble a ContactService over the real repositories."""
    contact_repo = SqlContactRepository(connection=connection)
    tag_repo = SqlTagRepository(connection=connection)
    history_repo = SqlContactFieldHistoryRepository(connection=connection)

    return ContactService(
        contact_repo=contact_repo,
        tag_repo=tag_repo,
        history_repo=history_repo,
        event_publisher=event_publisher,
        address_validation_service=AddressValidationService(),
        contact_validation_service=ContactValidationService(contact_repo),
        history_service=ContactHistoryService(history_repo),
        tag_hierarchy_service=TagHierarchyService(tag_repo),
    )
