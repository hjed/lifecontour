"""Shared fixtures for API integration tests."""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def integration_api_client(async_connection, clean_database, test_settings):  # noqa: ARG001
    """Create async test client for API integration tests with real database setup."""
    from dishka import Provider, Scope, make_async_container, provide
    from dishka.integrations.fastapi import FastapiProvider, setup_dishka
    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.infrastructure.auth.models import SessionUser
    from app.infrastructure.di.contacts import ContactProvider
    from app.infrastructure.di.infrastructure import InfrastructureProvider
    from app.infrastructure.di.integrations import IntegrationProvider
    from app.infrastructure.di.journal import JournalProvider

    # Create a test provider that uses our test connection
    class TestDatabaseProvider(Provider):
        def __init__(self, connection: AsyncConnection):
            super().__init__()
            self.connection = connection

        @provide(scope=Scope.REQUEST)
        async def get_connection(self) -> AsyncConnection:
            return self.connection

        @provide(scope=Scope.REQUEST)
        def get_session_user(self) -> SessionUser:
            # Provide a test user for authenticated endpoints
            return SessionUser(
                id="test-user-123",
                email="test@example.com",
                name="Test User",
                avatar_url="https://example.com/avatar.jpg",
                provider="test",
            )

    app = create_app(settings=test_settings)

    # Replace the Dishka container with our test container
    await app.state.dishka_container.close()  # Close the original container

    test_container = make_async_container(
        TestDatabaseProvider(async_connection),
        InfrastructureProvider(),
        ContactProvider(),
        JournalProvider(),
        IntegrationProvider(),
        FastapiProvider(),
    )
    app.state.dishka_container = test_container
    setup_dishka(test_container, app)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client

    # Clean up the test container
    await test_container.close()
