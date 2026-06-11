"""
User settings providers for Dishka dependency injection.

Provides the user settings repository used by the settings API and by
timezone-aware AI prompt generation.
"""

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettingsRepository
from app.core.settings.services.user_settings_service import UserSettingsService


class SettingsProvider(Provider):
    """Provides user settings repository and service instances."""

    @provide(scope=Scope.REQUEST, provides=UserSettingsRepository)
    def user_settings_repository(
        self, connection: AsyncConnection
    ) -> SqlUserSettingsRepository:
        """Provide a SqlUserSettingsRepository instance."""
        return SqlUserSettingsRepository(connection)

    @provide(scope=Scope.REQUEST)
    def user_settings_service(
        self, settings_repo: UserSettingsRepository
    ) -> UserSettingsService:
        """Provide a UserSettingsService instance."""
        return UserSettingsService(settings_repo)
