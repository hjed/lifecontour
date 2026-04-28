"""
Infrastructure providers for Dishka dependency injection.

Provides general infrastructure services like settings, search, and event publishing.
"""

from core_shared.stream_client import StreamClient
from dishka import AsyncContainer, Provider, Scope, provide
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.config import Settings, get_settings
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.events.outbox_processor import OutboxProcessor
from app.infrastructure.search.reindex_service import ReindexService
from app.infrastructure.search.search_service import SearchService


class InfrastructureProvider(Provider):
    """Provider for general infrastructure dependencies."""

    @provide(scope=Scope.APP)
    def get_settings(self) -> Settings:
        """Get application settings (singleton for app lifetime)."""
        return get_settings()

    @provide(scope=Scope.APP)
    def get_search_service(self) -> SearchService:
        """Get search service (singleton for app lifetime)."""
        return SearchService()

    @provide(scope=Scope.REQUEST)
    def get_reindex_service(self, connection: AsyncConnection) -> ReindexService:
        """Get re-index service for request scope."""
        return ReindexService(connection)

    @provide(scope=Scope.REQUEST)
    def get_outbox_event_publisher(
        self, connection: AsyncConnection
    ) -> OutboxEventPublisher:
        """Get outbox event publisher for request scope."""
        return OutboxEventPublisher(connection)

    @provide(scope=Scope.APP)
    def provide_outbox_processor(self, container: AsyncContainer) -> OutboxProcessor:
        """Get outbox processor for app scope."""
        return OutboxProcessor(container)

    @provide(scope=Scope.APP)
    def provide_stream_client(self, settings: Settings) -> StreamClient:
        """Get Redis Streams client for app scope.

        Creates an async Redis connection from the configured redis_url
        and wraps it in a StreamClient for use by the OutboxRelay and
        StreamConsumer instances.
        """
        redis = Redis.from_url(settings.redis_url, decode_responses=False)
        return StreamClient(redis)
