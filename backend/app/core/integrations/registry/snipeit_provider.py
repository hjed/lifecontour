"""
Snipe-IT integration provider.

Derives Snipe-IT integration status from the ``snipeit_settings`` table.
Implements the ``IntegrationProvider`` protocol for registration in the
``IntegrationRegistryService``.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.snipeit_settings_repository import (
    SqlSnipeItSettingsRepository,
)
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

        Note:
            Phase 1 always returns DISCONNECTED because there are no OAuth
            endpoints yet.  Returning CONNECTED would cause the UI to render
            Connect/Disconnect buttons that call non-existent OAuth routes.
            Phase 2 will add ``user_snipe_it_auth`` and upgrade this logic
            to derive CONNECTED from actual OAuth tokens.
        """
        # Phase 1: always DISCONNECTED — no OAuth flow exists yet.
        # The settings table is checked only for future use / logging.
        try:
            repo = SqlSnipeItSettingsRepository(connection)
            settings = await repo.get_by_user_id(user_id)

            if settings and settings.base_url:
                logger.debug(
                    "Snipe-IT settings exist but OAuth not implemented yet",
                    user_id=user_id,
                    base_url=settings.base_url,
                )
        except Exception:
            # Table may not exist yet (migration hasn't run) —
            # log at warning so unexpected DB failures are visible.
            logger.warning(
                "snipeit_settings query failed — table may not exist yet",
                user_id=user_id,
                exc_info=True,
            )

        # Sync summary — populated in later phases when sync jobs exist
        sync_summary = SyncSummary()

        return IntegrationInfo(
            id=self.integration_id,
            name="Snipe-IT",
            status=IntegrationStatus.DISCONNECTED,
            capabilities=[
                IntegrationCapability.GEAR_SYNC,
                IntegrationCapability.MAINTENANCE_SYNC,
                IntegrationCapability.CHECKOUT_SYNC,
            ],
            sync_summary=sync_summary,
            needs_reauth=False,
            needs_reconsent=False,
        )
