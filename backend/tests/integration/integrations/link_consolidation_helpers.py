"""Shared helpers for the integration-link consolidation integration tests.

Used by both the Phase 3 read tests and the Phase 4 write tests so the
``ContactService`` wiring lives in one place.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import (
    SqlContactEventPublisher,
    SqlContactFieldHistoryRepository,
    SqlContactRepository,
    SqlTagRepository,
)
from app.core.contacts.services import ContactService


def build_contact_service(conn: AsyncConnection) -> ContactService:
    """Build a real ContactService bound to the test connection."""
    from app.core.contacts.services import (
        AddressValidationService,
        ContactHistoryService,
        ContactValidationService,
        TagHierarchyService,
        TagService,
    )

    contact_repo = SqlContactRepository(conn)
    tag_repo = SqlTagRepository(conn)
    history_repo = SqlContactFieldHistoryRepository(conn)
    event_publisher = SqlContactEventPublisher(conn)
    tag_hierarchy_service = TagHierarchyService(tag_repo)

    return ContactService(
        contact_repo=contact_repo,
        tag_repo=tag_repo,
        history_repo=history_repo,
        event_publisher=event_publisher,
        address_validation_service=AddressValidationService(),
        contact_validation_service=ContactValidationService(contact_repo),
        history_service=ContactHistoryService(history_repo),
        tag_hierarchy_service=tag_hierarchy_service,
        tag_service=TagService(
            tag_repo=tag_repo,
            tag_hierarchy_service=tag_hierarchy_service,
            event_publisher=event_publisher,
        ),
    )
