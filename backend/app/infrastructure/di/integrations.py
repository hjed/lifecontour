"""
Dependency injection provider for integration services.

Provides integration-related dependencies including task queue configuration,
database managers, and base integration services.
"""

from arq.connections import RedisSettings
from dishka import Provider, Scope, provide
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.services.contact_service import ContactService
from app.core.integrations.database import IntegrationDatabaseManager
from app.core.integrations.encryption import EncryptionService
from app.core.integrations.external_reference_service import ExternalReferenceService
from app.core.integrations.google_contacts.transformer import GoogleContactTransformer
from app.core.integrations.health_service import IntegrationHealthService
from app.core.integrations.outbox_event_processor import OutboxEventProcessor
from app.core.integrations.task_queue import get_redis_pool, get_redis_settings
from app.core.integrations.task_queue_service import TaskQueueService
from app.infrastructure.config import Settings


class IntegrationProvider(Provider):
    """Provider for integration-related dependencies."""

    scope = Scope.APP

    @provide
    async def provide_redis_pool(self, settings: Settings) -> Redis:
        """
        Provide Redis connection pool for ARQ tasks.

        Args:
            settings: Application settings

        Returns:
            Redis: Redis connection pool
        """
        return await get_redis_pool(settings)

    @provide
    def provide_integration_database_manager(
        self, settings: Settings
    ) -> IntegrationDatabaseManager:
        """
        Provide database manager for integration workers.

        Args:
            settings: Application settings

        Returns:
            IntegrationDatabaseManager: Database manager instance
        """
        return IntegrationDatabaseManager(settings)

    # Integration processing dependencies
    @provide(scope=Scope.APP)
    def provide_encryption_service(self, settings: Settings) -> EncryptionService:
        """
        Provide encryption service as singleton.

        Args:
            settings: Application settings

        Returns:
            EncryptionService: Encryption service instance
        """
        return EncryptionService(settings)

    @provide(scope=Scope.APP)
    def provide_google_contact_transformer(self) -> GoogleContactTransformer:
        """
        Provide Google Contact transformer as singleton.

        Returns:
            GoogleContactTransformer: Transformer instance
        """
        return GoogleContactTransformer()

    @provide(scope=Scope.REQUEST)
    def provide_external_reference_service(
        self, connection: AsyncConnection
    ) -> ExternalReferenceService:
        """
        Provide external reference service for request scope.

        Args:
            connection: Database connection

        Returns:
            ExternalReferenceService: External reference service instance
        """
        return ExternalReferenceService(connection)

    @provide(scope=Scope.REQUEST)
    def provide_outbox_event_processor(
        self, contact_service: ContactService, connection: AsyncConnection
    ) -> OutboxEventProcessor:
        """
        Provide outbox event processor for request scope.

        Args:
            contact_service: Contact service for creating/updating contacts
            connection: Database connection

        Returns:
            OutboxEventProcessor: Outbox event processor instance
        """
        return OutboxEventProcessor(
            contact_service=contact_service, connection=connection
        )

    @provide(scope=Scope.REQUEST)
    async def provide_task_queue_service(
        self,
        redis_pool: Redis,
        settings: Settings,
        db_manager: IntegrationDatabaseManager,
    ) -> TaskQueueService:
        """
        Provide task queue service for request scope.

        Args:
            redis_pool: Redis connection pool
            settings: Application settings
            db_manager: Database manager for persisting sync jobs

        Returns:
            TaskQueueService: Task queue service instance
        """
        redis_settings = get_redis_settings(settings)
        return TaskQueueService(
            redis_pool=redis_pool,
            redis_settings=redis_settings,
            settings=settings,
            db_manager=db_manager,
        )

    @provide(scope=Scope.REQUEST)
    def provide_health_service(
        self, redis_pool: Redis, db_manager: IntegrationDatabaseManager
    ) -> IntegrationHealthService:
        """
        Provide integration health service for request scope.

        Args:
            redis_pool: Redis connection pool
            db_manager: Database manager for job statistics

        Returns:
            IntegrationHealthService: Health service instance
        """
        return IntegrationHealthService(redis_pool=redis_pool, db_manager=db_manager)

    @provide
    def provide_redis_settings(self, settings: Settings) -> RedisSettings:
        """
        Provide Redis settings for ARQ configuration.

        Args:
            settings: Application settings

        Returns:
            RedisSettings: Redis settings for ARQ
        """
        return get_redis_settings(settings)
