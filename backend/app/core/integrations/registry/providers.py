"""
Integration provider protocol.

Each integration (Google, Strava, etc.) implements this protocol so that the
``IntegrationRegistryService`` can aggregate their status into the
``GET /api/integrations`` response.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.registry.models import IntegrationInfo


class IntegrationProvider(Protocol):
    """
    Protocol for pluggable integration providers.

    Implementations derive integration status, capabilities, and sync summary
    from their own data sources (OAuth tokens, sync jobs, etc.).

    Every provider must expose ``integration_id`` as a class-level attribute
    so that the registry can identify a failing provider in error entries.
    """

    integration_id: str

    async def get_integration_info(
        self,
        user_id: str,
        connection: AsyncConnection,
    ) -> IntegrationInfo:
        """
        Return current integration metadata for a user.

        Args:
            user_id: The authenticated user's ID.
            connection: Active database connection for queries.

        Returns:
            IntegrationInfo with current status, capabilities, and sync summary.
        """
        ...
