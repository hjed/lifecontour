"""
Immich Integration Provider.

Exposes Immich integration status and capabilities to the integration registry.
"""

from typing import Any

from sqlalchemy import text

from app.core.integrations.registry.models import (
    IntegrationCapability,
    IntegrationInfo,
    IntegrationStatus,
    SyncSummary,
)
from app.core.integrations.registry.providers import IntegrationProvider


class ImmichIntegrationProvider(IntegrationProvider):
    """Provider for the Immich integration."""

    integration_id: str = "immich"

    def __init__(self) -> None:
        """Initialize Immich provider."""
        self.name = "Immich"
        self.capabilities = [
            IntegrationCapability.CONTACTS_SYNC,
            IntegrationCapability.ALBUM_SYNC,
        ]

    async def get_integration_info(self, user_id: str, session: Any) -> IntegrationInfo:
        """
        Get the current status and metadata of the Immich integration.

        Args:
            user_id: Internal user ID.
            session: Async database session.

        Returns:
            IntegrationInfo object representing the current state.
        """
        # 1. Check if connected by querying the auth table
        auth_stmt = text("""
            SELECT 1
            FROM user_immich_auth
            WHERE user_id = :user_id
        """)
        auth_result = await session.execute(auth_stmt, {"user_id": user_id})
        is_connected = auth_result.fetchone() is not None

        if not is_connected:
            return IntegrationInfo(
                id=self.integration_id,
                name=self.name,
                status=IntegrationStatus.DISCONNECTED,
                capabilities=self.capabilities,
                sync_summary=SyncSummary(),
                needs_reauth=False,
            )

        # 2. Get sync history from sync_jobs table
        sync_stmt = text("""
            SELECT
                COUNT(*) as sync_count,
                COUNT(CASE WHEN status = 'failed' THEN 1 END) as error_count,
                MAX(completed_at) as last_sync_time
            FROM sync_jobs
            WHERE user_id = :user_id
              AND integration_source = 'immich'
        """)
        sync_result = await session.execute(sync_stmt, {"user_id": user_id})
        sync_row = sync_result.fetchone()

        sync_summary = SyncSummary()
        if sync_row:
            sync_summary = SyncSummary(
                sync_count=sync_row.sync_count or 0,
                error_count=sync_row.error_count or 0,
                last_sync_time=sync_row.last_sync_time,
            )

        return IntegrationInfo(
            id=self.integration_id,
            name=self.name,
            status=IntegrationStatus.CONNECTED,
            capabilities=self.capabilities,
            sync_summary=sync_summary,
            needs_reauth=False,  # API keys don't expire like OAuth tokens
        )
