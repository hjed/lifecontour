"""
Integration registry service.

Aggregates integration status from all registered providers. Each provider
implements ``IntegrationProvider`` and returns its own ``IntegrationInfo``.
Provider failures are isolated — a failing provider produces an error entry
without affecting other providers.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.registry.models import IntegrationInfo, IntegrationStatus
from app.core.integrations.registry.providers import IntegrationProvider

logger = structlog.get_logger()


class IntegrationRegistryService:
    """
    Aggregates integration metadata from pluggable providers.

    Providers are registered at container startup via Dishka DI. Each call to
    ``list_integrations`` queries every provider for the given user.
    """

    def __init__(self, providers: list[IntegrationProvider]) -> None:
        """
        Initialize the registry with a list of providers.

        Args:
            providers: Objects implementing the ``IntegrationProvider`` protocol.
        """
        self._providers = providers

    async def list_integrations(
        self,
        user_id: str,
        connection: AsyncConnection,
    ) -> list[IntegrationInfo]:
        """
        Query all registered providers and return their integration info.

        Provider failures are isolated: a provider that raises an exception
        will produce an error entry, and remaining providers will still be
        queried.

        Args:
            user_id: The authenticated user's ID.
            connection: Active database connection shared across providers.

        Returns:
            List of ``IntegrationInfo``, one per registered provider.
        """
        results: list[IntegrationInfo] = []

        for provider in self._providers:
            try:
                info = await provider.get_integration_info(user_id, connection)
                results.append(info)
            except Exception:
                integration_id = getattr(provider, "integration_id", "unknown")
                logger.exception(
                    "Integration provider failed",
                    integration_id=integration_id,
                    user_id=user_id,
                )
                results.append(
                    IntegrationInfo(
                        id=integration_id,
                        name=integration_id.title(),
                        status=IntegrationStatus.ERROR,
                    )
                )

        return results
