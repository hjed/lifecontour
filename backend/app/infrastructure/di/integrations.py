"""
Dependency injection provider for integration services.

Provides integration-related dependencies including task queue configuration,
database managers, and base integration services.
"""

from arq.connections import RedisSettings
from dishka import Provider, Scope, provide
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.database import IntegrationDatabaseManager
from app.core.integrations.encryption import EncryptionService
from app.core.integrations.google_contacts.client_factory import (
    GoogleContactsClientFactory,
)
from app.core.integrations.google_contacts.contacts_service import GoogleContactsService
from app.core.integrations.google_contacts.service import GoogleAuthService
from app.core.integrations.google_contacts.transformer import GoogleContactTransformer
from app.core.integrations.task_queue import get_redis_pool, get_redis_settings
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

    # Google Contacts integration dependencies
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
    def provide_google_auth_service(
        self,
        connection: AsyncConnection,
        encryption_service: EncryptionService,
        settings: Settings
    ) -> GoogleAuthService:
        """
        Provide Google Auth service for request scope.

        Args:
            connection: Database connection
            encryption_service: Encryption service
            settings: Application settings

        Returns:
            GoogleAuthService: Auth service instance
        """
        return GoogleAuthService(
            connection=connection,
            encryption_service=encryption_service,
            google_client_id=settings.google_client_id,
            google_client_secret=settings.google_client_secret,
        )

    @provide(scope=Scope.REQUEST)
    def provide_google_contacts_client_factory(
        self, auth_service: GoogleAuthService, settings: Settings
    ) -> GoogleContactsClientFactory:
        """
        Provide Google Contacts client factory for request scope.

        Args:
            auth_service: Google authentication service
            settings: Application settings

        Returns:
            GoogleContactsClientFactory: Client factory instance
        """
        return GoogleContactsClientFactory(
            auth_service=auth_service,
            google_client_id=settings.google_client_id,
            google_client_secret=settings.google_client_secret,
        )

    @provide(scope=Scope.REQUEST)
    def provide_google_contacts_service(
        self,
        connection: AsyncConnection,
        client_factory: GoogleContactsClientFactory,
        transformer: GoogleContactTransformer,
    ) -> GoogleContactsService:
        """
        Provide Google Contacts service for request scope.

        Args:
            connection: Database connection
            client_factory: Google Contacts client factory
            transformer: Contact transformer

        Returns:
            GoogleContactsService: Service instance
        """
        return GoogleContactsService(
            connection=connection,
            client_factory=client_factory,
            transformer=transformer,
        )

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
