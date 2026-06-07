"""Persistence for Immich album links on PHOTO_ALBUM journals.

ITER11-004 Phase 1: PHOTO_ALBUM is integration-managed. A journal is a
PHOTO_ALBUM when it has a ``sync_metadata`` row with
``integration_source='immich_album'``. Album display data (name, web URL, asset
count) is sourced from that row and the album ``external_references`` record
rather than a dedicated data table.

This repository owns all SQL for the album ``external_references`` link: the
journal API read path, the album-sync link find/upsert used by
``ImmichAlbumOutboxEventProcessor``, and cleanup on journal deletion. Album
content itself is only ever written by Immich album sync.
"""

import json
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = structlog.get_logger()

INTEGRATION_SOURCE = "immich_album"
EXTERNAL_SYSTEM = "immich"
EXTERNAL_ENTITY_TYPE = "album"
INTERNAL_ENTITY_TYPE = "journal"


class AlbumSyncReadRepository:
    """Reads, links, and cleans up Immich album links for PHOTO_ALBUM journals."""

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize with a database connection."""
        self.conn = conn

    async def find_link(
        self, album_id: str, journal_id: int | None = None
    ) -> Any | None:
        """Find the album ``external_references`` row for ``album_id``.

        When ``journal_id`` is given, the lookup is constrained to the reference
        pointing at that journal, so merge protection compares against the right
        anchor even if multiple references exist for the same album.
        """
        result = await self.conn.execute(
            text("""
                SELECT id, internal_entity_id, updated_at
                FROM external_references
                WHERE external_system = :external_system
                  AND external_entity_type = :external_entity_type
                  AND external_entity_id = :external_entity_id
                  AND internal_entity_type = :internal_entity_type
                  AND (
                      CAST(:journal_id AS INTEGER) IS NULL
                      OR internal_entity_id = :journal_id
                  )
                ORDER BY id DESC
                LIMIT 1
            """),
            {
                "external_system": EXTERNAL_SYSTEM,
                "external_entity_type": EXTERNAL_ENTITY_TYPE,
                "external_entity_id": album_id,
                "internal_entity_type": INTERNAL_ENTITY_TYPE,
                "journal_id": journal_id,
            },
        )
        return result.fetchone()

    async def upsert_link(
        self,
        journal_id: int,
        album_id: str,
        reference_data: dict[str, Any],
        *,
        bump_anchor: bool,
    ) -> None:
        """Insert or update the ``(journal, album)`` external_reference link.

        Scoped to this specific journal so stray references for the same album
        are never repointed or duplicated. ``updated_at`` (the merge-protection
        anchor) is only advanced when ``bump_anchor`` is True; when False the
        existing anchor is preserved so a locally edited journal stays protected.
        """
        now = datetime.now(UTC)
        params: dict[str, Any] = {
            "journal_id": journal_id,
            "reference_data": json.dumps(reference_data),
            "external_system": EXTERNAL_SYSTEM,
            "external_entity_type": EXTERNAL_ENTITY_TYPE,
            "external_entity_id": album_id,
            "internal_entity_type": INTERNAL_ENTITY_TYPE,
            "now": now,
            "bump_anchor": bump_anchor,
        }

        # A SQL CASE keeps the conditional anchor parametrised (no f-strings).
        result = await self.conn.execute(
            text("""
                UPDATE external_references
                SET reference_data = :reference_data,
                    updated_at = CASE
                        WHEN :bump_anchor THEN :now ELSE updated_at
                    END
                WHERE external_system = :external_system
                  AND external_entity_type = :external_entity_type
                  AND external_entity_id = :external_entity_id
                  AND internal_entity_type = :internal_entity_type
                  AND internal_entity_id = :journal_id
            """),
            params,
        )
        if result.rowcount == 0:
            await self.conn.execute(
                text("""
                    INSERT INTO external_references
                        (internal_entity_type, internal_entity_id, external_system,
                         external_entity_type, external_entity_id, reference_data,
                         created_at, updated_at)
                    VALUES
                        (:internal_entity_type, :journal_id, :external_system,
                         :external_entity_type, :external_entity_id,
                         :reference_data, :now, :now)
                """),
                params,
            )

    async def find_by_journal_id(self, journal_id: int) -> dict[str, Any] | None:
        """Return album display data for a journal, or None if not an album.

        The returned dict matches ``PhotoAlbumDataSchema`` fields:
        ``immich_album_id`` plus optional ``album_name``, ``album_url`` and
        ``asset_count`` taken from the album external reference's reference_data.
        """
        result = await self.conn.execute(
            text("""
                SELECT sm.external_id AS immich_album_id,
                       er.reference_data AS reference_data
                FROM sync_metadata sm
                LEFT JOIN external_references er
                    ON er.external_system = 'immich'
                    AND er.external_entity_type = 'album'
                    AND er.external_entity_id = sm.external_id
                    AND er.internal_entity_type = 'journal'
                    AND er.internal_entity_id = sm.internal_id
                WHERE sm.integration_source = :source
                  AND sm.internal_id = :journal_id
                LIMIT 1
            """),
            {"source": INTEGRATION_SOURCE, "journal_id": journal_id},
        )
        row = result.fetchone()
        if row is None:
            return None

        data: dict[str, Any] = {"immich_album_id": row.immich_album_id}
        ref = self._decode_reference_data(row.reference_data, journal_id)
        if ref.get("album_name"):
            data["album_name"] = ref["album_name"]
        if ref.get("album_url"):
            data["album_url"] = ref["album_url"]
        if ref.get("asset_count") is not None:
            data["asset_count"] = ref["asset_count"]
        return data

    @staticmethod
    def _decode_reference_data(
        reference_data: str | None, journal_id: int
    ) -> dict[str, Any]:
        """Decode the album reference_data JSON, tolerating malformed rows.

        A single corrupted ``external_references.reference_data`` value must not
        turn a journal fetch/list into a 500; fall back to the bare album id.
        """
        if not reference_data:
            return {}
        try:
            # json.JSONDecodeError is a subclass of ValueError; reference_data is
            # a non-empty str by here, so a TypeError cannot occur.
            decoded = json.loads(reference_data)
        except ValueError:
            logger.warning(
                "Malformed album reference_data; ignoring",
                journal_id=journal_id,
            )
            return {}
        if not isinstance(decoded, dict):
            logger.warning(
                "Unexpected album reference_data shape; ignoring",
                journal_id=journal_id,
            )
            return {}
        return decoded

    async def delete(self, journal_id: int) -> None:
        """Remove a journal's album sync metadata and external reference.

        Called when a journal is deleted so album links do not outlive the
        journal they belonged to.
        """
        await self.conn.execute(
            text("""
                DELETE FROM external_references
                WHERE internal_entity_type = 'journal'
                  AND internal_entity_id = :journal_id
                  AND external_system = 'immich'
                  AND external_entity_type = 'album'
            """),
            {"journal_id": journal_id},
        )
        await self.conn.execute(
            text("""
                DELETE FROM sync_metadata
                WHERE integration_source = :source
                  AND internal_id = :journal_id
            """),
            {"source": INTEGRATION_SOURCE, "journal_id": journal_id},
        )
