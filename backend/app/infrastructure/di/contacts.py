"""
Contact domain providers for Dishka dependency injection.

Provides all contact-related services, repositories, and dependencies.
"""

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import (
    SqlContactEventPublisher,
    SqlContactFieldHistoryRepository,
    SqlContactRelationshipRepository,
    SqlContactRepository,
    SQLCustomDateTypeRepository,
    SqlTagRepository,
)
from app.core.contacts.models.repositories import (
    ContactEventPublisher,
    ContactFieldHistoryRepository,
    ContactRelationshipRepository,
    ContactRepository,
    CustomDateTypeRepository,
    TagRepository,
)
from app.core.contacts.services import (
    AddressValidationService,
    ContactHistoryService,
    ContactRelationshipService,
    ContactService,
    ContactValidationService,
    TagHierarchyService,
    TagService,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.search.search_service import SearchService


class ContactProvider(Provider):
    """Provider for contact domain dependencies."""

    scope = Scope.REQUEST

    # Repository implementations
    @provide(provides=ContactRepository)
    def get_contact_repository(
        self, connection: AsyncConnection
    ) -> SqlContactRepository:
        return SqlContactRepository(connection)

    @provide(provides=TagRepository)
    def get_tag_repository(self, connection: AsyncConnection) -> SqlTagRepository:
        return SqlTagRepository(connection)

    @provide(provides=CustomDateTypeRepository)
    def get_custom_date_type_repository(
        self, connection: AsyncConnection
    ) -> SQLCustomDateTypeRepository:
        return SQLCustomDateTypeRepository(connection)

    @provide(provides=ContactFieldHistoryRepository)
    def get_contact_field_history_repository(
        self, connection: AsyncConnection
    ) -> SqlContactFieldHistoryRepository:
        return SqlContactFieldHistoryRepository(connection)

    @provide(provides=ContactEventPublisher)
    def get_contact_event_publisher(
        self,
        connection: AsyncConnection,
        outbox_pub: OutboxEventPublisher,
    ) -> ContactEventPublisher:
        from app.infrastructure.events.dual_contact_event_publisher import (
            DualContactEventPublisher,
        )

        return DualContactEventPublisher(
            SqlContactEventPublisher(connection), outbox_pub
        )

    @provide(provides=ContactRelationshipRepository)
    def get_contact_relationship_repository(
        self, connection: AsyncConnection
    ) -> SqlContactRelationshipRepository:
        return SqlContactRelationshipRepository(connection)

    # Domain services
    @provide
    def get_address_validation_service(self) -> AddressValidationService:
        return AddressValidationService()

    @provide
    def get_contact_validation_service(
        self, contact_repo: ContactRepository
    ) -> ContactValidationService:
        return ContactValidationService(contact_repo)

    @provide
    def get_contact_history_service(
        self, history_repo: ContactFieldHistoryRepository
    ) -> ContactHistoryService:
        return ContactHistoryService(history_repo)

    @provide
    def get_tag_hierarchy_service(self, tag_repo: TagRepository) -> TagHierarchyService:
        return TagHierarchyService(tag_repo)

    @provide
    def get_tag_service(
        self,
        tag_repo: TagRepository,
        tag_hierarchy_service: TagHierarchyService,
        event_publisher: ContactEventPublisher,
    ) -> TagService:
        from app.core.contacts.services.tag_service import TagService

        return TagService(
            tag_repo=tag_repo,
            tag_hierarchy_service=tag_hierarchy_service,
            event_publisher=event_publisher,
        )

    @provide
    def get_contact_relationship_service(
        self,
        contact_repo: ContactRepository,
        relationship_repo: ContactRelationshipRepository,
    ) -> ContactRelationshipService:
        return ContactRelationshipService(contact_repo, relationship_repo)

    # Main contact service
    @provide
    def get_contact_service(
        self,
        contact_repo: ContactRepository,
        tag_repo: TagRepository,
        history_repo: ContactFieldHistoryRepository,
        event_publisher: ContactEventPublisher,
        address_validation_service: AddressValidationService,
        contact_validation_service: ContactValidationService,
        history_service: ContactHistoryService,
        tag_hierarchy_service: TagHierarchyService,
    ) -> ContactService:
        return ContactService(
            contact_repo=contact_repo,
            tag_repo=tag_repo,
            history_repo=history_repo,
            event_publisher=event_publisher,
            address_validation_service=address_validation_service,
            contact_validation_service=contact_validation_service,
            history_service=history_service,
            tag_hierarchy_service=tag_hierarchy_service,
        )

    # Search service (stateless, can be singleton)
    @provide(scope=Scope.APP)
    def get_search_service(self) -> SearchService:
        return SearchService()
