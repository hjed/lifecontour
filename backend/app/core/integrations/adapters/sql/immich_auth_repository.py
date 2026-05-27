"""
Immich auth repository.

Provides data-access methods for the ``user_immich_auth`` table and
Immich-related rows in ``sync_jobs``.  Used by both the registry
provider and the token service so that raw SQL stays out of
business-logic classes.
"""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class ImmichSyncSummaryRow(NamedTuple):
    """Raw sync-summary data from the ``sync_jobs`` table."""

    sync_count: int
    error_count: int
    last_sync_time: datetime | None


class SqlImmichAuthRepository:
    """Repository for Immich authentication and sync data."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def is_connected(self, user_id: str) -> bool:
        """Check whether the user has stored Immich credentials.

        Args:
            user_id: Internal user ID.

        Returns:
            ``True`` if a row exists in ``user_immich_auth``.
        """
        stmt = text("""
            SELECT 1
            FROM user_immich_auth
            WHERE user_id = :user_id
        """)
        result = await self._connection.execute(stmt, {"user_id": user_id})
        return result.fetchone() is not None

    async def get_sync_summary(self, user_id: str) -> ImmichSyncSummaryRow:
        """Aggregate sync statistics for the Immich integration.

        Args:
            user_id: Internal user ID.

        Returns:
            A ``ImmichSyncSummaryRow`` with counts and the most recent
            sync timestamp.
        """
        stmt = text("""
            SELECT
                COUNT(*) as sync_count,
                COUNT(CASE WHEN status = 'failed' THEN 1 END) as error_count,
                MAX(completed_at) as last_sync_time
            FROM sync_jobs
            WHERE user_id = :user_id
              AND integration_source = 'immich'
        """)
        result = await self._connection.execute(stmt, {"user_id": user_id})
        row = result.fetchone()

        if row:
            return ImmichSyncSummaryRow(
                sync_count=row.sync_count or 0,
                error_count=row.error_count or 0,
                last_sync_time=row.last_sync_time,
            )

        return ImmichSyncSummaryRow(
            sync_count=0,
            error_count=0,
            last_sync_time=None,
        )
