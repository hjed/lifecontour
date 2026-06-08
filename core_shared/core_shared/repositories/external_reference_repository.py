"""
Repository for ``external_references`` table operations.

Provides shared data-access methods for managing links between internal
entities and external system entities.  Used by integration workers and
the main application backend.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = structlog.get_logger(__name__)


class ExternalReferenceRepository:
    """Database operations for the ``external_references`` table.

    Args:
        connection: An async SQLAlchemy connection.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self._conn = connection

    async def find_by_internal_entity(
        self,
        internal_entity_type: str,
        internal_entity_id: int,
        external_system: str,
        external_entity_type: str | None = None,
    ) -> dict[str, Any] | None:
        """Find an external reference for an internal entity.

        Args:
            internal_entity_type: e.g. ``'contact'``
            internal_entity_id: Internal entity ID.
            external_system: e.g. ``'immich'``
            external_entity_type: Optional filter for external entity type.

        Returns:
            Dictionary with reference data or ``None``.
        """
        if external_entity_type:
            query = text("""
                SELECT id, internal_entity_type, internal_entity_id,
                       external_system, external_entity_type,
                       external_entity_id, reference_data,
                       created_at, updated_at
                FROM external_references
                WHERE external_system = :external_system
                  AND internal_entity_type = :internal_entity_type
                  AND internal_entity_id = :internal_entity_id
                  AND external_entity_type = :external_entity_type
                ORDER BY id
                LIMIT 1
            """)
            params: dict[str, Any] = {
                "external_system": external_system,
                "internal_entity_type": internal_entity_type,
                "internal_entity_id": internal_entity_id,
                "external_entity_type": external_entity_type,
            }
        else:
            query = text("""
                SELECT id, internal_entity_type, internal_entity_id,
                       external_system, external_entity_type,
                       external_entity_id, reference_data,
                       created_at, updated_at
                FROM external_references
                WHERE external_system = :external_system
                  AND internal_entity_type = :internal_entity_type
                  AND internal_entity_id = :internal_entity_id
                ORDER BY id
                LIMIT 1
            """)
            params = {
                "external_system": external_system,
                "internal_entity_type": internal_entity_type,
                "internal_entity_id": internal_entity_id,
            }

        result = await self._conn.execute(query, params)
        row = result.fetchone()
        return self._row_to_dict(row) if row else None

    async def find_contact_with_birthday(
        self, contact_id: int
    ) -> dict[str, Any] | None:
        """Fetch a contact's name fields and full-precision birthday.

        Args:
            contact_id: Internal contact ID.

        Returns:
            Dictionary with name and birthday fields, or ``None``.
        """
        query = text("""
            SELECT c.first_name, c.last_name, c.middle_name,
                   d.year, d.month, d.day
            FROM contacts c
            LEFT JOIN contact_important_dates d
              ON c.id = d.contact_id AND d.date_type = 'birthday' AND d.precision = 'full'
            WHERE c.id = :contact_id
        """)
        result = await self._conn.execute(query, {"contact_id": contact_id})
        row = result.fetchone()
        if not row:
            return None

        return {
            "first_name": row.first_name,
            "last_name": row.last_name,
            "middle_name": row.middle_name,
            "year": row.year,
            "month": row.month,
            "day": row.day,
        }

    async def get_immich_person_id(self, contact_id: int) -> str | None:
        """Look up the Immich person ID linked to a contact.

        Args:
            contact_id: Internal contact ID.

        Returns:
            The Immich person ID string, or ``None`` if unlinked.
        """
        query = text("""
            SELECT external_entity_id
            FROM external_references
            WHERE internal_entity_type = 'contact'
              AND internal_entity_id = :contact_id
              AND external_system = 'immich'
              AND external_entity_type = 'person'
            LIMIT 1
        """)
        result = await self._conn.execute(query, {"contact_id": contact_id})
        row = result.fetchone()
        return row.external_entity_id if row else None

    async def get_contact_ids_by_immich_person_ids(
        self, person_ids: list[str]
    ) -> dict[str, int]:
        """Resolve Immich person ids to linked local contact ids.

        Used for album participant detection: tagged Immich people are mapped to
        the contacts they were linked to during contact sync. Person ids without
        a contact link are simply omitted from the result, so unresolved people
        never produce orphan participants.

        Args:
            person_ids: Immich person UUIDs to resolve.

        Returns:
            A mapping of ``{person_id: contact_id}`` for the linked people.
        """
        if not person_ids:
            return {}

        query = text("""
            SELECT external_entity_id, internal_entity_id
            FROM external_references
            WHERE external_system = 'immich'
              AND external_entity_type = 'person'
              AND internal_entity_type = 'contact'
              AND external_entity_id = ANY(:person_ids)
        """)
        result = await self._conn.execute(query, {"person_ids": person_ids})
        return {
            row.external_entity_id: row.internal_entity_id for row in result.fetchall()
        }

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a database row to a dictionary."""
        return {
            "id": row.id,
            "internal_entity_type": row.internal_entity_type,
            "internal_entity_id": row.internal_entity_id,
            "external_system": row.external_system,
            "external_entity_type": row.external_entity_type,
            "external_entity_id": row.external_entity_id,
            "reference_data": row.reference_data,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
