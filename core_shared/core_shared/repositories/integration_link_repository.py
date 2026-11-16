"""Repository for reading the canonical integration-link store (``sync_metadata``).

ITER15-001 Phase 3 consolidates integration entity links onto ``sync_metadata``.
This repository provides the unified link-lookup reads used by both the backend
consumer and the integration workers, replacing the legacy
``external_references`` reads. Writes remain on the existing upsert paths,
apart from :meth:`IntegrationLinkRepository.patch_reference_data` and
:meth:`IntegrationLinkRepository.record_superseded_versions` and
:meth:`IntegrationLinkRepository.record_merged_source_versions`, which a worker
uses to record per-link sync state without racing the backend's writes.

The repository provides the link-lookup reads (plus the contact reads behind an
outbound sync) used by both ``core_shared`` consumers and the integration workers,
in the same constructor and raw-SQL style as the rest of the data layer.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Final

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from core_shared.sync_base import (
    MAX_SUPERSEDED_VERSIONS,
    MERGED_SOURCE_VERSIONS_KEY,
    SUPERSEDED_VERSIONS_KEY,
    parse_source_versions,
)

logger = structlog.get_logger(__name__)

# Ranks a push's versions after any recorded ones, however long the record.
_SUPERSEDED_RANK_OFFSET: Final = 1_000_000_000


class IntegrationLinkRepository:
    """Read access to integration entity links stored in ``sync_metadata``.

    Args:
        connection: An async SQLAlchemy connection.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self._conn = connection

    async def find_link_by_external(
        self, integration_source: str, external_id: str, *, user_id: str
    ) -> dict[str, Any] | None:
        """Find ``user_id``'s link by ``(integration_source, external_id)``.

        Args:
            integration_source: e.g. ``'google'``, ``'immich'``.
            external_id: The external system's id for the entity.
            user_id: The link's owner; another user's link is never returned.

        Returns:
            A dict describing the link, or ``None`` when no link exists.
        """
        query = text("""
            SELECT internal_id, internal_uuid, integration_source, external_id,
                   internal_entity_type, external_entity_type, reference_data,
                   version_hash
            FROM sync_metadata
            WHERE user_id = :user_id
              AND integration_source = :integration_source
              AND external_id = :external_id
        """)
        result = await self._conn.execute(
            query,
            {
                "user_id": user_id,
                "integration_source": integration_source,
                "external_id": external_id,
            },
        )
        row = result.fetchone()
        return self._row_to_dict(row) if row else None

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
        query = text("""
            SELECT internal_id, internal_uuid, integration_source, external_id,
                   internal_entity_type, external_entity_type, reference_data,
                   version_hash
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

    async def find_contact_with_birthday(
        self, contact_id: int
    ) -> dict[str, Any] | None:
        """Fetch a contact's name fields, full-precision birthday and version.

        ``updated_at`` is the version a push reads, recorded as the link's
        ``last_synced_at`` so an edit landing mid-push is still owed one.

        Reads the ``contacts`` / ``contact_important_dates`` tables (not a link
        table); colocated here so the integration workers have a single
        ``core_shared`` repository for the reads behind an outbound sync.

        Args:
            contact_id: Internal contact ID.

        Returns:
            Dictionary with name and birthday fields, or ``None``.
        """
        query = text("""
            SELECT c.first_name, c.last_name, c.middle_name, c.updated_at,
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
            "updated_at": row.updated_at,
        }

    async def get_immich_person_id(
        self, contact_id: int, *, user_id: str
    ) -> str | None:
        """Look up the Immich person id the owner has linked to a contact.

        Args:
            contact_id: Internal contact id.
            user_id: The acting user; another user's link is never returned.

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
              AND user_id = :user_id
            ORDER BY id
            LIMIT 1
        """)
        result = await self._conn.execute(
            query, {"contact_id": contact_id, "user_id": user_id}
        )
        row = result.fetchone()
        return row.external_id if row else None

    async def get_contact_ids_by_immich_person_ids(
        self, person_ids: list[str], *, user_id: str
    ) -> dict[str, int]:
        """Resolve Immich person ids to ``user_id``'s linked contact ids.

        Person ids without a contact link of the owner's are omitted from the
        result, so unresolved people never produce orphan participants.

        Args:
            person_ids: Immich person UUIDs to resolve.
            user_id: The links' owner; another user's links are never used.

        Returns:
            A mapping of ``{person_id: contact_id}`` for the linked people.
        """
        if not person_ids:
            return {}

        # ``internal_id`` is nullable; filtering it out keeps the return type
        # honest (``dict[str, int]``) and matches the "omit unresolved" contract.
        query = text("""
            SELECT external_id, internal_id
            FROM sync_metadata
            WHERE user_id = :user_id
              AND integration_source = 'immich'
              AND internal_entity_type = 'contact'
              AND external_entity_type = 'person'
              AND internal_id IS NOT NULL
              AND external_id = ANY(:person_ids)
        """)
        result = await self._conn.execute(
            query, {"user_id": user_id, "person_ids": person_ids}
        )
        return {row.external_id: row.internal_id for row in result.fetchall()}

    async def patch_reference_data(
        self,
        integration_source: str,
        external_id: str,
        patch: Mapping[str, Any],
        *,
        user_id: str,
    ) -> None:
        """Merge ``patch`` into ``user_id``'s link's ``reference_data``.

        One statement, so a concurrent writer's keys on the same row are never
        lost to a read-modify-write here. Stored data that is not a JSON object
        (NULL, or unreadable) is replaced by ``patch`` alone.
        """
        await self._conn.execute(
            text("""
                UPDATE sync_metadata
                SET reference_data = (
                    CASE WHEN reference_data IS JSON OBJECT
                         THEN reference_data::jsonb
                         ELSE '{}'::jsonb
                    END || CAST(:patch AS jsonb)
                )::text
                WHERE user_id = :user_id
                  AND integration_source = :integration_source
                  AND external_id = :external_id
            """),
            {
                "patch": json.dumps(dict(patch)),
                "user_id": user_id,
                "integration_source": integration_source,
                "external_id": external_id,
            },
        )

    async def record_superseded_versions(
        self,
        integration_source: str,
        external_id: str,
        versions: Sequence[str],
        *,
        user_id: str,
    ) -> None:
        """Append remote ``versions`` a push replaced to ``user_id``'s link (#1938).

        Kept under ``SUPERSEDED_VERSIONS_KEY``, oldest first: a version already
        recorded moves to the newest end, and only the newest
        ``MAX_SUPERSEDED_VERSIONS`` are kept. One statement, like
        :meth:`patch_reference_data`, so the backend's keys on the same row are
        never lost; a record that cannot be read as a list of versions starts
        empty.
        """
        if not versions:
            return
        await self._conn.execute(
            text("""
                UPDATE sync_metadata AS link
                SET reference_data = (
                    stored.data || jsonb_build_object(
                        CAST(:key AS text),
                        (
                            SELECT COALESCE(jsonb_agg(version ORDER BY position), '[]')
                            FROM (
                                SELECT version, position
                                FROM (
                                    SELECT version, max(position) AS position
                                    FROM (
                                        SELECT entry #>> '{}' AS version,
                                               ordinality AS position
                                        FROM jsonb_array_elements(
                                            CASE WHEN jsonb_typeof(stored.data -> CAST(:key AS text))
                                                      = 'array'
                                                 THEN stored.data -> CAST(:key AS text)
                                                 ELSE '[]'::jsonb
                                            END
                                        ) WITH ORDINALITY AS recorded(entry, ordinality)
                                        WHERE jsonb_typeof(entry) = 'string'
                                        UNION ALL
                                        SELECT added.version,
                                               CAST(:offset AS bigint) + added.ordinality
                                        FROM jsonb_array_elements_text(
                                            CAST(:versions AS jsonb)
                                        ) WITH ORDINALITY AS added(version, ordinality)
                                    ) AS candidates
                                    GROUP BY version
                                ) AS distinct_versions
                                ORDER BY position DESC
                                LIMIT CAST(:keep AS integer)
                            ) AS newest
                        )
                    )
                )::text
                FROM (
                    SELECT id,
                           CASE WHEN reference_data IS JSON OBJECT
                                THEN reference_data::jsonb
                                ELSE '{}'::jsonb
                           END AS data
                    FROM sync_metadata
                    WHERE user_id = :user_id
                      AND integration_source = :integration_source
                      AND external_id = :external_id
                ) AS stored
                WHERE link.id = stored.id
            """),
            {
                "key": SUPERSEDED_VERSIONS_KEY,
                "versions": json.dumps(list(versions)),
                # Added versions rank after every recorded one.
                "offset": _SUPERSEDED_RANK_OFFSET,
                "keep": MAX_SUPERSEDED_VERSIONS,
                "user_id": user_id,
                "integration_source": integration_source,
                "external_id": external_id,
            },
        )

    async def record_merged_source_versions(
        self,
        integration_source: str,
        external_id: str,
        versions: Mapping[str, str],
        *,
        user_id: str,
    ) -> None:
        """Record the source versions of the record a push merged into (#1938).

        Kept under ``MERGED_SOURCE_VERSIONS_KEY``, per source the later of the
        stored and the given time, so a push recorded out of order never moves
        a source back. ``versions`` that are not all readable record nothing;
        a stored entry that is not a readable time is dropped. One statement,
        like :meth:`patch_reference_data`, so the backend's keys on the same
        row are never lost.
        """
        if not parse_source_versions(versions):
            return
        await self._conn.execute(
            text("""
                UPDATE sync_metadata AS link
                SET reference_data = (
                    stored.data || jsonb_build_object(
                        CAST(:key AS text),
                        (
                            SELECT jsonb_object_agg(source, version)
                            FROM (
                                SELECT DISTINCT ON (source) source, version
                                FROM (
                                    SELECT recorded.key AS source,
                                           recorded.value AS version
                                    FROM jsonb_each(
                                        CASE WHEN jsonb_typeof(stored.data -> CAST(:key AS text))
                                                  = 'object'
                                             THEN stored.data -> CAST(:key AS text)
                                             ELSE '{}'::jsonb
                                        END
                                    ) AS recorded
                                    WHERE jsonb_typeof(recorded.value) = 'string'
                                      AND pg_input_is_valid(
                                          recorded.value #>> '{}', 'timestamptz'
                                      )
                                    UNION ALL
                                    SELECT added.key, added.value
                                    FROM jsonb_each(CAST(:versions AS jsonb)) AS added
                                ) AS candidates
                                ORDER BY source,
                                         CAST(version #>> '{}' AS timestamptz) DESC
                            ) AS latest
                        )
                    )
                )::text
                FROM (
                    SELECT id,
                           CASE WHEN reference_data IS JSON OBJECT
                                THEN reference_data::jsonb
                                ELSE '{}'::jsonb
                           END AS data
                    FROM sync_metadata
                    WHERE user_id = :user_id
                      AND integration_source = :integration_source
                      AND external_id = :external_id
                ) AS stored
                WHERE link.id = stored.id
            """),
            {
                "key": MERGED_SOURCE_VERSIONS_KEY,
                "versions": json.dumps(dict(versions)),
                "user_id": user_id,
                "integration_source": integration_source,
                "external_id": external_id,
            },
        )

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
