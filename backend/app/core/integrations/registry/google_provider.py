"""
Google integration provider.

Derives Google integration status from OAuth token state and ``SyncJob``
history. Implements the ``IntegrationProvider`` protocol for registration
in the ``IntegrationRegistryService``.
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


class GoogleIntegrationProvider:
    """
    Derives Google integration status from OAuth tokens and sync jobs.

    Queries ``user_google_auth`` for connection/reauth state, and ``sync_jobs``
    for sync history. This logic mirrors the existing ``get_google_status``
    controller but packages the data into the generic ``IntegrationInfo`` model.
    """

    integration_id: str = "google"

    async def get_integration_info(
        self,
        user_id: str,
        connection: AsyncConnection,
    ) -> IntegrationInfo:
        """
        Return current Google integration metadata for a user.

        Args:
            user_id: The authenticated user's ID.
            connection: Active database connection for queries.

        Returns:
            IntegrationInfo with Google status, capabilities, and sync summary.
        """
        # 1. Query OAuth token state
        is_connected = False
        needs_reauth = False
        needs_reconsent = False

        auth_stmt = text("""
            SELECT granted_scopes, needs_reauth
            FROM user_google_auth
            WHERE user_id = :user_id
        """)
        auth_result = await connection.execute(auth_stmt, {"user_id": user_id})
        auth_rows = auth_result.fetchall()

        if auth_rows:
            is_connected = True
            for row in auth_rows:
                scopes = row.granted_scopes or ""
                if "calendar.events" not in scopes or "calendar.readonly" not in scopes:
                    needs_reconsent = True
                if row.needs_reauth:
                    needs_reauth = True
                if needs_reconsent and needs_reauth:
                    break

        # 2. Query sync job summary
        sync_stmt = text("""
            SELECT
                (SELECT completed_at
                 FROM sync_jobs
                 WHERE user_id = :user_id
                   AND integration_source = 'google'
                   AND status = 'completed'
                 ORDER BY completed_at DESC
                 LIMIT 1) AS last_sync_time,
                (SELECT COUNT(*)
                 FROM sync_jobs
                 WHERE user_id = :user_id
                   AND integration_source = 'google'
                   AND status = 'completed') AS completed_count,
                (SELECT COUNT(*)
                 FROM sync_jobs
                 WHERE user_id = :user_id
                   AND integration_source = 'google'
                   AND status = 'failed') AS failed_count
        """)
        sync_result = await connection.execute(sync_stmt, {"user_id": user_id})
        sync_row = sync_result.fetchone()

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
            name="Google",
            status=status,
            capabilities=[
                IntegrationCapability.CONTACTS_SYNC,
                IntegrationCapability.CALENDAR_SYNC,
            ],
            sync_summary=sync_summary,
            needs_reauth=needs_reauth,
            needs_reconsent=needs_reconsent,
        )
