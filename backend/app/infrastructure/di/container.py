"""
Dishka container setup and configuration.

Creates and configures the main dependency injection container for the application.
"""

from dishka import AsyncContainer, make_async_container
from dishka.integrations.fastapi import FastapiProvider

from app.infrastructure.config import Settings
from app.infrastructure.di.auth import AuthProvider
from app.infrastructure.di.contacts import ContactProvider
from app.infrastructure.di.database import DatabaseProvider
from app.infrastructure.di.infrastructure import InfrastructureProvider
from app.infrastructure.di.integrations import IntegrationProvider
from app.infrastructure.di.journal import JournalProvider
from app.infrastructure.di.settings import SettingsProvider
from app.infrastructure.di.tasks import TaskProvider


def create_container(settings: Settings | None = None) -> AsyncContainer:
    """
    Create and configure the main Dishka container.

    Args:
        settings: Optional settings to use for configuration

    Returns:
        AsyncContainer: Configured container with all providers
    """
    return make_async_container(
        DatabaseProvider(settings),
        InfrastructureProvider(),
        AuthProvider(),
        ContactProvider(),
        JournalProvider(),
        TaskProvider(),
        IntegrationProvider(),
        SettingsProvider(),
        FastapiProvider(),  # Provides FastAPI Request/WebSocket objects
    )
