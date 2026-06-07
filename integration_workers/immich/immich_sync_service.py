"""Immich People Sync Service.

Implements the inbound people sync logic: fetch Immich people, match to
local contacts using :class:`ContactNameMatcher`, create or link as
needed, and handle birthday sync.

Contact mutations (create/update) are published as outbox events so that
the backend ``OutboxEventProcessor`` handles the actual database writes
via ``ContactService``, matching the established Google-worker pattern.

This service runs inside the Immich worker and uses a database
connection (``AsyncConnection``) for all persistence operations.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from core_shared.contact_name_matcher import ContactNameMatcher
from core_shared.models.contacts.entities import Contact, ImportantDate
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.contacts.serialization import serialize_contact
from core_shared.repositories.external_reference_repository import (
    ExternalReferenceRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from immich_api_client import ImmichApiClient
from immich_models import ImmichAlbum, ImmichAsset, ImmichPerson

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


@dataclass
class AlbumSyncResult:
    """Summary of an album sync operation.

    Attributes:
        created: New PHOTO_ALBUM journals emitted.
        updated: Albums whose metadata changed since the last sync.
        unchanged: Albums already up-to-date (no event emitted).
        errors: Albums that failed to sync.
        error_details: Per-album error messages.
    """

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)


class ImmichSyncService:
    """Inbound people sync from Immich to local contacts.

    Contact mutations are emitted as outbox events so the backend
    ``OutboxEventProcessor`` handles them through ``ContactService``,
    which records history, publishes domain events, and triggers
    search re-indexing.

    Args:
        api_client: Configured :class:`ImmichApiClient`.
        connection: Async database connection.
        user_id: Internal user ID (string).
        integration_source: Integration source name (default ``"immich"``).
    """

    _INTEGRATION_SOURCE = "immich"
    _EXTERNAL_ENTITY_TYPE = "person"
    _INTERNAL_ENTITY_TYPE = "contact"
    _ALBUM_INTEGRATION_SOURCE = "immich_album"
    # Number of albums processed per fanned-out batch job.
    _ALBUM_BATCH_SIZE = 50

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

        Contact creates/updates are published as outbox events and
        processed asynchronously by the backend ``OutboxEventProcessor``.

        Args:
            people_data: List of serialized ImmichPerson dicts.

        Returns:
            A :class:`PeopleSyncResult` summarising the sync.
        """
        result = PeopleSyncResult()

        for data in people_data:
            person = ImmichPerson.model_validate(data)
            try:
                await self._process_person(person, result)
            except Exception as e:  # noqa: BLE001
                result.errors += 1
                result.error_details.append(
                    f"Error processing person {person.id}: {e!s}"
                )
                logger.error(
                    "Error processing person",
                    person_id=person.id,
                    person_name=person.name,
                    error=str(e),
                )

        return result

    async def list_album_id_batches(self) -> AsyncIterator[list[str]]:
        """Yield batches of Immich album IDs for fan-out processing.

        Fetching each album's assets (`get_album`) is a per-album network call,
        so album sync is fanned out across batch jobs (mirroring people sync) to
        avoid a single task timing out on accounts with many albums.
        """
        albums = await self._api.get_all_albums()
        album_ids = [album.id for album in albums]
        logger.info("Listed albums for sync", total=len(album_ids))

        for start in range(0, len(album_ids), self._ALBUM_BATCH_SIZE):
            yield album_ids[start : start + self._ALBUM_BATCH_SIZE]

    async def sync_albums_batch(self, album_ids: list[str]) -> AlbumSyncResult:
        """Sync a batch of Immich albums to PHOTO_ALBUM journals.

        For each album, derives its date range from photo timestamps and emits
        an ``immich_album.created`` / ``immich_album.updated`` outbox event when
        the album is new or its metadata changed. The backend
        ``ImmichAlbumOutboxEventProcessor`` performs the journal writes.

        Returns:
            An :class:`AlbumSyncResult` summarising the batch.
        """
        result = AlbumSyncResult()

        for album_id in album_ids:
            try:
                await self._process_album(album_id, result)
            except Exception as e:  # noqa: BLE001
                result.errors += 1
                result.error_details.append(f"Error processing album {album_id}: {e!s}")
                logger.error("Error processing album", album_id=album_id, error=str(e))

        logger.info(
            "Album batch sync complete",
            created=result.created,
            updated=result.updated,
            unchanged=result.unchanged,
            errors=result.errors,
        )
        return result

    async def _process_album(self, album_id: str, result: AlbumSyncResult) -> None:
        """Fetch one album with assets and emit a sync event if it changed."""
        album = await self._api.get_album(album_id)

        date_range = self.derive_album_date_range(album.assets)
        if date_range is None:
            # No dated photos — fall back to the album's updated time so the
            # journal still has a (point-in-time) event date range.
            fallback = album.updated_at or datetime.now(UTC)
            date_range = (fallback, fallback)

        version_hash = self.calculate_album_version_hash(album)
        existing = await self._find_album_sync_metadata(album.id)

        if existing is None:
            await self._emit_album_outbox_event(
                "created", album, date_range, version_hash
            )
            result.created += 1
        elif existing.version_hash != version_hash:
            await self._emit_album_outbox_event(
                "updated", album, date_range, version_hash
            )
            result.updated += 1
        else:
            result.unchanged += 1

    async def _find_album_sync_metadata(self, album_id: str) -> Any | None:
        """Look up album SyncMetadata by Immich album ID."""
        query = text("""
            SELECT id, version_hash, sync_status
            FROM sync_metadata
            WHERE integration_source = :integration_source
              AND external_id = :external_id
        """)
        result = await self._conn.execute(
            query,
            {
                "integration_source": self._ALBUM_INTEGRATION_SOURCE,
                "external_id": album_id,
            },
        )
        return result.fetchone()

    async def _emit_album_outbox_event(
        self,
        sync_action: str,
        album: ImmichAlbum,
        date_range: tuple[datetime, datetime],
        version_hash: str,
    ) -> None:
        """Insert an ``immich_album.{created|updated}`` outbox event."""
        event_id = str(uuid4())
        now = datetime.now(UTC)
        start, end = date_range
        event_data = {
            "integration_source": self._ALBUM_INTEGRATION_SOURCE,
            "external_id": album.id,
            "version_hash": version_hash,
            "sync_action": sync_action,
            "journal_data": {
                "user_id": self._user_id,
                "title": album.album_name or "Untitled album",
                "content": album.description or "",
                "event_date_range_start": start.isoformat(),
                "event_date_range_end": end.isoformat(),
            },
            "album_metadata": {
                "album_name": album.album_name,
                "description": album.description,
                "asset_count": album.asset_count,
                "updated_at": (
                    album.updated_at.isoformat() if album.updated_at else None
                ),
                "thumbnail_asset_id": album.album_thumbnail_asset_id,
            },
            "sync_timestamp": now.isoformat(),
        }

        query = text("""
            INSERT INTO outbox_events
                (event_id, event_type, aggregate_id, event_data,
                 occurred_at, created_at, retry_count)
            VALUES
                (:event_id, :event_type, 0, :event_data,
                 :occurred_at, :created_at, 0)
        """)
        await self._conn.execute(
            query,
            {
                "event_id": event_id,
                "event_type": f"immich_album.{sync_action}",
                "event_data": json.dumps(event_data),
                "occurred_at": now,
                "created_at": now,
            },
        )
        logger.debug(
            "Emitted outbox event for Immich album sync",
            event_id=event_id,
            sync_action=sync_action,
            album_id=album.id,
        )

    async def sync_contact_outbound(self, contact_id: int) -> dict[str, Any]:
        """Sync a local contact update to Immich.

        Checks if the contact is linked to an Immich person. If so, fetches
        the contact's details (name, full precision birthday) and pushes
        updates to Immich.

        Args:
            contact_id: Local contact ID.

        Returns:
            Dictionary with sync status.
        """
        # 1. Find if contact is linked to Immich
        ext_ref_repo = ExternalReferenceRepository(self._conn)
        ref = await ext_ref_repo.find_by_internal_entity(
            internal_entity_type=self._INTERNAL_ENTITY_TYPE,
            internal_entity_id=contact_id,
            external_system=self._integration_source,
            external_entity_type=self._EXTERNAL_ENTITY_TYPE,
        )
        if not ref:
            return {"status": "skipped", "reason": "not_linked"}

        person_id = ref["external_entity_id"]

        # 2. Fetch the contact's name and birthday
        contact_data = await ext_ref_repo.find_contact_with_birthday(contact_id)
        if not contact_data:
            return {"status": "error", "reason": "contact_not_found"}

        # 3. Build update payload for Immich
        update_data: dict[str, Any] = {}
        name_parts = []
        if contact_data.get("first_name"):
            name_parts.append(contact_data["first_name"])
        if contact_data.get("middle_name"):
            name_parts.append(contact_data["middle_name"])
        if contact_data.get("last_name"):
            name_parts.append(contact_data["last_name"])
        if name_parts:
            update_data["name"] = " ".join(name_parts)

        if (
            contact_data.get("year")
            and contact_data.get("month")
            and contact_data.get("day")
        ):
            update_data["birthDate"] = (
                f"{contact_data['year']:04d}-{contact_data['month']:02d}-{contact_data['day']:02d}"
            )
        else:
            # Preserve Immich's existing birthday when local has no
            # full-precision birthday (source-of-truth enforcement).
            immich_person = await self._api.get_person(person_id)
            if immich_person and immich_person.birth_date:
                update_data["birthDate"] = immich_person.birth_date

        if not update_data:
            return {"status": "skipped", "reason": "no_changes"}

        # 4. Push update to Immich
        updated_person = await self._api.update_person(person_id, update_data)

        # 5. Update sync metadata version hash
        new_hash = self.calculate_version_hash(updated_person)
        await self._upsert_sync_metadata(
            external_id=person_id,
            internal_id=contact_id,
            version_hash=new_hash,
        )

        logger.info(
            "Outbound contact sync successful",
            contact_id=contact_id,
            person_id=person_id,
        )
        return {"status": "success", "person_id": person_id}

    # -- Static helpers ---------------------------------------------------

    @staticmethod
    def parse_person_name(full_name: str) -> tuple[str, str | None]:
        """Parse an Immich person name into first/last name.

        Delegates to :meth:`ContactNameMatcher.parse_name`.
        """
        return ContactNameMatcher.parse_name(full_name)

    @staticmethod
    def calculate_version_hash(person: ImmichPerson) -> str:
        """Calculate a SHA-256 hash for an Immich person's mutable fields."""
        data = f"{person.name}|{person.birth_date or ''}"
        return hashlib.sha256(data.encode()).hexdigest()

    # -- Album sync helpers ----------------------------------------------

    @staticmethod
    def _asset_timezone(asset: ImmichAsset) -> tzinfo:
        """Resolve an asset's local timezone from EXIF, defaulting to UTC."""
        if asset.exif_info is not None and asset.exif_info.timezone:
            try:
                return ZoneInfo(asset.exif_info.timezone)
            except (ZoneInfoNotFoundError, ValueError):
                logger.warning(
                    "Invalid EXIF timezone, defaulting to UTC",
                    timezone=asset.exif_info.timezone,
                )
        return UTC

    @staticmethod
    def _asset_instant_and_tz(
        asset: ImmichAsset,
    ) -> tuple[datetime, tzinfo] | None:
        """Return an asset's capture instant and its local timezone.

        Prefers ``takenAt`` (a UTC instant) and falls back to EXIF
        ``dateTimeOriginal``. A *naive* timestamp's wall clock is local time in
        the asset's own EXIF timezone, so it is localized to that timezone
        rather than assumed to be UTC — otherwise the derived day could shift by
        the timezone offset. The timezone (UTC fallback) is also used for the
        day boundary.
        """
        ts = asset.taken_at
        if ts is None and asset.exif_info is not None:
            ts = asset.exif_info.date_time_original
        if ts is None:
            return None

        local_tz = ImmichSyncService._asset_timezone(asset)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=local_tz)
        return (ts, local_tz)

    @staticmethod
    def derive_album_date_range(
        assets: list[ImmichAsset],
    ) -> tuple[datetime, datetime] | None:
        """Derive an album's event date range from its photo timestamps.

        The range covers full days in each boundary photo's local timezone:
        the start of the earliest photo's day to the end of the latest photo's
        day. Per-photo EXIF timezones are honoured (UTC fallback) so a photo
        taken at 23:00 UTC is dated by its local day, not the UTC day.

        Returns ``None`` when no asset has a usable timestamp.
        """
        timed: list[tuple[datetime, tzinfo]] = []
        for asset in assets:
            item = ImmichSyncService._asset_instant_and_tz(asset)
            if item is not None:
                timed.append(item)

        if not timed:
            return None

        earliest_ts, earliest_tz = min(timed, key=lambda item: item[0])
        latest_ts, latest_tz = max(timed, key=lambda item: item[0])

        start_local = earliest_ts.astimezone(earliest_tz)
        end_local = latest_ts.astimezone(latest_tz)

        start = start_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end = end_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        return (start, end)

    @staticmethod
    def calculate_album_version_hash(album: ImmichAlbum) -> str:
        """Calculate a SHA-256 hash of an album's mutable metadata."""
        updated = album.updated_at.isoformat() if album.updated_at else ""
        data = f"{album.album_name}|{album.description}|{album.asset_count}|{updated}"
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

            # Version changed — emit contact.updated outbox event
            contact_data = self._build_contact_data(
                person, existing_ref.internal_entity_id
            )
            await self._emit_outbox_event(
                sync_type="updated",
                external_id=person.id,
                contact_data=contact_data,
                version_hash=version_hash,
            )
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
            # Emit contact.updated so the processor updates the contact
            # (adds photo_url, birthday, etc.) through ContactService
            contact_data = self._build_contact_data(person, contact.id)
            await self._emit_outbox_event(
                sync_type="updated",
                external_id=person.id,
                contact_data=contact_data,
                version_hash=version_hash,
            )
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

        # 3. No match — emit contact.created outbox event
        contact_data = self._build_contact_data(person, contact_id=None)
        await self._emit_outbox_event(
            sync_type="created",
            external_id=person.id,
            contact_data=contact_data,
            version_hash=version_hash,
        )
        result.created += 1

    def _build_contact_data(
        self, person: ImmichPerson, contact_id: int | None
    ) -> dict[str, Any]:
        """Build a serialized contact dict from an Immich person.

        The data follows the canonical contact format used by the outbox
        pattern, including the avatar proxy URL and birthday.

        Args:
            person: Immich person to convert.
            contact_id: Existing contact ID (for photo_url), or ``None``
                for new contacts (photo_url will be set later by the
                processor when the contact ID is assigned).

        Returns:
            Serialized contact dict suitable for outbox event payload.
        """
        first_name, last_name = self.parse_person_name(person.name)

        # Build important_dates from birthday
        important_dates: list[ImportantDate] | None = None
        parsed_birthday = self.parse_birth_date(person.birth_date)
        if parsed_birthday:
            year, month, day = parsed_birthday
            important_dates = [
                ImportantDate(
                    contact_id=contact_id or 0,
                    date_type=ImportantDateType.BIRTHDAY,
                    precision=DatePrecision.FULL,
                    year=year,
                    month=month,
                    day=day,
                )
            ]

        # Build photo_url for the avatar proxy endpoint
        photo_url = f"/api/contacts/{contact_id}/avatar" if contact_id else None

        contact = Contact(
            first_name=first_name,
            last_name=last_name,
            photo_url=photo_url,
            important_dates=important_dates,
        )

        return serialize_contact(contact)

    # -- Outbox event emission --------------------------------------------

    async def _emit_outbox_event(
        self,
        sync_type: str,
        external_id: str,
        contact_data: dict[str, Any],
        version_hash: str,
    ) -> None:
        """Insert a contact sync outbox event via raw SQL.

        Follows the same event structure as the Google worker's
        ``OutboxEvent.create_contact_sync_event()``.

        Args:
            sync_type: ``'created'`` or ``'updated'``.
            external_id: Immich person ID.
            contact_data: Serialized contact dict.
            version_hash: The calculated Immich person version hash.
        """
        event_id = str(uuid4())
        now = datetime.now(UTC)
        event_data = {
            "integration_source": self._integration_source,
            "external_id": external_id,
            "contact_data": contact_data,
            "sync_timestamp": now.isoformat(),
            "sync_type": sync_type,
            "etag": version_hash,
        }

        query = text("""
            INSERT INTO outbox_events
                (event_id, event_type, aggregate_id, event_data,
                 occurred_at, created_at, retry_count)
            VALUES
                (:event_id, :event_type, 0, :event_data,
                 :occurred_at, :created_at, 0)
        """)
        await self._conn.execute(
            query,
            {
                "event_id": event_id,
                "event_type": f"contact.{sync_type}",
                "event_data": json.dumps(event_data),
                "occurred_at": now,
                "created_at": now,
            },
        )
        logger.debug(
            "Emitted outbox event for Immich contact sync",
            event_id=event_id,
            sync_type=sync_type,
            external_id=external_id,
        )

    # -- Database operations (integration-specific) -----------------------

    async def _find_external_reference(self, person_id: str) -> Any | None:
        """Look up an ExternalReference by Immich person ID."""
        query = text("""
            SELECT id, internal_entity_id
            FROM external_references
            WHERE external_system = :external_system
              AND internal_entity_type = :internal_entity_type
              AND external_entity_type = :external_entity_type
              AND external_entity_id = :external_entity_id
            ORDER BY id DESC
            LIMIT 1
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

    async def _create_external_reference(self, contact_id: int, person_id: str) -> None:
        """Create an ExternalReference linking a contact to an Immich person."""
        query = text("""
            INSERT INTO external_references
                (internal_entity_type, internal_entity_id, external_system,
                 external_entity_type, external_entity_id)
            SELECT
                :internal_entity_type, :internal_entity_id, :external_system,
                :external_entity_type, :external_entity_id
            WHERE NOT EXISTS (
                SELECT 1 FROM external_references
                WHERE external_system = :external_system
                  AND internal_entity_type = :internal_entity_type
                  AND external_entity_type = :external_entity_type
                  AND external_entity_id = :external_entity_id
            )
        """)
        await self._conn.execute(
            query,
            {
                "internal_entity_type": self._INTERNAL_ENTITY_TYPE,
                "internal_entity_id": contact_id,
                "external_system": self._integration_source,
                "external_entity_type": self._EXTERNAL_ENTITY_TYPE,
                "external_entity_id": person_id,
            },
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
