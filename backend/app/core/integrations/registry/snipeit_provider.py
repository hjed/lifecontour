"""
Snipe-IT integration provider.

Derives Snipe-IT integration status from the ``snipeit_settings`` table.
Implements the ``IntegrationProvider`` protocol for registration in the
``IntegrationRegistryService``.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.registry.models import (
    IntegrationCapability,
    IntegrationInfo,
    IntegrationStatus,
    SyncSummary,
)

logger = structlog.get_logger()


class SnipeItIntegrationProvider:
    """
    Derives Snipe-IT integration status from configuration settings.

    Queries ``snipeit_settings`` for connection configuration. In Phase 1
    the integration is considered "disconnected" when no settings exist.
    Phase 2 will add the ``user_snipe_it_auth`` table for full OAuth status.
    """

    integration_id: str = "snipeit"

    async def get_integration_info(
        self,
        user_id: str,
        connection: AsyncConnection,
    ) -> IntegrationInfo:
        """
        Return current Snipe-IT integration metadata for a user.

        Args:
            user_id: The authenticated user's ID.
            connection: Active database connection for queries.

        Returns:
            IntegrationInfo with Snipe-IT status, capabilities, and sync
            summary.
        """
        is_configured = False

        # Check whether the user has configured Snipe-IT settings
        try:
            settings_stmt = text("""
                SELECT base_url, snipeit_user_id
                FROM snipeit_settings
                WHERE user_id = :user_id
            """)
            settings_result = await connection.execute(
                settings_stmt, {"user_id": user_id}
            )
            settings_row = settings_result.fetchone()

            if settings_row and settings_row.base_url:
                is_configured = True
        except Exception:
            # Table may not exist yet (Phase 1 migration hasn't run) —
            # treat as disconnected.
            logger.debug(
                "snipeit_settings query failed — table may not exist yet",
                user_id=user_id,
            )

        # Derive status
        status = (
            IntegrationStatus.DISCONNECTED
            if not is_configured
            else IntegrationStatus.CONNECTED
        )

        # Sync summary — populated in later phases when sync jobs exist
        sync_summary = SyncSummary()

        return IntegrationInfo(
            id=self.integration_id,
            name="Snipe-IT",
            status=status,
            capabilities=[
                IntegrationCapability.GEAR_SYNC,
                IntegrationCapability.MAINTENANCE_SYNC,
                IntegrationCapability.CHECKOUT_SYNC,
            ],
            sync_summary=sync_summary,
            needs_reauth=False,
            needs_reconsent=False,
        )
