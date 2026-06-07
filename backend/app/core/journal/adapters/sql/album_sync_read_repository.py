"""Read-only access to Immich album link data for PHOTO_ALBUM journals.

ITER11-004 Phase 1: PHOTO_ALBUM is integration-managed. A journal is a
PHOTO_ALBUM when it has a ``sync_metadata`` row with
``integration_source='immich_album'``. Album display data (name, web URL, asset
count) is sourced from that row and the album ``external_references`` record
rather than a dedicated data table. There is no write path — albums are created
and updated by Immich album sync.
"""

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

INTEGRATION_SOURCE = "immich_album"


class AlbumSyncReadRepository:
    """Reads (and cleans up) Immich album links for PHOTO_ALBUM journals."""

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize with a database connection."""
        self.conn = conn

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
        if row.reference_data:
            ref = json.loads(row.reference_data)
            if ref.get("album_name"):
                data["album_name"] = ref["album_name"]
            if ref.get("album_url"):
                data["album_url"] = ref["album_url"]
            if ref.get("asset_count") is not None:
                data["asset_count"] = ref["asset_count"]
        return data

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
