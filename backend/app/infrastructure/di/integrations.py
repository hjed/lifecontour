"""
Dependency injection provider for integration services.

Provides integration-related dependencies including task queue configuration,
database managers, base integration services, and the pluggable integration
registry.
"""

from arq.connections import ArqRedis, RedisSettings
from core_shared.repositories.external_reference_repository import (
    ExternalReferenceRepository,
)
from core_shared.repositories.integration_link_repository import (
    IntegrationLinkRepository,
)
from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.repositories import ContactRepository
from app.core.contacts.services.contact_service import ContactService
from app.core.integrations.adapters.sql.journal_unmatched_strava_athlete_repository import (
    SqlJournalUnmatchedStravaAthleteRepository,
)
from app.core.integrations.adapters.sql.snipeit_settings_repository import (
    SqlSnipeItSettingsRepository,
)
from app.core.integrations.adapters.sql.strava_athlete_mapping_repository import (
    SqlStravaAthleteMappingRepository,
)
from app.core.integrations.database import IntegrationDatabaseManager
from app.core.integrations.encryption import EncryptionService
from app.core.integrations.external_reference_service import ExternalReferenceService
from app.core.integrations.health_service import IntegrationHealthService
from app.core.integrations.immich.adapters.album_api_client import ImmichAlbumApiClient
from app.core.integrations.immich.album_cover_proxy_service import (
    AlbumCoverProxyService,
)
from app.core.integrations.immich.album_creation_service import (
    ImmichAlbumCreationService,
)
from app.core.integrations.immich.asset_thumbnail_proxy_service import (
    AssetThumbnailProxyService,
)
from app.core.integrations.immich.avatar_proxy_service import AvatarProxyService
from app.core.integrations.outbox_event_processor import OutboxEventProcessor
from app.core.integrations.registry.google_provider import GoogleIntegrationProvider
from app.core.integrations.registry.immich_provider import ImmichIntegrationProvider
from app.core.integrations.registry.service import IntegrationRegistryService
from app.core.integrations.registry.snipeit_provider import SnipeItIntegrationProvider
from app.core.integrations.registry.strava_provider import StravaIntegrationProvider
from app.core.integrations.services.snipeit_settings_service import (
    SnipeItSettingsService,
)
from app.core.integrations.strava.athlete_mapping_service import (
    StravaAthleteMappingService,
)
from app.core.integrations.task_queue import get_redis_pool, get_redis_settings
from app.core.integrations.task_queue_service import TaskQueueService
from app.core.journal.models.repositories import JournalContactRelationshipRepository
from app.infrastructure.auth.immich_token_service import ImmichTokenService
from app.infrastructure.auth.snipeit_token_service import SnipeItTokenService
from app.infrastructure.auth.strava_token_service import StravaTokenService
from app.infrastructure.config import Settings


class IntegrationProvider(Provider):
    """Provider for integration-related dependencies."""

    scope = Scope.APP

    @provide
    async def provide_redis_pool(self, settings: Settings) -> ArqRedis:
        """
        Provide Redis connection pool for ARQ tasks.

        Args:
            settings: Application settings

        Returns:
            ArqRedis: ARQ Redis connection pool
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
        redis_pool: ArqRedis,
        settings: Settings,
        db_manager: IntegrationDatabaseManager,
    ) -> TaskQueueService:
        """
        Provide task queue service for request scope.

        Args:
            redis_pool: ARQ Redis connection pool
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
        self, redis_pool: ArqRedis, db_manager: IntegrationDatabaseManager
    ) -> IntegrationHealthService:
        """
        Provide integration health service for request scope.

        Args:
            redis_pool: ARQ Redis connection pool
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

    # Registry providers

    @provide(scope=Scope.APP)
    def provide_google_integration_provider(self) -> GoogleIntegrationProvider:
        """
        Provide Google integration provider (singleton).

        Returns:
            GoogleIntegrationProvider: Google status/capability provider
        """
        return GoogleIntegrationProvider()

    @provide(scope=Scope.APP)
    def provide_strava_integration_provider(self) -> StravaIntegrationProvider:
        """
        Provide Strava integration provider (singleton).

        Returns:
            StravaIntegrationProvider: Strava status/capability provider
        """
        return StravaIntegrationProvider()

    @provide(scope=Scope.APP)
    def provide_snipeit_integration_provider(self) -> SnipeItIntegrationProvider:
        """
        Provide Snipe-IT integration provider (singleton).

        Returns:
            SnipeItIntegrationProvider: Snipe-IT status/capability provider
        """
        return SnipeItIntegrationProvider()

    @provide(scope=Scope.APP)
    def provide_immich_integration_provider(self) -> ImmichIntegrationProvider:
        """
        Provide Immich integration provider (singleton).

        Returns:
            ImmichIntegrationProvider: Immich status/capability provider
        """
        return ImmichIntegrationProvider()

    @provide(scope=Scope.APP)
    def provide_integration_registry_service(
        self,
        google_provider: GoogleIntegrationProvider,
        strava_provider: StravaIntegrationProvider,
        snipeit_provider: SnipeItIntegrationProvider,
        immich_provider: ImmichIntegrationProvider,
    ) -> IntegrationRegistryService:
        """
        Provide integration registry service with all registered providers.

        Args:
            google_provider: Google integration provider
            strava_provider: Strava integration provider
            snipeit_provider: Snipe-IT integration provider
            immich_provider: Immich integration provider

        Returns:
            IntegrationRegistryService: Registry aggregating all providers
        """
        return IntegrationRegistryService(
            providers=[
                google_provider,
                strava_provider,
                snipeit_provider,
                immich_provider,
            ]
        )

    @provide(scope=Scope.REQUEST)
    def provide_strava_token_service(
        self, connection: AsyncConnection, settings: Settings
    ) -> StravaTokenService:
        """
        Provide Strava token service for request scope.

        Args:
            connection: Database connection
            settings: Application settings for encryption key

        Returns:
            StravaTokenService: Service for Strava token CRUD operations
        """
        return StravaTokenService(
            connection=connection,
            encryption_key=settings.strava_encryption_key,
        )

    @provide(scope=Scope.REQUEST)
    def provide_strava_athlete_mapping_repository(
        self, connection: AsyncConnection
    ) -> SqlStravaAthleteMappingRepository:
        """Provide repository for Strava athlete mappings."""
        from app.core.integrations.adapters.sql.strava_athlete_mapping_repository import (
            SqlStravaAthleteMappingRepository,
        )

        return SqlStravaAthleteMappingRepository(connection)

    @provide(scope=Scope.REQUEST)
    def provide_snipeit_token_service(
        self, connection: AsyncConnection, settings: Settings
    ) -> SnipeItTokenService:
        """Provide Snipe-IT token service for request scope.

        Args:
            connection: Database connection
            settings: Application settings for encryption key

        Returns:
            SnipeItTokenService: Service for Snipe-IT token CRUD operations
        """
        return SnipeItTokenService(
            connection=connection,
            encryption_key=settings.snipeit_encryption_key,
        )

    @provide(scope=Scope.REQUEST)
    def provide_immich_token_service(
        self, connection: AsyncConnection, settings: Settings
    ) -> ImmichTokenService:
        """Provide Immich token service for request scope.

        Args:
            connection: Database connection
            settings: Application settings for encryption key

        Returns:
            ImmichTokenService: Service for Immich token CRUD operations
        """
        return ImmichTokenService(
            connection=connection,
            encryption_key=settings.immich_encryption_key,
        )

    @provide(scope=Scope.REQUEST)
    def provide_external_reference_repository(
        self, connection: AsyncConnection
    ) -> ExternalReferenceRepository:
        """Provide ExternalReferenceRepository for request scope."""
        return ExternalReferenceRepository(connection=connection)

    @provide(scope=Scope.REQUEST)
    def provide_integration_link_repository(
        self, connection: AsyncConnection
    ) -> IntegrationLinkRepository:
        """Provide IntegrationLinkRepository (canonical link reads) per request."""
        return IntegrationLinkRepository(connection=connection)

    @provide(scope=Scope.REQUEST)
    def provide_avatar_proxy_service(
        self,
        link_repo: IntegrationLinkRepository,
        immich_token_service: ImmichTokenService,
    ) -> AvatarProxyService:
        """Provide avatar proxy service for request scope.

        Args:
            link_repo: Canonical integration-link repository for person lookups
            immich_token_service: Service for Immich credential management

        Returns:
            AvatarProxyService: Service for proxying Immich thumbnails
        """
        return AvatarProxyService(
            ext_ref_repo=link_repo,
            immich_token_service=immich_token_service,
        )

    @provide(scope=Scope.REQUEST)
    def provide_album_cover_proxy_service(
        self,
        connection: AsyncConnection,
        immich_token_service: ImmichTokenService,
    ) -> AlbumCoverProxyService:
        """Provide the album cover proxy service for request scope.

        Returns:
            AlbumCoverProxyService: Service for proxying Immich album covers
        """
        from app.core.journal.adapters.sql.album_sync_read_repository import (
            AlbumSyncReadRepository,
        )

        return AlbumCoverProxyService(
            album_repo=AlbumSyncReadRepository(connection),
            immich_token_service=immich_token_service,
        )

    @provide(scope=Scope.APP)
    def provide_immich_album_api_client(self) -> ImmichAlbumApiClient:
        """Provide the backend Immich album API client (stateless singleton)."""
        return ImmichAlbumApiClient()

    @provide(scope=Scope.REQUEST)
    def provide_asset_thumbnail_proxy_service(
        self, immich_token_service: ImmichTokenService
    ) -> AssetThumbnailProxyService:
        """Provide the Immich asset thumbnail proxy service for request scope."""
        return AssetThumbnailProxyService(immich_token_service=immich_token_service)

    @provide(scope=Scope.REQUEST)
    def provide_immich_album_creation_service(
        self,
        connection: AsyncConnection,
        immich_token_service: ImmichTokenService,
        api_client: ImmichAlbumApiClient,
    ) -> ImmichAlbumCreationService:
        """Provide the Immich album creation service for request scope."""
        from app.core.journal.adapters.sql.album_sync_read_repository import (
            AlbumSyncReadRepository,
        )
        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )
        from app.core.settings.adapters.sql.user_settings_repository import (
            SqlUserSettingsRepository,
        )

        return ImmichAlbumCreationService(
            connection=connection,
            token_service=immich_token_service,
            api_client=api_client,
            journal_repo=SqlJournalRepository(connection),
            album_link_repo=AlbumSyncReadRepository(connection),
            user_settings_repo=SqlUserSettingsRepository(connection),
        )

    @provide(scope=Scope.REQUEST)
    def provide_snipeit_settings_repository(
        self, connection: AsyncConnection
    ) -> SqlSnipeItSettingsRepository:
        """Provide repository for Snipe-IT settings."""
        from app.core.integrations.adapters.sql.snipeit_settings_repository import (
            SqlSnipeItSettingsRepository,
        )

        return SqlSnipeItSettingsRepository(connection)

    @provide(scope=Scope.REQUEST)
    def provide_snipeit_settings_service(
        self, settings_repo: SqlSnipeItSettingsRepository
    ) -> SnipeItSettingsService:
        """Provide a SnipeItSettingsService instance."""
        return SnipeItSettingsService(settings_repo)

    @provide(scope=Scope.REQUEST)
    def provide_unmatched_strava_athlete_repository(
        self, connection: AsyncConnection
    ) -> SqlJournalUnmatchedStravaAthleteRepository:
        """Provide repository for unmatched Strava athletes on journals."""
        from app.core.integrations.adapters.sql.journal_unmatched_strava_athlete_repository import (
            SqlJournalUnmatchedStravaAthleteRepository,
        )

        return SqlJournalUnmatchedStravaAthleteRepository(connection)

    @provide(scope=Scope.REQUEST)
    def provide_strava_athlete_mapping_service(
        self,
        connection: AsyncConnection,
        mapping_repo: SqlStravaAthleteMappingRepository,
        unmatched_repo: SqlJournalUnmatchedStravaAthleteRepository,
        contact_repo: ContactRepository,
        contact_relationship_repo: JournalContactRelationshipRepository,
    ) -> StravaAthleteMappingService:
        """Provide Strava athlete mapping service."""
        from app.core.integrations.strava.athlete_mapping_service import (
            StravaAthleteMappingService,
        )

        return StravaAthleteMappingService(
            connection=connection,
            mapping_repo=mapping_repo,
            unmatched_repo=unmatched_repo,
            contact_repo=contact_repo,
            contact_relationship_repo=contact_relationship_repo,
        )
