"""Repository for reading the canonical integration-link store (``sync_metadata``).

ITER15-001 Phase 3 consolidates integration entity links onto ``sync_metadata``.
This repository provides the unified link-lookup reads used by both the backend
consumer and the integration workers, replacing the legacy
``external_references`` reads. Writes remain on the existing upsert paths.

The repository is read-only and intentionally mirrors the constructor and raw-SQL
style of :class:`ExternalReferenceRepository` so it is a drop-in for the link
reads, available to both ``core_shared`` consumers and workers.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = structlog.get_logger(__name__)

# Columns selected for a full link row, shared across the lookups below.
_LINK_COLUMNS = (
    "internal_id, internal_uuid, integration_source, external_id, "
    "internal_entity_type, external_entity_type, reference_data, version_hash"
)


class IntegrationLinkRepository:
    """Read access to integration entity links stored in ``sync_metadata``.

    Args:
        connection: An async SQLAlchemy connection.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self._conn = connection

    async def find_link_by_external(
        self, integration_source: str, external_id: str
    ) -> dict[str, Any] | None:
        """Find a link by ``(integration_source, external_id)``.

        Args:
            integration_source: e.g. ``'google'``, ``'immich'``.
            external_id: The external system's id for the entity.

        Returns:
            A dict describing the link, or ``None`` when no link exists.
        """
        query = text(f"""
            SELECT {_LINK_COLUMNS}
            FROM sync_metadata
            WHERE integration_source = :integration_source
              AND external_id = :external_id
        """)
        result = await self._conn.execute(
            query,
            {
                "integration_source": integration_source,
                "external_id": external_id,
            },
        )
        row = result.fetchone()
        return self._row_to_dict(row) if row else None

    async def find_internal_by_external(
        self, integration_source: str, external_id: str
    ) -> tuple[int | None, str | None, str | None] | None:
        """Resolve the internal identity behind an external link.

        Returns:
            ``(internal_id, internal_uuid, internal_entity_type)`` when a link
            exists, otherwise ``None``.
        """
        link = await self.find_link_by_external(integration_source, external_id)
        if link is None:
            return None
        return (
            link["internal_id"],
            link["internal_uuid"],
            link["internal_entity_type"],
        )

    async def find_external_by_internal(
        self,
        internal_entity_type: str,
        internal_id: int,
        integration_source: str,
        external_entity_type: str | None = None,
    ) -> dict[str, Any] | None:
        """Find the external link for an internal entity.

        Args:
            internal_entity_type: e.g. ``'contact'``.
            internal_id: Internal entity id.
            integration_source: External integration, e.g. ``'immich'``.
            external_entity_type: Optional filter (e.g. ``'person'``).

        Returns:
            A dict describing the link, or ``None``.
        """
        params: dict[str, Any] = {
            "internal_entity_type": internal_entity_type,
            "internal_id": internal_id,
            "integration_source": integration_source,
            "external_entity_type": external_entity_type,
        }
        query = text(f"""
            SELECT {_LINK_COLUMNS}
            FROM sync_metadata
            WHERE integration_source = :integration_source
              AND internal_id = :internal_id
              AND internal_entity_type = :internal_entity_type
              AND (
                  CAST(:external_entity_type AS VARCHAR) IS NULL
                  OR external_entity_type = :external_entity_type
              )
            ORDER BY id
            LIMIT 1
        """)
        result = await self._conn.execute(query, params)
        row = result.fetchone()
        return self._row_to_dict(row) if row else None

    async def get_immich_person_id(self, contact_id: int) -> str | None:
        """Look up the Immich person id linked to a contact.

        Args:
            contact_id: Internal contact id.

        Returns:
            The Immich person id string, or ``None`` if unlinked.
        """
        query = text("""
            SELECT external_id
            FROM sync_metadata
            WHERE integration_source = 'immich'
              AND internal_entity_type = 'contact'
              AND external_entity_type = 'person'
              AND internal_id = :contact_id
            ORDER BY id
            LIMIT 1
        """)
        result = await self._conn.execute(query, {"contact_id": contact_id})
        row = result.fetchone()
        return row.external_id if row else None

    async def get_contact_ids_by_immich_person_ids(
        self, person_ids: list[str]
    ) -> dict[str, int]:
        """Resolve Immich person ids to linked local contact ids.

        Person ids without a contact link are omitted from the result, so
        unresolved people never produce orphan participants.

        Args:
            person_ids: Immich person UUIDs to resolve.

        Returns:
            A mapping of ``{person_id: contact_id}`` for the linked people.
        """
        if not person_ids:
            return {}

        query = text("""
            SELECT external_id, internal_id
            FROM sync_metadata
            WHERE integration_source = 'immich'
              AND internal_entity_type = 'contact'
              AND external_entity_type = 'person'
              AND external_id = ANY(:person_ids)
        """)
        result = await self._conn.execute(query, {"person_ids": person_ids})
        return {row.external_id: row.internal_id for row in result.fetchall()}

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a ``sync_metadata`` link row to a dictionary."""
        return {
            "internal_id": row.internal_id,
            "internal_uuid": row.internal_uuid,
            "integration_source": row.integration_source,
            "external_id": row.external_id,
            "internal_entity_type": row.internal_entity_type,
            "external_entity_type": row.external_entity_type,
            "reference_data": row.reference_data,
            "version_hash": row.version_hash,
        }
