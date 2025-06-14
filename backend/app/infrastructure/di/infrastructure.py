"""
Infrastructure providers for Dishka dependency injection.

Provides general infrastructure services like settings, search, and event publishing.
"""

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.config import Settings, get_settings
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
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
    def get_outbox_event_publisher(
        self, connection: AsyncConnection
    ) -> OutboxEventPublisher:
        """Get outbox event publisher for request scope."""
        return OutboxEventPublisher(connection)
