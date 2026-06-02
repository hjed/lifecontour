"""
Repository for ``sync_conflicts`` table operations.

Provides CRUD helpers used by integration workers to create, list, and
resolve sync conflicts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = structlog.get_logger(__name__)


class SyncConflictRepository:
    """Database operations for the ``sync_conflicts`` table.

    Args:
        connection: An async SQLAlchemy connection (typically injected).
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self._conn = connection

    async def create(
        self,
        *,
        user_id: str,
        integration_source: str,
        external_entity_id: str,
        external_entity_name: str | None = None,
        candidate_contact_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Create or update an unresolved sync conflict.

        Uses ``ON CONFLICT`` on the partial unique index to prevent
        duplicates for the same unresolved entity.

        Returns:
            Dictionary with the conflict row data.
        """
        candidates_json = json.dumps(candidate_contact_ids or [])
        now = datetime.now(UTC)

        query = text("""
            INSERT INTO sync_conflicts
                (user_id, integration_source, external_entity_id,
                 external_entity_name, candidate_contact_ids, status,
                 created_at, updated_at)
            VALUES
                (:user_id, :integration_source, :external_entity_id,
                 :external_entity_name, :candidate_contact_ids::jsonb,
                 'unresolved', :now, :now)
            ON CONFLICT (user_id, integration_source, external_entity_id)
                WHERE status = 'unresolved'
            DO UPDATE SET
                external_entity_name = EXCLUDED.external_entity_name,
                candidate_contact_ids = EXCLUDED.candidate_contact_ids,
                updated_at = EXCLUDED.updated_at
            RETURNING id, user_id, integration_source, external_entity_id,
                      external_entity_name, candidate_contact_ids, status,
                      resolved_contact_id, created_at, updated_at
        """)

        result = await self._conn.execute(
            query,
            {
                "user_id": user_id,
                "integration_source": integration_source,
                "external_entity_id": external_entity_id,
                "external_entity_name": external_entity_name,
                "candidate_contact_ids": candidates_json,
                "now": now,
            },
        )
        row = result.fetchone()
        if not row:
            raise RuntimeError("Failed to create sync conflict")

        return self._row_to_dict(row)

    async def find_unresolved(
        self,
        user_id: str,
        integration_source: str,
    ) -> list[dict[str, Any]]:
        """List all unresolved conflicts for a user and integration.

        Returns:
            List of conflict dictionaries.
        """
        query = text("""
            SELECT id, user_id, integration_source, external_entity_id,
                   external_entity_name, candidate_contact_ids, status,
                   resolved_contact_id, created_at, updated_at
            FROM sync_conflicts
            WHERE user_id = :user_id
              AND integration_source = :integration_source
              AND status = 'unresolved'
            ORDER BY created_at DESC
        """)

        result = await self._conn.execute(
            query,
            {"user_id": user_id, "integration_source": integration_source},
        )
        return [self._row_to_dict(row) for row in result.fetchall()]

    async def find_by_external_id(
        self,
        user_id: str,
        integration_source: str,
        external_entity_id: str,
    ) -> dict[str, Any] | None:
        """Find an unresolved conflict by its external entity ID.

        Returns:
            Conflict dictionary or ``None``.
        """
        query = text("""
            SELECT id, user_id, integration_source, external_entity_id,
                   external_entity_name, candidate_contact_ids, status,
                   resolved_contact_id, created_at, updated_at
            FROM sync_conflicts
            WHERE user_id = :user_id
              AND integration_source = :integration_source
              AND external_entity_id = :external_entity_id
              AND status = 'unresolved'
        """)

        result = await self._conn.execute(
            query,
            {
                "user_id": user_id,
                "integration_source": integration_source,
                "external_entity_id": external_entity_id,
            },
        )
        row = result.fetchone()
        return self._row_to_dict(row) if row else None

    async def resolve(
        self,
        conflict_id: int,
        resolved_contact_id: int,
    ) -> dict[str, Any] | None:
        """Mark a conflict as resolved with the chosen contact.

        Returns:
            Updated conflict dictionary, or ``None`` if not found.
        """
        query = text("""
            UPDATE sync_conflicts
            SET status = 'resolved',
                resolved_contact_id = :resolved_contact_id,
                updated_at = :now
            WHERE id = :id
              AND status = 'unresolved'
            RETURNING id, user_id, integration_source, external_entity_id,
                      external_entity_name, candidate_contact_ids, status,
                      resolved_contact_id, created_at, updated_at
        """)

        result = await self._conn.execute(
            query,
            {
                "id": conflict_id,
                "resolved_contact_id": resolved_contact_id,
                "now": datetime.now(UTC),
            },
        )
        row = result.fetchone()
        return self._row_to_dict(row) if row else None

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a database row to a dictionary."""
        return {
            "id": row.id,
            "user_id": row.user_id,
            "integration_source": row.integration_source,
            "external_entity_id": row.external_entity_id,
            "external_entity_name": row.external_entity_name,
            "candidate_contact_ids": row.candidate_contact_ids,
            "status": row.status,
            "resolved_contact_id": row.resolved_contact_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
