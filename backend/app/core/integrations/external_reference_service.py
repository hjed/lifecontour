"""
External Reference Service for managing links between internal and external entities.

Provides operations for creating, updating, and querying external references
that link internal entities (like contacts) to external system entities.
"""

from typing import Any

import structlog
from core_shared.models.external_reference import ExternalReference
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = structlog.get_logger()


class ExternalReferenceService:
    """
    Service for managing external references between internal and external entities.

    Handles the creation and management of links between our internal entities
    (contacts, journal entries, etc.) and external system entities.
    """

    def __init__(self, connection: AsyncConnection):
        """
        Initialize the external reference service.

        Args:
            connection: Database connection for operations
        """
        self.connection = connection

    async def create_external_reference(
        self,
        internal_entity_type: str,
        internal_entity_id: int,
        external_system: str,
        external_entity_type: str,
        external_entity_id: str,
        reference_data: str | None = None,
    ) -> ExternalReference:
        """
        Create an external reference linking internal and external entities.

        Args:
            internal_entity_type: Type of internal entity (e.g., 'contact')
            internal_entity_id: ID of the internal entity
            external_system: Name of external system (e.g., 'google')
            external_entity_type: Type of external entity (e.g., 'person')
            external_entity_id: External system's ID for the entity
            reference_data: Optional additional reference data

        Returns:
            Created ExternalReference instance

        Raises:
            Exception: If creation fails
        """
        logger.info(
            "Creating external reference",
            internal_entity_type=internal_entity_type,
            internal_entity_id=internal_entity_id,
            external_system=external_system,
            external_entity_id=external_entity_id,
        )

        try:
            # Insert the external reference
            query = text(
                """
                INSERT INTO external_references
                (internal_entity_type, internal_entity_id, external_system,
                 external_entity_type, external_entity_id, reference_data)
                VALUES (:internal_entity_type, :internal_entity_id, :external_system,
                        :external_entity_type, :external_entity_id, :reference_data)
                RETURNING id, created_at, updated_at
                """
            )

            result = await self.connection.execute(
                query,
                {
                    "internal_entity_type": internal_entity_type,
                    "internal_entity_id": internal_entity_id,
                    "external_system": external_system,
                    "external_entity_type": external_entity_type,
                    "external_entity_id": external_entity_id,
                    "reference_data": reference_data,
                },
            )

            row = result.fetchone()
            if not row:
                raise Exception("Failed to create external reference")

            logger.info(
                "Successfully created external reference",
                reference_id=row.id,
                internal_entity_type=internal_entity_type,
                internal_entity_id=internal_entity_id,
                external_system=external_system,
                external_entity_id=external_entity_id,
            )

            # Return the created reference (simplified for now)
            return ExternalReference(
                id=row.id,
                internal_entity_type=internal_entity_type,
                internal_entity_id=internal_entity_id,
                external_system=external_system,
                external_entity_type=external_entity_type,
                external_entity_id=external_entity_id,
                reference_data=reference_data,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

        except Exception as e:
            logger.error(
                "Failed to create external reference",
                internal_entity_type=internal_entity_type,
                internal_entity_id=internal_entity_id,
                external_system=external_system,
                external_entity_id=external_entity_id,
                error=str(e),
            )
            raise

    async def find_external_reference(
        self,
        internal_entity_type: str,
        internal_entity_id: int,
        external_system: str,
    ) -> ExternalReference | None:
        """
        Find an external reference for an internal entity.

        Args:
            internal_entity_type: Type of internal entity
            internal_entity_id: ID of the internal entity
            external_system: Name of external system

        Returns:
            ExternalReference if found, None otherwise
        """
        query = text(
            """
            SELECT id, internal_entity_type, internal_entity_id, external_system,
                   external_entity_type, external_entity_id, reference_data,
                   created_at, updated_at
            FROM external_references
            WHERE internal_entity_type = :internal_entity_type
            AND internal_entity_id = :internal_entity_id
            AND external_system = :external_system
            """
        )

        result = await self.connection.execute(
            query,
            {
                "internal_entity_type": internal_entity_type,
                "internal_entity_id": internal_entity_id,
                "external_system": external_system,
            },
        )

        row = result.fetchone()
        if not row:
            return None

        return ExternalReference(
            id=row.id,
            internal_entity_type=row.internal_entity_type,
            internal_entity_id=row.internal_entity_id,
            external_system=row.external_system,
            external_entity_type=row.external_entity_type,
            external_entity_id=row.external_entity_id,
            reference_data=row.reference_data,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def update_external_reference(
        self,
        reference_id: int,
        external_entity_id: str | None = None,
        reference_data: dict[str, Any] | None = None,
    ) -> ExternalReference | None:
        """
        Update an existing external reference.

        Args:
            reference_id: ID of the external reference to update
            external_entity_id: New external entity ID (optional)
            reference_data: New reference data (optional)

        Returns:
            Updated ExternalReference if found, None otherwise
        """
        # Build parameterized update query to prevent SQL injection
        params: dict[str, Any] = {"reference_id": reference_id}

        # Determine which fields to update based on provided parameters
        update_external_entity_id = external_entity_id is not None
        update_reference_data = reference_data is not None

        if update_external_entity_id:
            params["external_entity_id"] = external_entity_id

        if update_reference_data:
            params["reference_data"] = reference_data

        if not (update_external_entity_id or update_reference_data):
            # No fields to update
            return await self._get_external_reference_by_id(reference_id)

        # Build query with conditional SET clauses using CASE statements
        # This avoids string concatenation in SQL construction
        query_parts = ["UPDATE external_references SET"]
        set_clauses = []

        if update_external_entity_id:
            set_clauses.append("external_entity_id = :external_entity_id")
        if update_reference_data:
            set_clauses.append("reference_data = :reference_data")

        # Always update timestamp
        set_clauses.append("updated_at = now()")

        query_parts.append(", ".join(set_clauses))
        query_parts.append("WHERE id = :reference_id")
        query_parts.append("""RETURNING id, internal_entity_type, internal_entity_id, external_system,
                      external_entity_type, external_entity_id, reference_data,
                      created_at, updated_at""")

        query = text(" ".join(query_parts))

        result = await self.connection.execute(query, params)
        row = result.fetchone()

        if not row:
            return None

        return ExternalReference(
            id=row.id,
            internal_entity_type=row.internal_entity_type,
            internal_entity_id=row.internal_entity_id,
            external_system=row.external_system,
            external_entity_type=row.external_entity_type,
            external_entity_id=row.external_entity_id,
            reference_data=row.reference_data,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _get_external_reference_by_id(
        self, reference_id: int
    ) -> ExternalReference | None:
        """Get an external reference by ID."""
        query = text(
            """
            SELECT id, internal_entity_type, internal_entity_id, external_system,
                   external_entity_type, external_entity_id, reference_data,
                   created_at, updated_at
            FROM external_references
            WHERE id = :reference_id
            """
        )

        result = await self.connection.execute(query, {"reference_id": reference_id})
        row = result.fetchone()

        if not row:
            return None

        return ExternalReference(
            id=row.id,
            internal_entity_type=row.internal_entity_type,
            internal_entity_id=row.internal_entity_id,
            external_system=row.external_system,
            external_entity_type=row.external_entity_type,
            external_entity_id=row.external_entity_id,
            reference_data=row.reference_data,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_external_id(
        self, external_system: str, external_entity_id: str
    ) -> ExternalReference | None:
        """
        Find external reference by external entity ID and system.

        Args:
            external_system: External system name
            external_entity_id: External entity ID

        Returns:
            ExternalReference if found, None otherwise
        """
        logger.debug(
            "Finding external reference by external ID",
            external_system=external_system,
            external_entity_id=external_entity_id,
        )

        try:
            query = text("""
                SELECT id, internal_entity_type, internal_entity_id, external_system,
                       external_entity_type, external_entity_id, reference_data,
                       created_at, updated_at
                FROM external_references
                WHERE external_system = :external_system
                AND external_entity_id = :external_entity_id
            """)

            result = await self.connection.execute(
                query,
                {
                    "external_system": external_system,
                    "external_entity_id": external_entity_id,
                },
            )
            row = result.fetchone()

            if row:
                return ExternalReference(
                    id=row.id,
                    internal_entity_type=row.internal_entity_type,
                    internal_entity_id=row.internal_entity_id,
                    external_system=row.external_system,
                    external_entity_type=row.external_entity_type,
                    external_entity_id=row.external_entity_id,
                    reference_data=row.reference_data,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )

            return None

        except Exception as e:
            logger.error(
                "Failed to find external reference by external ID",
                error=str(e),
                external_system=external_system,
                external_entity_id=external_entity_id,
            )
            raise
