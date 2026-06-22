"""
SQL repository for SyncMetadata with SELECT FOR UPDATE locking support.

This repository implements production-grade resilience patterns:
1. SELECT FOR UPDATE locking for concurrent sync operations
2. Version hash-based idempotency checks
3. Atomic upsert operations
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from core_shared.models.sync_metadata import SyncMetadata, SyncStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class IntegrationLinkCollision:
    """A same-service integration link that could not simply carry over on merge.

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


class SyncMetadataRepository:
    """Repository for managing sync metadata with concurrency control."""

    def __init__(self, conn: AsyncConnection):
        """
        Initialize the repository.

        Args:
            conn: Database connection (must be within a transaction for locking)
        """
        self.conn = conn

    async def find_and_lock(
        self, integration_source: str, external_id: str
    ) -> SyncMetadata | None:
        """
        Find sync metadata and acquire an exclusive lock using SELECT FOR UPDATE.

        This prevents concurrent sync operations on the same entity.
        The lock is held until the transaction commits or rolls back.

        Args:
            integration_source: Integration source (e.g., 'google')
            external_id: External entity ID

        Returns:
            SyncMetadata if found, None otherwise
        """
        query = text("""
            SELECT id, internal_id, internal_uuid, integration_source, external_id,
                   last_synced_at, version_hash, sync_status,
                   error_message, retry_count, created_at, updated_at
            FROM sync_metadata
            WHERE integration_source = :integration_source
              AND external_id = :external_id
            FOR UPDATE
        """)

        result = await self.conn.execute(
            query,
            {
                "integration_source": integration_source,
                "external_id": external_id,
            },
        )
        row = result.fetchone()

        if not row:
            return None

        return SyncMetadata(
            id=row.id,
            internal_id=row.internal_id,
            internal_uuid=row.internal_uuid,
            integration_source=row.integration_source,
            external_id=row.external_id,
            last_synced_at=row.last_synced_at,
            version_hash=row.version_hash,
            sync_status=row.sync_status,
            error_message=row.error_message,
            retry_count=row.retry_count,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_external_id(
        self, integration_source: str, external_id: str
    ) -> SyncMetadata | None:
        """
        Find sync metadata without locking (for read-only operations).

        Args:
            integration_source: Integration source (e.g., 'google')
            external_id: External entity ID

        Returns:
            SyncMetadata if found, None otherwise
        """
        query = text("""
            SELECT id, internal_id, internal_uuid, integration_source, external_id,
                   last_synced_at, version_hash, sync_status,
                   error_message, retry_count, created_at, updated_at
            FROM sync_metadata
            WHERE integration_source = :integration_source
              AND external_id = :external_id
        """)

        result = await self.conn.execute(
            query,
            {
                "integration_source": integration_source,
                "external_id": external_id,
            },
        )
        row = result.fetchone()

        if not row:
            return None

        return SyncMetadata(
            id=row.id,
            internal_id=row.internal_id,
            internal_uuid=row.internal_uuid,
            integration_source=row.integration_source,
            external_id=row.external_id,
            last_synced_at=row.last_synced_at,
            version_hash=row.version_hash,
            sync_status=row.sync_status,
            error_message=row.error_message,
            retry_count=row.retry_count,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def upsert(
        self,
        integration_source: str,
        external_id: str,
        version_hash: str,
        internal_id: int | None = None,
        internal_uuid: str | None = None,
        sync_status: SyncStatus = SyncStatus.SUCCESS,
        error_message: str | None = None,
        internal_entity_type: str | None = None,
        external_entity_type: str | None = None,
        reference_data: str | None = None,
    ) -> SyncMetadata:
        """
        Insert or update sync metadata atomically.

        Args:
            integration_source: Integration source
            external_id: External entity ID
            version_hash: Version hash for change detection
            internal_id: Internal entity ID (integer)
            internal_uuid: Internal entity ID (UUID string)
            sync_status: Sync status
            error_message: Error message if failed
            internal_entity_type: Internal entity type (e.g. 'contact', 'journal')
            external_entity_type: External entity type (e.g. 'person', 'album')
            reference_data: Additional link metadata as a JSON string

        Returns:
            Created or updated SyncMetadata
        """
        now = datetime.now(UTC)

        # The link columns use COALESCE on conflict so a writer that does not
        # supply them (e.g. an integration worker still on the old code path)
        # never clears values populated by another writer or the backfill.
        query = text("""
            INSERT INTO sync_metadata
                (internal_id, internal_uuid, integration_source, external_id, last_synced_at,
                 version_hash, sync_status, error_message, retry_count,
                 internal_entity_type, external_entity_type, reference_data,
                 created_at, updated_at)
            VALUES
                (:internal_id, :internal_uuid, :integration_source, :external_id, :last_synced_at,
                 :version_hash, :sync_status, :error_message, 0,
                 :internal_entity_type, :external_entity_type, :reference_data,
                 :created_at, :updated_at)
            ON CONFLICT (integration_source, external_id)
            DO UPDATE SET
                internal_id = EXCLUDED.internal_id,
                internal_uuid = EXCLUDED.internal_uuid,
                last_synced_at = EXCLUDED.last_synced_at,
                version_hash = EXCLUDED.version_hash,
                sync_status = EXCLUDED.sync_status,
                error_message = EXCLUDED.error_message,
                retry_count = CASE
                    WHEN EXCLUDED.sync_status = 'success' THEN 0
                    ELSE sync_metadata.retry_count + 1
                END,
                internal_entity_type = COALESCE(
                    EXCLUDED.internal_entity_type, sync_metadata.internal_entity_type
                ),
                external_entity_type = COALESCE(
                    EXCLUDED.external_entity_type, sync_metadata.external_entity_type
                ),
                reference_data = COALESCE(
                    EXCLUDED.reference_data, sync_metadata.reference_data
                ),
                updated_at = EXCLUDED.updated_at
            RETURNING id, internal_id, internal_uuid, integration_source, external_id,
                      last_synced_at, version_hash, sync_status,
                      error_message, retry_count, internal_entity_type,
                      external_entity_type, reference_data, created_at, updated_at
        """)

        result = await self.conn.execute(
            query,
            {
                "internal_id": internal_id,
                "internal_uuid": internal_uuid,
                "integration_source": integration_source,
                "external_id": external_id,
                "last_synced_at": now,
                "version_hash": version_hash,
                "sync_status": sync_status.value,
                "error_message": error_message,
                "internal_entity_type": internal_entity_type,
                "external_entity_type": external_entity_type,
                "reference_data": reference_data,
                "created_at": now,
                "updated_at": now,
            },
        )
        row = result.fetchone()

        if not row:
            raise RuntimeError("Failed to upsert sync metadata")

        return SyncMetadata(
            id=row.id,
            internal_id=row.internal_id,
            internal_uuid=row.internal_uuid,
            integration_source=row.integration_source,
            external_id=row.external_id,
            last_synced_at=row.last_synced_at,
            version_hash=row.version_hash,
            sync_status=row.sync_status,
            error_message=row.error_message,
            retry_count=row.retry_count,
            internal_entity_type=row.internal_entity_type,
            external_entity_type=row.external_entity_type,
            reference_data=row.reference_data,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def update_reference_data(
        self,
        integration_source: str,
        external_id: str,
        reference_data: str,
    ) -> None:
        """Update only the ``reference_data`` of an existing link.

        Used for link metadata that changes independently of the entity's
        version (e.g. a contact's ``synced_tags``): ``version_hash`` and the
        identity columns are deliberately left untouched so this write never
        looks like a content change to the next sync's ``should_sync`` check.

        A no-op when no row matches ``(integration_source, external_id)``.

        Args:
            integration_source: Integration source (e.g. 'google').
            external_id: External entity ID.
            reference_data: New reference data as a JSON string.
        """
        query = text("""
            UPDATE sync_metadata
            SET reference_data = :reference_data, updated_at = :now
            WHERE integration_source = :integration_source
              AND external_id = :external_id
        """)
        await self.conn.execute(
            query,
            {
                "reference_data": reference_data,
                "now": datetime.now(UTC),
                "integration_source": integration_source,
                "external_id": external_id,
            },
        )

    async def upsert_contact_link(
        self,
        contact_id: int,
        external_system: str,
        external_entity_type: str,
        external_entity_id: str,
    ) -> None:
        """Link a contact to an external entity in the canonical link store.

        Writes the ``(integration_source, external_id) → contact`` link onto
        ``sync_metadata``, which dedups on ``UNIQUE(integration_source,
        external_id)``. ``version_hash`` is left empty so the next sync
        re-validates the entity's content. The link columns use ``COALESCE`` on
        conflict (see :meth:`upsert`), so re-linking the same external id never
        clears existing metadata.

        Args:
            contact_id: Internal contact ID.
            external_system: External system name (e.g. 'immich').
            external_entity_type: External entity type (e.g. 'person').
            external_entity_id: External entity ID to link.
        """
        await self.upsert(
            integration_source=external_system,
            external_id=external_entity_id,
            version_hash="",
            internal_id=contact_id,
            internal_entity_type="contact",
            external_entity_type=external_entity_type,
        )

    async def repoint_contact_links(
        self,
        source_id: int,
        survivor_id: int,
        transaction: AsyncConnection,
    ) -> list[IntegrationLinkCollision]:
        """Re-point a source contact's external links onto the survivor on merge.

        Runs inline in the merge transaction (a local re-point, never a remote
        call) so a deleted source never leaves resolvable-looking orphans in the
        canonical ``sync_metadata`` link store, which has no ``ON DELETE
        CASCADE``.

        For each of the source's contact ``sync_metadata`` links:

        - **Different service** (the survivor has no link for that
          ``integration_source``): the ``sync_metadata`` row is re-pointed onto
          the survivor.
        - **Same service** (the survivor already has a link for that
          ``integration_source``): the survivor's link is kept; the source's
          ``sync_metadata`` row is deleted, and the collision is returned so the
          caller can hand the source's remote id to the integration workers for
          remote reconciliation.

        ``sync_metadata`` is keyed to each reference by ``(integration_source,
        external_id)`` so only the rows backing a contact's external link are
        touched — a journal sync row that merely shares the source's integer id is
        left alone.

        Args:
            source_id: The contact being absorbed (and then deleted).
            survivor_id: The surviving contact that keeps its id.
            transaction: The merge transaction's connection.

        Returns:
            One ``IntegrationLinkCollision`` per same-service collision.
        """
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

        collisions: list[IntegrationLinkCollision] = []
        for ref in source_refs:
            survivor_external_id = survivor_external_id_by_system.get(
                ref.external_system
            )
            link_params = {
                "source_id": source_id,
                "survivor_id": survivor_id,
                "integration_source": ref.external_system,
                "external_id": ref.external_entity_id,
            }
            if survivor_external_id is None:
                # Different service — carry the sync row over to the survivor.
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
                    IntegrationLinkCollision(
                        external_system=ref.external_system,
                        external_entity_type=ref.external_entity_type,
                        source_external_id=ref.external_entity_id,
                        survivor_external_id=survivor_external_id,
                    )
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

        return collisions

    def should_sync(
        self, existing_metadata: SyncMetadata | None, new_version_hash: str
    ) -> bool:
        """
        Determine if sync should proceed based on version hash comparison.

        This implements idempotency - if the version hash matches,
        the data hasn't changed and we can skip the sync.

        Args:
            existing_metadata: Existing sync metadata (if any)
            new_version_hash: New version hash from external system

        Returns:
            True if sync should proceed, False if it can be skipped
        """
        if existing_metadata is None:
            # No existing metadata - this is a new entity, sync it
            return True

        if existing_metadata.version_hash == new_version_hash:
            # Version hash matches - data hasn't changed, skip sync
            return False

        # Version hash differs - data has changed, sync it
        return True
