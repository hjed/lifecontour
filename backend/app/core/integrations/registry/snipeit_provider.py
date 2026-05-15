"""
Snipe-IT integration provider.

Derives Snipe-IT integration status from the ``user_snipe_it_auth`` table.
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
    Derives Snipe-IT integration status from OAuth tokens and sync jobs.

    Queries ``user_snipe_it_auth`` for connection/reauth state, and
    ``sync_jobs`` for sync history. Packages the data into the generic
    ``IntegrationInfo`` model for the pluggable integration registry.
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
        # 1. Query OAuth token state
        is_connected = False
        needs_reauth = False

        try:
            auth_stmt = text("""
                SELECT needs_reauth
                FROM user_snipe_it_auth
                WHERE user_id = :user_id
            """)
            auth_result = await connection.execute(auth_stmt, {"user_id": user_id})
            auth_row = auth_result.fetchone()

            if auth_row:
                is_connected = True
                needs_reauth = bool(auth_row.needs_reauth)
        except Exception as e:
            # Gracefully degrade if table doesn't exist yet (e.g. during deployment)
            logger.warning(
                "Failed to query user_snipe_it_auth",
                user_id=user_id,
                error=str(e),
            )

        # 2. Query sync summary from sync_jobs (Snipe-IT uses 'snipeit' source)
        try:
            sync_stmt = text("""
                SELECT
                    MAX(CASE WHEN status = 'completed' THEN completed_at END)
                        AS last_sync_time,
                    COUNT(CASE WHEN status = 'completed' THEN 1 END)
                        AS completed_count,
                    COUNT(CASE WHEN status = 'failed' THEN 1 END)
                        AS failed_count
                FROM sync_jobs
                WHERE user_id = :user_id AND integration_source = 'snipeit'
            """)
            sync_result = await connection.execute(sync_stmt, {"user_id": user_id})
            sync_row = sync_result.fetchone()
        except Exception as e:
            logger.warning(
                "Failed to query sync_jobs for Snipe-IT",
                user_id=user_id,
                error=str(e),
            )
            sync_row = None

        sync_summary = SyncSummary(
            last_sync_time=sync_row.last_sync_time if sync_row else None,
            sync_count=sync_row.completed_count if sync_row else 0,
            error_count=sync_row.failed_count if sync_row else 0,
        )

        # 3. Derive status
        if not is_connected:
            status = IntegrationStatus.DISCONNECTED
        elif needs_reauth:
            status = IntegrationStatus.TOKEN_EXPIRED
        else:
            status = IntegrationStatus.CONNECTED

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
            needs_reauth=needs_reauth,
            needs_reconsent=False,
        )
