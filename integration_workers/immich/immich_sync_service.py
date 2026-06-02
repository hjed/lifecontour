"""Immich People Sync Service.

Implements the inbound people sync logic: fetch Immich people, match to
local contacts using :class:`ContactNameMatcher`, create or link as
needed, and handle birthday sync.

This service runs inside the Immich worker and uses a database
connection (``AsyncConnection``) for all persistence operations.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from core_shared.contact_name_matcher import ContactNameMatcher
from core_shared.models.contacts.entities import Contact
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from immich_api_client import ImmichApiClient
from immich_models import ImmichPerson

logger = structlog.get_logger(__name__)


@dataclass
class PeopleSyncResult:
    """Summary of a people sync operation.

    Attributes:
        created: New contacts created from unmatched Immich people.
        linked: Existing contacts auto-linked via name match.
        unchanged: Existing links that were already up-to-date.
        updated: Existing links where version hash changed.
        skipped: People skipped (unnamed, hidden).
        conflicts: Ambiguous matches stored as sync conflicts.
        errors: People that failed to sync.
        error_details: Per-person error messages.
    """

    created: int = 0
    linked: int = 0
    unchanged: int = 0
    updated: int = 0
    skipped: int = 0
    conflicts: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)


class ImmichSyncService:
    """Inbound people sync from Immich to local contacts.

    Args:
        api_client: Configured :class:`ImmichApiClient`.
        connection: Async database connection.
        user_id: Internal user ID (string).
        integration_source: Integration source name (default ``"immich"``).
    """

    _INTEGRATION_SOURCE = "immich"
    _EXTERNAL_ENTITY_TYPE = "person"
    _INTERNAL_ENTITY_TYPE = "contact"

    def __init__(
        self,
        api_client: ImmichApiClient,
        connection: AsyncConnection,
        user_id: str,
        integration_source: str = "immich",
    ) -> None:
        self._api = api_client
        self._conn = connection
        self._user_id = user_id
        self._integration_source = integration_source
        self._contacts_cache: list[Contact] | None = None

    # -- Public API -------------------------------------------------------

    async def list_people_batches(self) -> AsyncIterator[list[dict[str, Any]]]:
        """Yield pages of serialized Immich people for batch processing."""
        page = 1
        while True:
            response = await self._api.get_all_people(page=page, size=500)
            if not response.people:
                break

            logger.info(
                "Listed people batch", page=page, batch_size=len(response.people)
            )
            yield [p.model_dump() for p in response.people]

            if not response.has_next_page:
                break
            page += 1

    async def sync_people_batch(
        self, people_data: list[dict[str, Any]]
    ) -> PeopleSyncResult:
        """Sync a batch of Immich people to local contacts.

        Args:
            people_data: Serialized ImmichPerson dictionaries.

        Returns:
            A :class:`PeopleSyncResult` summarising the batch operation.
        """
        result = PeopleSyncResult()

        # Pre-load contacts cache for this batch
        self._contacts_cache = await self._fetch_user_contacts()

        for p_dict in people_data:
            person = ImmichPerson.model_validate(p_dict)
            await self._process_person(person, result)

        logger.info(
            "Immich people batch sync complete",
            user_id=self._user_id,
            created=result.created,
            linked=result.linked,
            unchanged=result.unchanged,
            updated=result.updated,
            skipped=result.skipped,
            conflicts=result.conflicts,
        )

        return result

    # -- Static helpers ---------------------------------------------------

    @staticmethod
    def parse_person_name(full_name: str) -> tuple[str, str | None]:
        """Parse an Immich person name into first/last name.

        Delegates to :meth:`ContactNameMatcher.parse_name`.
        """
        return ContactNameMatcher.parse_name(full_name)

    @staticmethod
    def calculate_version_hash(person: ImmichPerson) -> str:
        """Compute a version hash from a person's name and birth date.

        Used for idempotency: if the hash hasn't changed, the sync
        is skipped.
        """
        data = f"{person.name}|{person.birth_date or ''}"
        return hashlib.sha256(data.encode()).hexdigest()

    @staticmethod
    def parse_birth_date(
        birth_date: str | None,
    ) -> tuple[int, int, int] | None:
        """Parse an ISO-8601 date string into ``(year, month, day)``.

        Returns:
            Tuple of ``(year, month, day)`` or ``None`` if invalid.
        """
        if not birth_date:
            return None
        try:
            dt = datetime.strptime(birth_date, "%Y-%m-%d")  # noqa: DTZ007
            return (dt.year, dt.month, dt.day)
        except ValueError:
            logger.warning("Invalid birth date format", birth_date=birth_date)
            return None

    # -- Private implementation -------------------------------------------

    async def _process_person(
        self,
        person: ImmichPerson,
        result: PeopleSyncResult,
    ) -> None:
        """Process a single Immich person."""
        # Skip unnamed or hidden people
        if not person.name or not person.name.strip():
            result.skipped += 1
            return
        if person.is_hidden:
            result.skipped += 1
            return

        version_hash = self.calculate_version_hash(person)

        # 1. Check for existing ExternalReference
        existing_ref = await self._find_external_reference(person.id)

        if existing_ref:
            # Person is already linked — check if update needed
            existing_meta = await self._find_sync_metadata(person.id)
            if existing_meta and existing_meta.version_hash == version_hash:
                result.unchanged += 1
                return

            # Version changed — update sync metadata
            await self._upsert_sync_metadata(
                external_id=person.id,
                internal_id=existing_ref.internal_entity_id,
                version_hash=version_hash,
            )
            # Sync birthday since version hash changed
            await self._sync_birthday(existing_ref.internal_entity_id, person)
            result.updated += 1
            return

        # 2. No existing link — try name matching
        contacts = (
            self._contacts_cache
            if self._contacts_cache is not None
            else await self._fetch_user_contacts()
        )
        matches = ContactNameMatcher.find_matches(person.name, contacts)

        if len(matches) == 1:
            # Single match — auto-link
            contact = matches[0]
            assert contact.id is not None
            await self._create_external_reference(
                contact_id=contact.id, person_id=person.id
            )
            await self._upsert_sync_metadata(
                external_id=person.id,
                internal_id=contact.id,
                version_hash=version_hash,
            )
            # Handle birthday sync
            await self._sync_birthday(contact.id, person)
            result.linked += 1
            return

        if len(matches) > 1:
            # Multiple matches — create pending entity mapping
            candidate_ids = [m.id for m in matches if m.id is not None]
            await self._create_pending_entity_mapping(
                person_id=person.id,
                person_name=person.name,
                candidate_ids=candidate_ids,
            )
            result.conflicts += 1
            return

        # 3. No match — create new contact
        contact_id = await self._create_contact(person)
        await self._create_external_reference(
            contact_id=contact_id, person_id=person.id
        )
        await self._upsert_sync_metadata(
            external_id=person.id,
            internal_id=contact_id,
            version_hash=version_hash,
        )
        # Handle birthday sync for new contact
        await self._sync_birthday(contact_id, person)
        result.created += 1

    # -- Database operations ----------------------------------------------

    async def _find_external_reference(self, person_id: str) -> Any | None:
        """Look up an ExternalReference by Immich person ID."""
        query = text("""
            SELECT id, internal_entity_id
            FROM external_references
            WHERE external_system = :external_system
              AND internal_entity_type = :internal_entity_type
              AND external_entity_type = :external_entity_type
              AND external_entity_id = :external_entity_id
        """)
        result = await self._conn.execute(
            query,
            {
                "external_system": self._integration_source,
                "internal_entity_type": self._INTERNAL_ENTITY_TYPE,
                "external_entity_type": self._EXTERNAL_ENTITY_TYPE,
                "external_entity_id": person_id,
            },
        )
        return result.fetchone()

    async def _find_sync_metadata(self, external_id: str) -> Any | None:
        """Look up SyncMetadata by external ID."""
        query = text("""
            SELECT id, version_hash, sync_status
            FROM sync_metadata
            WHERE integration_source = :integration_source
              AND external_id = :external_id
        """)
        result = await self._conn.execute(
            query,
            {
                "integration_source": self._integration_source,
                "external_id": external_id,
            },
        )
        return result.fetchone()

    async def _fetch_user_contacts(self) -> list[Contact]:
        """Fetch all contacts for the current user from the database.

        Returns lightweight Contact objects with just name fields for
        matching purposes.
        """
        query = text("""
            SELECT id, first_name, last_name, middle_name
            FROM contacts
        """)
        result = await self._conn.execute(query)
        rows = result.fetchall()

        return [
            Contact(
                id=row.id,
                first_name=row.first_name,
                last_name=row.last_name,
                middle_name=row.middle_name,
            )
            for row in rows
        ]

    async def _create_contact(self, person: ImmichPerson) -> int:
        """Create a new contact from an Immich person.

        Returns:
            The new contact's ID.
        """
        first_name, last_name = self.parse_person_name(person.name)
        now = datetime.now(UTC)

        query = text("""
            INSERT INTO contacts
                (first_name, last_name, is_favourite,
                 created_at, updated_at)
            VALUES
                (:first_name, :last_name, false,
                 :now, :now)
            RETURNING id, created_at, updated_at
        """)
        result = await self._conn.execute(
            query,
            {
                "first_name": first_name,
                "last_name": last_name,
                "now": now,
            },
        )
        row = result.fetchone()
        if not row:
            raise RuntimeError(
                f"Failed to create contact for Immich person {person.id}"
            )

        logger.info(
            "Created new contact from Immich person",
            contact_id=row.id,
            person_id=person.id,
            person_name=person.name,
        )
        return int(row.id)

    async def _create_external_reference(self, contact_id: int, person_id: str) -> None:
        """Create an ExternalReference linking a contact to an Immich person."""
        query = text("""
            INSERT INTO external_references
                (internal_entity_type, internal_entity_id, external_system,
                 external_entity_type, external_entity_id)
            VALUES
                (:internal_entity_type, :internal_entity_id, :external_system,
                 :external_entity_type, :external_entity_id)
            RETURNING id, created_at, updated_at
        """)
        result = await self._conn.execute(
            query,
            {
                "internal_entity_type": self._INTERNAL_ENTITY_TYPE,
                "internal_entity_id": contact_id,
                "external_system": self._integration_source,
                "external_entity_type": self._EXTERNAL_ENTITY_TYPE,
                "external_entity_id": person_id,
            },
        )
        row = result.fetchone()
        if not row:
            raise RuntimeError(
                f"Failed to create ExternalReference for contact {contact_id}"
            )

    async def _upsert_sync_metadata(
        self,
        external_id: str,
        internal_id: int,
        version_hash: str,
    ) -> None:
        """Create or update SyncMetadata for a person-to-contact mapping."""
        now = datetime.now(UTC)
        query = text("""
            INSERT INTO sync_metadata
                (internal_id, integration_source, external_id,
                 last_synced_at, version_hash, sync_status,
                 retry_count, created_at, updated_at)
            VALUES
                (:internal_id, :integration_source, :external_id,
                 :now, :version_hash, 'success',
                 0, :now, :now)
            ON CONFLICT (integration_source, external_id)
            DO UPDATE SET
                internal_id = EXCLUDED.internal_id,
                last_synced_at = EXCLUDED.last_synced_at,
                version_hash = EXCLUDED.version_hash,
                sync_status = 'success',
                retry_count = 0,
                updated_at = EXCLUDED.updated_at
            RETURNING id
        """)
        await self._conn.execute(
            query,
            {
                "internal_id": internal_id,
                "integration_source": self._integration_source,
                "external_id": external_id,
                "version_hash": version_hash,
                "now": now,
            },
        )

    async def _create_pending_entity_mapping(
        self,
        person_id: str,
        person_name: str,
        candidate_ids: list[int],
    ) -> None:
        """Create a pending entity mapping for an ambiguous name match."""
        now = datetime.now(UTC)
        candidates_json = json.dumps(candidate_ids)

        query = text("""
            INSERT INTO pending_entity_mappings
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
            RETURNING id
        """)
        result = await self._conn.execute(
            query,
            {
                "user_id": self._user_id,
                "integration_source": self._integration_source,
                "external_entity_id": person_id,
                "external_entity_name": person_name,
                "candidate_contact_ids": candidates_json,
                "now": now,
            },
        )
        row = result.fetchone()
        if not row:
            raise RuntimeError(
                f"Failed to create pending entity mapping for person {person_id}"
            )

        logger.info(
            "Created pending entity mapping for ambiguous name match",
            person_id=person_id,
            person_name=person_name,
            candidate_count=len(candidate_ids),
        )

    async def _sync_birthday(self, contact_id: int, person: ImmichPerson) -> None:
        """Sync birthday from Immich person to contact.

        Only creates a birthday if:
        - The Immich person has a birth_date
        - The contact does not already have a birthday
        """
        parsed = self.parse_birth_date(person.birth_date)
        if parsed is None:
            return

        year, month, day = parsed

        # Check if contact already has a birthday
        check_query = text("""
            SELECT id FROM contact_important_dates
            WHERE contact_id = :contact_id AND date_type = 'birthday'
            LIMIT 1
        """)
        result = await self._conn.execute(check_query, {"contact_id": contact_id})
        if result.fetchone() is not None:
            logger.debug(
                "Contact already has birthday, skipping",
                contact_id=contact_id,
            )
            return

        # Create birthday important date
        insert_query = text("""
            INSERT INTO contact_important_dates
                (contact_id, date_type, precision, year, month, day)
            VALUES
                (:contact_id, 'birthday', 'full', :year, :month, :day)
            ON CONFLICT DO NOTHING
        """)
        await self._conn.execute(
            insert_query,
            {
                "contact_id": contact_id,
                "year": year,
                "month": month,
                "day": day,
            },
        )
        logger.info(
            "Created birthday from Immich person",
            contact_id=contact_id,
            birth_date=person.birth_date,
        )
