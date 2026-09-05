"""
Contact domain providers for Dishka dependency injection.

Provides all contact-related services, repositories, and dependencies.
"""

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import (
    SqlContactEventPublisher,
    SqlContactFieldHistoryRepository,
    SqlContactImportanceRepository,
    SqlContactRelationshipRepository,
    SqlContactRepository,
    SqlContactSummaryRepository,
    SqlCustomDateTypeRepository,
    SqlTagRepository,
)
from app.core.contacts.models.repositories import (
    ContactEventPublisher,
    ContactFieldHistoryRepository,
    ContactImportanceRepository,
    ContactRelationshipRepository,
    ContactRepository,
    ContactSummaryRepository,
    CustomDateTypeRepository,
    TagRepository,
)
from app.core.contacts.services import (
    AddressValidationService,
    ContactHistoryService,
    ContactMergeService,
    ContactRelationshipService,
    ContactService,
    ContactSummaryService,
    ContactValidationService,
    CustomDateTypeService,
    TagHierarchyService,
    TagService,
)
from app.core.history.models import FieldHistoryRepository
from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.journal.models.repositories import JournalContactRelationshipRepository
from app.core.tasks.adapters.sql.task_contact_repository import (
    SqlTaskContactRepository,
)
from app.core.tasks.models.repositories import TaskContactRepository
from app.core.tasks.services.task_contact_merge_service import (
    TaskContactMergeService,
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

    @provide(provides=ContactImportanceRepository)
    def get_contact_importance_repository(
        self, connection: AsyncConnection
    ) -> SqlContactImportanceRepository:
        """Provide the shared contact-importance read.

        Registered here rather than left to each caller to construct, because
        the read exists to be shared: the search indexer builds it inline while
        processing an outbox event, and the home dashboard resolves it through
        this container to rank upcoming important dates.
        """
        return SqlContactImportanceRepository(connection)

    @provide(provides=CustomDateTypeRepository, scope=Scope.REQUEST)
    def custom_date_type_repository(
        self, connection: AsyncConnection
    ) -> SqlCustomDateTypeRepository:
        """Provide custom date type repository."""
        return SqlCustomDateTypeRepository(connection=connection)

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

    @provide(provides=ContactSummaryRepository)
    def get_contact_summary_repository(
        self, connection: AsyncConnection
    ) -> SqlContactSummaryRepository:
        return SqlContactSummaryRepository(connection)

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
    def get_custom_date_type_service(
        self, custom_date_type_repo: CustomDateTypeRepository
    ) -> CustomDateTypeService:
        return CustomDateTypeService(custom_date_type_repo)

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
        event_publisher: ContactEventPublisher,
    ) -> ContactRelationshipService:
        return ContactRelationshipService(
            contact_repo, relationship_repo, event_publisher
        )

    @provide(provides=TaskContactRepository)
    def get_task_contact_repository(
        self, connection: AsyncConnection
    ) -> SqlTaskContactRepository:
        """The port a contact merge moves task links through.

        Provided here rather than by ``TaskProvider``, for the reason
        ``JournalProvider`` builds the anchor repository it needs: Dishka
        validates the whole graph at construction, so a ``ContactProvider`` that
        depended on something ``TaskProvider`` supplies would force every
        container registering one to register the other. It needs only the
        request connection this provider already has.
        """
        return SqlTaskContactRepository(connection)

    @provide
    def get_task_contact_merge_service(
        self,
        task_contact_repo: TaskContactRepository,
        event_publisher: OutboxEventPublisher,
    ) -> TaskContactMergeService:
        """Provide the tasks domain's half of a contact merge."""
        return TaskContactMergeService(
            task_contact_repo=task_contact_repo,
            event_publisher=event_publisher,
        )

    @provide
    def get_contact_merge_service(
        self,
        contact_repo: ContactRepository,
        relationship_repo: ContactRelationshipRepository,
        journal_relationship_repo: JournalContactRelationshipRepository,
        event_publisher: ContactEventPublisher,
        history_repo: FieldHistoryRepository,
        sync_metadata_repo: SyncMetadataRepository,
        task_merge_service: TaskContactMergeService,
    ) -> ContactMergeService:
        """Provide a ContactMergeService instance.

        A merge moves task links onto the survivor before deleting the absorbed
        contact, whose ``ON DELETE CASCADE`` would otherwise destroy them — and
        the tasks it moves record it in their own history. Both are the tasks
        domain's service to perform, so the contacts domain holds that rather
        than the link repository itself.
        """
        return ContactMergeService(
            contact_repo=contact_repo,
            relationship_repo=relationship_repo,
            journal_relationship_repo=journal_relationship_repo,
            event_publisher=event_publisher,
            history_repo=history_repo,
            sync_metadata_repo=sync_metadata_repo,
            task_merge_service=task_merge_service,
        )

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
        tag_service: TagService,
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
            tag_service=tag_service,
        )

    @provide
    def get_contact_summary_service(
        self,
        summary_repo: ContactSummaryRepository,
        event_publisher: ContactEventPublisher,
    ) -> ContactSummaryService:
        return ContactSummaryService(
            summary_repo=summary_repo,
            event_publisher=event_publisher,
        )

    # Search service (stateless, can be singleton)
    @provide(scope=Scope.APP)
    def get_search_service(self) -> SearchService:
        return SearchService()
