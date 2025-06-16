"""
Dependency injection provider for integration services.

Provides integration-related dependencies including task queue configuration,
database managers, and base integration services.
"""

from arq.connections import RedisSettings
from dishka import Provider, Scope, provide
from redis.asyncio import Redis

from app.core.integrations.database import IntegrationDatabaseManager
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
