"""Persistence for Immich album links on PHOTO_ALBUM journals.

ITER11-004 Phase 1: PHOTO_ALBUM is integration-managed. A journal is a
PHOTO_ALBUM when it has a ``sync_metadata`` row with
``integration_source='immich_album'``. Album display data (name, web URL, asset
count) is sourced from that row's ``reference_data`` — the canonical link store
(ITER15-001) — rather than a dedicated data table.

This repository owns the SQL for the album link reads (journal API read path)
and the album-sync link find/upsert used by ``ImmichAlbumOutboxEventProcessor``,
plus cleanup on journal deletion. Since ITER15-001 Phase 4 every read and write
keys on ``sync_metadata`` (the canonical link store) — including the
merge-protection anchor (``sync_metadata.updated_at``); ``external_references``
is no longer touched. Album content itself is only ever written by Immich album
sync.
"""

import json
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.sync_metadata_repository import (
    execute_link_write,
)

logger = structlog.get_logger()

INTEGRATION_SOURCE = "immich_album"
EXTERNAL_SYSTEM = "immich"
EXTERNAL_ENTITY_TYPE = "album"
INTERNAL_ENTITY_TYPE = "journal"

# Far-past merge anchor used when a link row is created without applying inbound
# changes, so a locally edited journal stays protected on the next sync.
_UNSYNCED_ANCHOR = datetime(1970, 1, 1, tzinfo=UTC)


class AlbumSyncReadRepository:
    """Reads, links, and cleans up Immich album links for PHOTO_ALBUM journals."""

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize with a database connection."""
        self.conn = conn

    async def find_link(
        self, album_id: str, journal_id: int | None = None
    ) -> Any | None:
        """Find the canonical ``sync_metadata`` album link for ``album_id``.

        Returns the row carrying ``updated_at`` (the merge-protection anchor) and
        ``reference_data``. ``sync_metadata`` is unique on
        ``(integration_source, external_id)`` so an album id maps to a single
        link; ``journal_id`` is accepted as an extra defensive scope so the
        anchor lookup is tied to the journal being updated.
        """
        result = await self.conn.execute(
            text("""
                SELECT id, internal_id AS internal_entity_id,
                       updated_at, reference_data
                FROM sync_metadata
                WHERE integration_source = :integration_source
                  AND external_id = :external_entity_id
                  AND (
                      CAST(:journal_id AS INTEGER) IS NULL
                      OR internal_id = :journal_id
                  )
                ORDER BY id DESC
                LIMIT 1
            """),
            {
                "integration_source": INTEGRATION_SOURCE,
                "external_entity_id": album_id,
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
        version_hash: str,
        bump_anchor: bool,
        user_id: str,
    ) -> None:
        """Upsert the canonical ``(journal, album)`` link in ``sync_metadata``.

        This is the single writer of the album ``sync_metadata`` row: it sets the
        ``version_hash``, the album display ``reference_data`` and the
        merge-protection anchor (``updated_at``).

        ``updated_at`` is the merge anchor. It is only advanced (to ``now``) when
        ``bump_anchor`` is True — i.e. when inbound changes were actually applied.
        When False the existing anchor is preserved (on update) or set to a
        far-past sentinel (on insert), so a locally edited journal stays protected
        and is not re-enabled for overwrite on the next sync.

        Owning ``updated_at`` here (rather than via a separate generic
        ``sync_metadata`` upsert, which would unconditionally bump it) is what
        keeps the anchor meaningful on the consolidated link store.

        The link is stamped with, and keyed by, the journal's owner
        ``user_id``.

        Raises:
            ExternalLinkOwnedByAnotherUserError: Another user links the album.
        """
        now = datetime.now(UTC)
        # The anchor for a freshly inserted row: advancing it (now) is only
        # correct when we applied inbound changes; otherwise keep it in the past.
        insert_anchor = now if bump_anchor else _UNSYNCED_ANCHOR

        # A SQL CASE keeps the conditional anchor parametrised (no f-strings).
        await execute_link_write(
            self.conn,
            text("""
                INSERT INTO sync_metadata
                    (user_id, internal_id, integration_source, external_id,
                     last_synced_at, version_hash, sync_status, retry_count,
                     internal_entity_type, external_entity_type, reference_data,
                     created_at, updated_at)
                VALUES
                    (:user_id, :journal_id, :integration_source, :external_entity_id,
                     :now, :version_hash, 'success', 0,
                     :internal_entity_type, :external_entity_type, :reference_data,
                     :now, :insert_anchor)
                ON CONFLICT (user_id, integration_source, external_id)
                DO UPDATE SET
                    internal_id = EXCLUDED.internal_id,
                    last_synced_at = EXCLUDED.last_synced_at,
                    version_hash = EXCLUDED.version_hash,
                    sync_status = 'success',
                    error_message = NULL,
                    retry_count = 0,
                    internal_entity_type = EXCLUDED.internal_entity_type,
                    external_entity_type = EXCLUDED.external_entity_type,
                    reference_data = EXCLUDED.reference_data,
                    updated_at = CASE
                        WHEN :bump_anchor THEN :now ELSE sync_metadata.updated_at
                    END
            """),
            {
                "user_id": user_id,
                "journal_id": journal_id,
                "integration_source": INTEGRATION_SOURCE,
                "external_entity_id": album_id,
                "now": now,
                "version_hash": version_hash,
                "internal_entity_type": INTERNAL_ENTITY_TYPE,
                "external_entity_type": EXTERNAL_ENTITY_TYPE,
                "reference_data": json.dumps(reference_data),
                "insert_anchor": insert_anchor,
                "bump_anchor": bump_anchor,
            },
            integration_source=INTEGRATION_SOURCE,
            external_id=album_id,
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
                       sm.reference_data AS reference_data
                FROM sync_metadata sm
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
        # The album cover is served on-demand via the backend proxy (the asset
        # thumbnail is not persisted). Expose the proxy URL only when the album
        # actually has a cover asset, so the UI can skip the banner otherwise.
        if ref.get("thumbnail_asset_id"):
            data["cover_url"] = f"/api/journals/{journal_id}/album-cover"
        return data

    async def find_external_links(self, journal_id: int) -> list[dict[str, Any]]:
        """Return Immich album external-link data for a journal.

        One entry per linked album, each ``{"album_id", "shared_link_url"}``.
        ``shared_link_url`` is the public share URL from the album reference
        when present (and a string), otherwise ``None``. The album web URL is
        built downstream from the user's Immich server URL, so it is not
        returned here.
        """
        result = await self.conn.execute(
            text("""
                SELECT sm.external_id AS album_id,
                       sm.reference_data AS reference_data
                FROM sync_metadata sm
                WHERE sm.integration_source = :source
                  AND sm.internal_id = :journal_id
            """),
            {
                "source": INTEGRATION_SOURCE,
                "journal_id": journal_id,
            },
        )

        links: list[dict[str, Any]] = []
        for row in result.fetchall():
            ref = self._decode_reference_data(row.reference_data, journal_id)
            shared_link_url = ref.get("shared_link_url")
            links.append(
                {
                    "album_id": row.album_id,
                    "shared_link_url": (
                        shared_link_url if isinstance(shared_link_url, str) else None
                    ),
                }
            )
        return links

    async def find_cover_asset(
        self, journal_id: int, user_id: str
    ) -> tuple[str, str | None] | None:
        """Return ``(album_id, thumbnail_asset_id)`` for a PHOTO_ALBUM journal.

        Used by the album-cover proxy. Returns ``None`` when the journal is not
        an Immich album; ``thumbnail_asset_id`` is ``None`` when the album has no
        cover photo recorded.

        **Scoped to the journal's owner.** ``sync_metadata`` carries no owner of
        its own, so the join onto ``journals`` is what supplies one. Without it
        the proxy resolved *any* journal's album and then fetched the thumbnail
        with the **caller's** Immich credentials — so on a server both users
        share, one could stream another's album cover by id (#1267).
        """
        result = await self.conn.execute(
            text("""
                SELECT sm.external_id AS album_id,
                       sm.reference_data AS reference_data
                FROM sync_metadata sm
                JOIN journals j ON j.id = sm.internal_id
                WHERE sm.integration_source = :source
                  AND sm.internal_id = :journal_id
                  AND j.user_id = :user_id
                LIMIT 1
            """),
            {
                "source": INTEGRATION_SOURCE,
                "journal_id": journal_id,
                "user_id": user_id,
            },
        )
        row = result.fetchone()
        if row is None:
            return None
        ref = self._decode_reference_data(row.reference_data, journal_id)
        thumbnail = ref.get("thumbnail_asset_id")
        return (row.album_id, thumbnail if isinstance(thumbnail, str) else None)

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
        """Remove a journal's album ``sync_metadata`` link.

        Called when a journal is deleted so album links do not outlive the
        journal they belonged to.
        """
        await self.conn.execute(
            text("""
                DELETE FROM sync_metadata
                WHERE integration_source = :source
                  AND internal_id = :journal_id
            """),
            {"source": INTEGRATION_SOURCE, "journal_id": journal_id},
        )
