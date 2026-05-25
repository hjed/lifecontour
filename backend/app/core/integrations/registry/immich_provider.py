"""
Immich Integration Provider.

Exposes Immich integration status and capabilities to the integration registry.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.immich_auth_repository import (
    SqlImmichAuthRepository,
)
from app.core.integrations.registry.models import (
    IntegrationCapability,
    IntegrationInfo,
    IntegrationStatus,
    SyncSummary,
)

logger = structlog.get_logger()


class ImmichIntegrationProvider:
    """Provider for the Immich integration."""

    integration_id: str = "immich"

    async def get_integration_info(
        self, user_id: str, connection: AsyncConnection
    ) -> IntegrationInfo:
        """
        Get the current status and metadata of the Immich integration.

        Args:
            user_id: Internal user ID.
            connection: Async database connection.

        Returns:
            IntegrationInfo object representing the current state.
        """
        repo = SqlImmichAuthRepository(connection)

        # 1. Check if connected via repository
        try:
            is_connected = await repo.is_connected(user_id)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Failed to query user_immich_auth",
                user_id=user_id,
                error=str(e),
            )
            is_connected = False

        if not is_connected:
            return IntegrationInfo(
                id=self.integration_id,
                name="Immich",
                status=IntegrationStatus.DISCONNECTED,
                capabilities=[
                    IntegrationCapability.CONTACTS_SYNC,
                    IntegrationCapability.ALBUM_SYNC,
                ],
                sync_summary=SyncSummary(),
                needs_reauth=False,
            )

        # 2. Get sync summary via repository
        try:
            summary_row = await repo.get_sync_summary(user_id)
            sync_summary = SyncSummary(
                sync_count=summary_row.sync_count,
                error_count=summary_row.error_count,
                last_sync_time=summary_row.last_sync_time,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Failed to query sync_jobs for Immich",
                user_id=user_id,
                error=str(e),
            )
            sync_summary = SyncSummary()

        return IntegrationInfo(
            id=self.integration_id,
            name="Immich",
            status=IntegrationStatus.CONNECTED,
            capabilities=[
                IntegrationCapability.CONTACTS_SYNC,
                IntegrationCapability.ALBUM_SYNC,
            ],
            sync_summary=sync_summary,
            needs_reauth=False,  # API keys don't expire like OAuth tokens
        )
