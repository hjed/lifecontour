"""
External Reference Service for managing links between internal and external entities.

Provides operations for creating, updating, and querying external references
that link internal entities (like contacts) to external system entities.
"""

from dataclasses import asdict, dataclass
from typing import Any

import structlog
from core_shared.models.external_reference import ExternalReference
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = structlog.get_logger()


class ExternalReferenceError(Exception):
    """Base exception for external reference service errors."""

    pass


@dataclass(frozen=True)
class ExternalReferenceCollision:
    """A same-service external link that could not simply carry over on merge.

    Both the source and the surviving contact were linked to ``external_system``,
    each to a distinct remote record. The survivor's link is kept and the source's
    local row is removed; this records the source's remote id (alongside the
    survivor's) so the integration workers can reconcile the remote records.
    """

    external_system: str
    external_entity_type: str
    source_external_id: str
    survivor_external_id: str

    def as_dict(self) -> dict[str, str]:
        """Serialise for inclusion in the ``ContactMerged`` event payload."""
        return asdict(self)


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
            ExternalReferenceError: If creation fails
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
                raise ExternalReferenceError("Failed to create external reference")

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
        reference_data: str | None = None,
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

    async def upsert_contact_reference(
        self,
        contact_id: int,
        external_system: str,
        external_entity_type: str,
        external_entity_id: str,
    ) -> ExternalReference:
        """Find an existing contact external reference and update it, or create a new one.

        Uses ``ORDER BY id LIMIT 1`` for deterministic row selection when
        multiple references exist for the same contact, system, and entity type.

        Args:
            contact_id: Internal contact ID.
            external_system: External system name (e.g. 'immich').
            external_entity_type: External entity type (e.g. 'person').
            external_entity_id: External entity ID to link.

        Returns:
            Created or updated ExternalReference.
        """
        # Scoped lookup: filter by entity type and use ORDER BY for determinism
        query = text("""
            SELECT id, internal_entity_type, internal_entity_id, external_system,
                   external_entity_type, external_entity_id, reference_data,
                   created_at, updated_at
            FROM external_references
            WHERE internal_entity_type = 'contact'
              AND internal_entity_id = :contact_id
              AND external_system = :external_system
              AND external_entity_type = :external_entity_type
            ORDER BY id
            LIMIT 1
        """)
        result = await self.connection.execute(
            query,
            {
                "contact_id": contact_id,
                "external_system": external_system,
                "external_entity_type": external_entity_type,
            },
        )
        row = result.fetchone()

        if row:
            updated = await self.update_external_reference(
                reference_id=row.id,
                external_entity_id=external_entity_id,
            )
            if updated:
                return updated
            # Fall through to create if update returned None (shouldn't happen)

        return await self.create_external_reference(
            internal_entity_type="contact",
            internal_entity_id=contact_id,
            external_system=external_system,
            external_entity_type=external_entity_type,
            external_entity_id=external_entity_id,
        )

    async def contact_exists(self, contact_id: int) -> bool:
        """Check if a contact with the given ID exists.

        Args:
            contact_id: Contact ID to check.

        Returns:
            True if the contact exists, False otherwise.
        """
        query = text("SELECT id FROM contacts WHERE id = :contact_id")
        result = await self.connection.execute(query, {"contact_id": contact_id})
        return result.first() is not None

    async def repoint_contact_references(
        self,
        source_id: int,
        survivor_id: int,
        transaction: AsyncConnection,
    ) -> list[ExternalReferenceCollision]:
        """Re-point a source contact's external links onto the survivor on merge.

        Runs inline in the merge transaction (a local re-point, never a remote
        call) so a deleted source never leaves resolvable-looking orphans — the
        ``external_references`` / ``sync_metadata`` tables have no
        ``ON DELETE CASCADE``.

        For each of the source's contact ``external_references``:

        - **Different service** (the survivor has no link for that
          ``external_system``): the reference, and its matching ``sync_metadata``
          row, are re-pointed onto the survivor.
        - **Same service** (the survivor already has a link for that
          ``external_system``): the survivor's link is kept; the source's
          reference and its ``sync_metadata`` row are deleted, and the collision
          is returned so the caller can hand the source's remote id to the
          integration workers for remote reconciliation.

        ``sync_metadata`` is keyed to each reference by ``(integration_source,
        external_id)`` so only the rows backing a contact's external link are
        touched — a journal sync row that merely shares the source's integer id is
        left alone.

        Args:
            source_id: The contact being absorbed (and then deleted).
            survivor_id: The surviving contact that keeps its id.
            transaction: The merge transaction's connection.

        Returns:
            One ``ExternalReferenceCollision`` per same-service collision.
        """
        # Collision detection reads the canonical link store (sync_metadata).
        survivor_result = await transaction.execute(
            text(
                """
                SELECT integration_source AS external_system,
                       external_id AS external_entity_id
                FROM sync_metadata
                WHERE internal_entity_type = 'contact'
                  AND internal_id = :survivor_id
                """
            ),
            {"survivor_id": survivor_id},
        )
        survivor_external_id_by_system = {
            row.external_system: row.external_entity_id
            for row in survivor_result.fetchall()
        }

        source_result = await transaction.execute(
            text(
                """
                SELECT integration_source AS external_system,
                       external_entity_type,
                       external_id AS external_entity_id
                FROM sync_metadata
                WHERE internal_entity_type = 'contact'
                  AND internal_id = :source_id
                """
            ),
            {"source_id": source_id},
        )
        source_refs = source_result.fetchall()

        collisions: list[ExternalReferenceCollision] = []
        for ref in source_refs:
            survivor_external_id = survivor_external_id_by_system.get(
                ref.external_system
            )
            # Both link tables are still dual-written, so keep them consistent.
            # Key the legacy external_references row by its identity columns since
            # the read no longer carries its surrogate id.
            link_params = {
                "source_id": source_id,
                "survivor_id": survivor_id,
                "integration_source": ref.external_system,
                "external_id": ref.external_entity_id,
            }
            if survivor_external_id is None:
                # Different service — carry the link and its sync row over.
                await transaction.execute(
                    text(
                        """
                        UPDATE external_references
                        SET internal_entity_id = :survivor_id, updated_at = now()
                        WHERE internal_entity_type = 'contact'
                          AND internal_entity_id = :source_id
                          AND external_system = :integration_source
                          AND external_entity_id = :external_id
                        """
                    ),
                    link_params,
                )
                await transaction.execute(
                    text(
                        """
                        UPDATE sync_metadata
                        SET internal_id = :survivor_id, updated_at = now()
                        WHERE internal_id = :source_id
                          AND integration_source = :integration_source
                          AND external_id = :external_id
                        """
                    ),
                    link_params,
                )
            else:
                # Same service — keep the survivor's link, drop the source's, and
                # record the collision for remote reconciliation by the workers.
                collisions.append(
                    ExternalReferenceCollision(
                        external_system=ref.external_system,
                        external_entity_type=ref.external_entity_type,
                        source_external_id=ref.external_entity_id,
                        survivor_external_id=survivor_external_id,
                    )
                )
                await transaction.execute(
                    text(
                        """
                        DELETE FROM external_references
                        WHERE internal_entity_type = 'contact'
                          AND internal_entity_id = :source_id
                          AND external_system = :integration_source
                          AND external_entity_id = :external_id
                        """
                    ),
                    link_params,
                )
                await transaction.execute(
                    text(
                        """
                        DELETE FROM sync_metadata
                        WHERE internal_id = :source_id
                          AND integration_source = :integration_source
                          AND external_id = :external_id
                        """
                    ),
                    link_params,
                )

        if collisions:
            logger.info(
                "Recorded same-service external-reference collisions on merge",
                source_id=source_id,
                survivor_id=survivor_id,
                collision_systems=[c.external_system for c in collisions],
            )
        return collisions
