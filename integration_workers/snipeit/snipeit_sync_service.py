"""
Snipe-IT Sync Service — orchestrates gear item and maintenance import.

Fetches assets and maintenance records from the Snipe-IT API, transforms
them using ``SnipeItDataTransformer`` / ``SnipeItMaintenanceTransformer``,
and upserts them into the database. Sync state is tracked via ``SyncMetadata``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import structlog
from core_shared.models.journals.calendar_info import event_date_in_timezone
from sqlalchemy import text

from snipeit_api_client import SnipeItAPIClient, SnipeItAPIError
from snipeit_data_transformer import SnipeItDataTransformer
from snipeit_maintenance_transformer import SnipeItMaintenanceTransformer
from snipeit_rate_limiter import SnipeItRateLimitError

logger = structlog.get_logger(__name__)

# Maximum assets per Snipe-IT API page
_PAGE_SIZE = 50


def _resolve_zone(*candidates: object) -> str | None:
    """Return the first candidate naming a zone ``ZoneInfo`` can load, else ``None``.

    Pass the event's zone before the user's: journal dates are read in the
    event's zone when it records one, the user's otherwise, and UTC when neither
    is usable. Settings are user input and a row column may be absent, so
    anything that is not a loadable zone name is skipped rather than trusted.
    """
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate:
            continue
        try:
            ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
        return candidate
    return None


def _local_date(value: date | datetime | str | None, zone: str | None) -> date | None:
    """Return the calendar date ``value`` falls on in ``zone``.

    Journal date ranges are stored as the UTC instant of a *local* midnight, so
    taking the date of the stored UTC value lands a day early east of UTC.
    Plain dates are already calendar dates; strings are read by their ISO date
    prefix. Returns ``None`` for missing or unparseable input.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return event_date_in_timezone(value, zone)
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _format_date_for_snipeit(
    value: date | datetime | str | None, zone: str | None
) -> str | None:
    """Format ``value`` as the ``YYYY-MM-DD`` local date the Snipe-IT API takes."""
    local = _local_date(value, zone)
    return local.isoformat() if local else None


def _journal_zone(journal_row: Any) -> str | None:
    """Return the zone a journal row's dates are read in (event, then user)."""
    return _resolve_zone(
        getattr(journal_row, "event_timezone", None),
        getattr(journal_row, "user_timezone", None),
    )


async def _fetch_journal_row(session: Any, journal_id: int) -> Any:
    """Fetch a journal's title, content and dates, with the zones they are read in."""
    result = await session.execute(
        text("""
            SELECT j.title, j.content,
                   j.event_date_range_start, j.event_date_range_end,
                   jci.timezone AS event_timezone,
                   us.timezone AS user_timezone
            FROM journals j
            LEFT JOIN journal_calendar_info jci ON jci.journal_id = j.id
            LEFT JOIN user_settings us ON us.user_id = j.user_id
            WHERE j.id = :journal_id
        """),
        {"journal_id": journal_id},
    )
    return result.fetchone()


# UTC-12, the last zone to reach each date: no server's date is behind it.
_EARLIEST_ZONE = ZoneInfo("Etc/GMT+12")


def _snipeit_checkin_at(
    local_checkin: date | None, *, now: datetime | None = None
) -> date | None:
    """Return the historical ``checkin_at`` to send Snipe-IT, or ``None`` for "now".

    Snipe-IT compares ``checkin_at`` with its own server date, whose zone we do
    not know, and must never be sent a date it reads as the future. A date is
    only sent once it has passed at UTC-12, by which point it has passed on
    every server; a more recent return is stamped at the server's time instead.
    """
    if local_checkin is None:
        return None
    earliest_today = (now or datetime.now(tz=UTC)).astimezone(_EARLIEST_ZONE).date()
    return local_checkin if local_checkin < earliest_today else None


def _checkout_asset_id(external_id: object) -> int | None:
    """Return the asset id in a ``snipeit_checkout:{asset}:{journal}`` external id."""
    try:
        return int(str(external_id).split(":")[1])
    except (ValueError, IndexError):
        return None


def _usage_period_has_ended(
    value: date | datetime | str | None, *, now: datetime | None = None
) -> bool:
    """Return ``True`` if the usage period end ``value`` is in the past.

    Compares full timestamps against ``now`` (consistent with the periodic
    sweep's ``COALESCE(...) < now()`` query), so a check-in time earlier *today*
    is correctly treated as past — a date-only comparison would leave the asset
    checked out until the next calendar day. Naive datetimes are assumed UTC.
    Returns ``False`` for falsy/unparseable inputs.
    """
    if value is None:
        return False
    now = now or datetime.now(tz=UTC)
    # ``datetime`` must be checked before ``date`` (datetime subclasses date).
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value < now
    if isinstance(value, date):
        return value < now.date()
    # String fallback: only a valid ISO date prefix is comparable; anything
    # else is treated as not-past rather than risking a lexicographic mishit.
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except ValueError:
        return False
    return parsed < now.date()


# Internal signalling exceptions
class _AssetSkipped(Exception):
    """Raised when an asset was already imported (dedup)."""


class _AssetFailed(Exception):
    """Raised when an asset failed after all retries."""


class _MaintenanceSkipped(Exception):
    """Raised when a maintenance record was already imported (dedup)."""


class _MaintenanceFailed(Exception):
    """Raised when a maintenance record failed after all retries."""


class SnipeItSyncInProgress(Exception):
    """Raised when another worker holds a journal's Snipe-IT checkout.

    That worker may be recording older dates than the event that met it, so the
    event must be retried rather than dropped; the stream consumer redelivers it.
    """


_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    ConnectionError,
    OSError,
)


def _is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, _TRANSIENT_EXCEPTIONS):
        return True
    if isinstance(exc, SnipeItAPIError) and exc.status_code >= 500:
        return True
    return False


_MAX_ASSET_RETRIES = 3
_RETRY_BACKOFF_BASE = 2.0

# Synthetic calendar UUID for Snipe-IT maintenance events.
# Generated deterministically: uuid5(NAMESPACE_URL, "snipeit:maintenance")
_SNIPEIT_MAINTENANCE_CALENDAR_ID = "d7e0f8a1-4b2c-5e3d-9a6f-1c8b7d5e4f3a"


class SnipeItSyncService:
    """Orchestrates Snipe-IT asset import into gear_items.

    Args:
        api_client: Authenticated ``SnipeItAPIClient``.
        user_id: Internal user ID that owns the Snipe-IT connection.
        snipeit_user_id: Optional Snipe-IT user ID to filter by assigned assets.
    """

    def __init__(
        self,
        api_client: SnipeItAPIClient,
        user_id: str,
        snipeit_user_id: str | None = None,
    ) -> None:
        self._api_client = api_client
        self._user_id = user_id
        self._snipeit_user_id = snipeit_user_id
        self._transformer = SnipeItDataTransformer()

    async def list_asset_batches(self) -> AsyncIterator[list[int]]:
        """Yield pages of Snipe-IT asset IDs for batch processing.

        Yields:
            Lists of Snipe-IT asset IDs, one list per API page.
        """
        page = 1
        while True:
            response = await self._api_client.list_assets(
                assigned_to_user_id=self._snipeit_user_id,
                page=page,
                per_page=_PAGE_SIZE,
            )

            if not response.rows:
                break

            asset_ids = [asset.id for asset in response.rows]
            logger.info(
                "Listed Snipe-IT asset batch",
                page=page,
                batch_size=len(asset_ids),
                total_expected=response.total,
            )
            yield asset_ids

            if page * _PAGE_SIZE >= response.total:
                break

            page += 1

        logger.info(
            "Finished listing asset batches",
            pages_fetched=page,
        )

    async def sync_asset_batch(
        self,
        asset_ids: list[int],
        session_factory: Any,
    ) -> dict[str, int]:
        """Process a batch of asset IDs, upserting gear_items.

        Args:
            asset_ids: Snipe-IT asset IDs to sync.
            session_factory: Async session factory for transactions.

        Returns:
            Dict with ``synced``, ``skipped``, and ``failed`` counts.
        """
        synced = 0
        skipped = 0
        failed = 0

        for asset_id in asset_ids:
            try:
                await self._sync_single_asset_with_retry(asset_id, session_factory)
                synced += 1
            except _AssetSkipped:
                skipped += 1
            except _AssetFailed:
                failed += 1

        logger.info(
            "Asset batch completed",
            batch_size=len(asset_ids),
            synced=synced,
            skipped=skipped,
            failed=failed,
        )
        return {"synced": synced, "skipped": skipped, "failed": failed}

    async def _sync_single_asset_with_retry(
        self,
        asset_id: int,
        session_factory: Any,
    ) -> None:
        last_exc: Exception | None = None
        external_id = str(asset_id)

        for attempt in range(1, _MAX_ASSET_RETRIES + 1):
            try:
                # Get the asset from API outside transaction
                asset = await self._api_client.get_asset(asset_id)
                transformed = self._transformer.transform(
                    asset=asset, user_id=self._user_id
                )

                async with session_factory() as session:
                    async with session.begin():
                        # Check existing metadata
                        result = await session.execute(
                            text("""
                                SELECT version_hash, internal_uuid
                                FROM sync_metadata
                                WHERE integration_source = 'snipeit'
                                  AND external_id = :external_id
                                FOR UPDATE
                            """),
                            {"external_id": external_id},
                        )
                        existing_meta = result.fetchone()

                        if (
                            existing_meta
                            and existing_meta.version_hash == transformed.version_hash
                        ):
                            logger.debug(
                                "Skipping unchanged Snipe-IT asset",
                                asset_id=asset_id,
                            )
                            raise _AssetSkipped

                        # Upsert gear item
                        gear_id = (
                            existing_meta.internal_uuid
                            if existing_meta and existing_meta.internal_uuid
                            else transformed.gear_item.id
                        )

                        await session.execute(
                            text("""
                                INSERT INTO gear_items (
                                    id, user_id, name, model, serial_number,
                                    purchase_date, manufacturer, updated_at
                                ) VALUES (
                                    :id, :user_id, :name, :model, :serial_number,
                                    :purchase_date, :manufacturer, now()
                                )
                                ON CONFLICT (id) DO UPDATE SET
                                    name = EXCLUDED.name,
                                    model = EXCLUDED.model,
                                    serial_number = EXCLUDED.serial_number,
                                    purchase_date = EXCLUDED.purchase_date,
                                    manufacturer = EXCLUDED.manufacturer,
                                    updated_at = now()
                                WHERE gear_items.user_id = EXCLUDED.user_id
                            """),
                            {
                                "id": gear_id,
                                "user_id": self._user_id,
                                "name": transformed.gear_item.name,
                                "model": transformed.gear_item.model,
                                "serial_number": transformed.gear_item.serial_number,
                                "purchase_date": transformed.gear_item.purchase_date,
                                "manufacturer": transformed.gear_item.manufacturer,
                            },
                        )

                        await session.execute(
                            text("""
                                INSERT INTO sync_metadata
                                    (internal_uuid, integration_source, external_id, last_synced_at,
                                     version_hash, sync_status, error_message, retry_count,
                                     created_at, updated_at)
                                VALUES
                                    (:internal_uuid, 'snipeit', :external_id, now(),
                                     :version_hash, 'success', NULL, 0,
                                     now(), now())
                                ON CONFLICT (integration_source, external_id)
                                DO UPDATE SET
                                    internal_uuid = EXCLUDED.internal_uuid,
                                    last_synced_at = EXCLUDED.last_synced_at,
                                    version_hash = EXCLUDED.version_hash,
                                    sync_status = EXCLUDED.sync_status,
                                    error_message = EXCLUDED.error_message,
                                    retry_count = 0,
                                    updated_at = EXCLUDED.updated_at
                            """),
                            {
                                "external_id": external_id,
                                "version_hash": transformed.version_hash,
                                "internal_uuid": gear_id,
                            },
                        )
                return

            except _AssetSkipped:
                raise
            except (SnipeItRateLimitError, Exception) as exc:
                if not _is_transient_error(exc) and not isinstance(
                    exc, SnipeItRateLimitError
                ):
                    logger.warning(
                        "Non-transient error syncing Snipe-IT asset",
                        asset_id=asset_id,
                        attempt=attempt,
                        exc_info=True,
                    )

                    # Log failure in metadata if possible
                    try:
                        async with session_factory() as session:
                            async with session.begin():
                                await session.execute(
                                    text("""
                                        INSERT INTO sync_metadata
                                            (integration_source, external_id, last_synced_at,
                                             version_hash, sync_status, error_message, retry_count,
                                             created_at, updated_at)
                                        VALUES
                                            ('snipeit', :external_id, now(),
                                             '', 'failed', :error_message, 0,
                                             now(), now())
                                        ON CONFLICT (integration_source, external_id)
                                        DO UPDATE SET
                                            last_synced_at = EXCLUDED.last_synced_at,
                                            sync_status = EXCLUDED.sync_status,
                                            error_message = EXCLUDED.error_message,
                                            retry_count = sync_metadata.retry_count + 1,
                                            updated_at = EXCLUDED.updated_at
                                    """),
                                    {
                                        "external_id": external_id,
                                        "error_message": str(exc),
                                    },
                                )
                    except Exception:  # noqa: BLE001
                        pass

                    raise _AssetFailed from exc

                last_exc = exc
                if isinstance(exc, SnipeItRateLimitError):
                    raise  # Bubble up to ARQ

                if attempt < _MAX_ASSET_RETRIES:
                    backoff = _RETRY_BACKOFF_BASE**attempt
                    await asyncio.sleep(backoff)

        logger.error(
            "Failed to sync asset after retries",
            asset_id=asset_id,
            error=str(last_exc),
        )
        raise _AssetFailed from last_exc

    async def push_asset_update(
        self,
        gear_item_id: str,
        changed_fields: dict[str, Any],
        session_factory: Any,
    ) -> None:
        """Push local gear item changes to Snipe-IT.

        Args:
            gear_item_id: Internal gear item UUID.
            changed_fields: Dictionary of field name to (old, new) array/tuple.
            session_factory: Async session factory for DB queries.
        """
        async with session_factory() as session:
            # 1. Get sync metadata for this gear item
            result = await session.execute(
                text("""
                    SELECT external_id, version_hash
                    FROM sync_metadata
                    WHERE integration_source = 'snipeit'
                      AND internal_uuid = :internal_uuid
                    FOR UPDATE
                """),
                {"internal_uuid": gear_item_id},
            )
            meta = result.fetchone()

            if not meta:
                logger.debug(
                    "Skipping Snipe-IT export, no sync metadata found",
                    gear_item_id=gear_item_id,
                )
                return

            external_id = meta.external_id
            local_version_hash = meta.version_hash

        # 2. Fetch the current asset from Snipe-IT to verify hash
        try:
            asset = await self._api_client.get_asset(int(external_id))
        except SnipeItAPIError as exc:
            if exc.status_code == 404:
                logger.warning(
                    "Snipe-IT asset not found during export",
                    gear_item_id=gear_item_id,
                    external_id=external_id,
                )
                return
            raise

        transformed = self._transformer.transform(asset=asset, user_id=self._user_id)

        # 3. Check for conflict
        if transformed.version_hash != local_version_hash:
            logger.info(
                "Snipe-IT export conflict: remote asset changed since last sync. Skipping update.",
                gear_item_id=gear_item_id,
                external_id=external_id,
            )
            return

        # 4. Map changed fields to Snipe-IT API payload
        payload = {}
        if "name" in changed_fields:
            payload["name"] = changed_fields["name"][1]
        if "serial_number" in changed_fields:
            payload["serial"] = changed_fields["serial_number"][1]
        if "purchase_date" in changed_fields:
            new_date = changed_fields["purchase_date"][1]
            payload["purchase_date"] = new_date if new_date is not None else ""

        if not payload:
            logger.debug(
                "No mapped fields changed for Snipe-IT export",
                gear_item_id=gear_item_id,
            )
            return

        # 5. Push the update
        updated_asset = await self._api_client.update_asset(int(external_id), payload)

        # 6. Update sync metadata with the new version hash
        updated_transformed = self._transformer.transform(
            asset=updated_asset, user_id=self._user_id
        )

        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        UPDATE sync_metadata
                        SET version_hash = :version_hash,
                            last_synced_at = now(),
                            updated_at = now()
                        WHERE integration_source = 'snipeit'
                          AND external_id = :external_id
                    """),
                    {
                        "version_hash": updated_transformed.version_hash,
                        "external_id": external_id,
                    },
                )

        logger.info(
            "Successfully pushed gear item update to Snipe-IT",
            gear_item_id=gear_item_id,
            external_id=external_id,
        )

    # -- Maintenance Sync Methods ------------------------------------------

    async def list_maintenance_batches(self) -> AsyncIterator[list[int]]:
        """Yield pages of Snipe-IT maintenance IDs for batch processing.

        Yields:
            Lists of Snipe-IT maintenance IDs, one list per API page.
        """
        page = 1
        while True:
            response = await self._api_client.list_maintenances(
                page=page,
                per_page=_PAGE_SIZE,
            )

            if not response.rows:
                break

            maintenance_ids = [m.id for m in response.rows]
            logger.info(
                "Listed Snipe-IT maintenance batch",
                page=page,
                batch_size=len(maintenance_ids),
                total_expected=response.total,
            )
            yield maintenance_ids

            if page * _PAGE_SIZE >= response.total:
                break

            page += 1

        logger.info(
            "Finished listing maintenance batches",
            pages_fetched=page,
        )

    async def sync_maintenance_batch(
        self,
        maintenance_ids: list[int],
        session_factory: Any,
    ) -> dict[str, int]:
        """Process a batch of maintenance IDs, creating outbox events.

        Args:
            maintenance_ids: Snipe-IT maintenance IDs to sync.
            session_factory: Async session factory for transactions.

        Returns:
            Dict with ``synced``, ``skipped``, and ``failed`` counts.
        """
        synced = 0
        skipped = 0
        failed = 0

        for maintenance_id in maintenance_ids:
            try:
                await self._sync_single_maintenance(maintenance_id, session_factory)
                synced += 1
            except _MaintenanceSkipped:
                skipped += 1
            except _MaintenanceFailed:
                failed += 1
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Unexpected error syncing maintenance record",
                    maintenance_id=maintenance_id,
                    exc_info=True,
                )
                failed += 1

        logger.info(
            "Maintenance batch completed",
            batch_size=len(maintenance_ids),
            synced=synced,
            skipped=skipped,
            failed=failed,
        )
        return {"synced": synced, "skipped": skipped, "failed": failed}

    async def _sync_single_maintenance(
        self,
        maintenance_id: int,
        session_factory: Any,
    ) -> None:
        """Fetch, transform, and create an outbox event for a maintenance record.

        1. Fetch maintenance from the API.
        2. Look up the internal gear_item_id from sync_metadata for the asset.
        3. Transform into journal data.
        4. Check for existing sync_metadata (dedup via version_hash).
        5. Create outbox event (journal_event.created or .updated).
        6. Update sync_metadata.
        """
        external_id = f"snipeit_maint:{maintenance_id}"

        maintenance = await self._api_client.get_maintenance(maintenance_id)

        async with session_factory() as session:
            async with session.begin():
                # Look up internal gear_item_id for this asset
                if maintenance.asset_id is None:
                    logger.warning(
                        "Skipping maintenance: no asset_id in API response",
                        maintenance_id=maintenance_id,
                    )
                    raise _MaintenanceSkipped
                asset_external_id = str(maintenance.asset_id)
                asset_result = await session.execute(
                    text("""
                        SELECT internal_uuid
                        FROM sync_metadata
                        WHERE integration_source = 'snipeit'
                          AND external_id = :external_id
                    """),
                    {"external_id": asset_external_id},
                )
                asset_meta = asset_result.fetchone()

                if not asset_meta or not asset_meta.internal_uuid:
                    logger.warning(
                        "Skipping maintenance: gear item not yet synced",
                        maintenance_id=maintenance_id,
                        asset_id=maintenance.asset_id,
                    )
                    raise _MaintenanceSkipped

                gear_item_id = str(asset_meta.internal_uuid)

                # Transform
                transformer = SnipeItMaintenanceTransformer()
                transformed = transformer.transform(
                    maintenance,
                    user_id=self._user_id,
                    gear_item_id=gear_item_id,
                )

                # Check existing metadata for dedup
                meta_result = await session.execute(
                    text("""
                        SELECT version_hash
                        FROM sync_metadata
                        WHERE integration_source = 'snipeit_maintenance'
                          AND external_id = :external_id
                        FOR UPDATE
                    """),
                    {"external_id": external_id},
                )
                existing_meta = meta_result.fetchone()

                if (
                    existing_meta
                    and existing_meta.version_hash == transformed.version_hash
                ):
                    logger.debug(
                        "Skipping unchanged Snipe-IT maintenance",
                        maintenance_id=maintenance_id,
                    )
                    raise _MaintenanceSkipped

                # Look up existing journal via external event links
                # (populated by JournalOutboxEventProcessor on creation)
                existing_journal_id: int | None = None
                if existing_meta:
                    link_result = await session.execute(
                        text("""
                            SELECT journal_id
                            FROM journal_external_event_links
                            WHERE external_event_id = :external_event_id
                              AND calendar_id = :calendar_id
                            LIMIT 1
                        """),
                        {
                            "external_event_id": external_id,
                            "calendar_id": _SNIPEIT_MAINTENANCE_CALENDAR_ID,
                        },
                    )
                    link_row = link_result.fetchone()
                    existing_journal_id = link_row.journal_id if link_row else None

                if existing_meta and existing_journal_id is None:
                    # An outbox event for creation was enqueued but hasn't been processed
                    # by the backend yet, so the external event link doesn't exist.
                    # We cannot emit an update without the journal ID, and emitting another
                    # create could duplicate the journal. Fail this record so it retries.
                    raise RuntimeError(
                        "Outbox creation event pending, cannot update yet"
                    )

                # Determine sync action
                sync_action = "updated" if existing_journal_id else "created"

                # Enrich journal_data with gear_maintenance_data and
                # journal_types for the outbox event processor
                journal_data = dict(transformed.journal_data)
                journal_data["gear_maintenance_data"] = (
                    transformed.gear_maintenance_data
                )
                journal_data["journal_types"] = ["GEAR_MAINTENANCE"]
                journal_data["version_hash"] = transformed.version_hash

                # Build calendar_info_data
                calendar_info_data: dict[str, Any] = {
                    "calendar_id": _SNIPEIT_MAINTENANCE_CALENDAR_ID,
                }

                # Create outbox event
                from core_shared.models.outbox import OutboxEvent

                event = OutboxEvent.create_journal_sync_event(
                    journal_data=journal_data,
                    calendar_info_data=calendar_info_data,
                    integration_source="snipeit_maintenance",
                    external_event_id=external_id,
                    calendar_id=_SNIPEIT_MAINTENANCE_CALENDAR_ID,
                    sync_action=sync_action,
                    existing_journal_id=existing_journal_id,
                )
                session.add(event)

                # Upsert sync_metadata
                await session.execute(
                    text("""
                        INSERT INTO sync_metadata
                            (integration_source, external_id, last_synced_at,
                             version_hash, sync_status, error_message,
                             retry_count, created_at, updated_at)
                        VALUES
                            ('snipeit_maintenance', :external_id, now(),
                             :version_hash, 'success', NULL, 0,
                             now(), now())
                        ON CONFLICT (integration_source, external_id)
                        DO UPDATE SET
                            last_synced_at = EXCLUDED.last_synced_at,
                            version_hash = EXCLUDED.version_hash,
                            sync_status = EXCLUDED.sync_status,
                            error_message = EXCLUDED.error_message,
                            retry_count = 0,
                            updated_at = EXCLUDED.updated_at
                    """),
                    {
                        "external_id": external_id,
                        "version_hash": transformed.version_hash,
                    },
                )

        logger.info(
            "Created outbox event for Snipe-IT maintenance",
            maintenance_id=maintenance_id,
            sync_action=sync_action,
        )

    # -- Outbound Maintenance Sync Methods ----------------------------------

    async def _fetch_journal_and_maintenance_data(
        self,
        journal_id: int,
        session_factory: Any,
    ) -> tuple[Any, Any, Any] | None:
        """Fetch journal, gear-maintenance, and asset-sync data for outbound push.

        Returns a ``(journal_row, maintenance_data_row, asset_sync_meta_row)``
        tuple, or ``None`` if any prerequisite is missing (logged and skipped).
        """
        async with session_factory() as session:
            # 1. Get journal data
            journal_row = await _fetch_journal_row(session, journal_id)
            if not journal_row:
                logger.debug(
                    "Skipping outbound maintenance push: journal not found",
                    journal_id=journal_id,
                )
                return None

            # 2. Get gear maintenance data
            maint_result = await session.execute(
                text("""
                    SELECT gear_item_id, maintenance_type
                    FROM journal_gear_maintenance_data
                    WHERE journal_id = :journal_id
                """),
                {"journal_id": journal_id},
            )
            maintenance_data_row = maint_result.fetchone()
            if not maintenance_data_row:
                logger.debug(
                    "Skipping outbound maintenance push: no gear maintenance data",
                    journal_id=journal_id,
                )
                return None

            # 3. Get asset sync metadata (gear_item → Snipe-IT asset ID)
            gear_item_id = str(maintenance_data_row.gear_item_id)
            asset_meta_result = await session.execute(
                text("""
                    SELECT external_id
                    FROM sync_metadata
                    WHERE integration_source = 'snipeit'
                      AND internal_uuid = :gear_item_id
                """),
                {"gear_item_id": gear_item_id},
            )
            asset_sync_meta_row = asset_meta_result.fetchone()
            if not asset_sync_meta_row:
                logger.debug(
                    "Skipping outbound maintenance push: gear item not synced to Snipe-IT",
                    journal_id=journal_id,
                    gear_item_id=gear_item_id,
                )
                return None

        return journal_row, maintenance_data_row, asset_sync_meta_row

    async def push_maintenance_create(
        self,
        journal_id: int,
        session_factory: Any,
    ) -> None:
        """Push a new GEAR_MAINTENANCE journal to Snipe-IT as a maintenance record.

        Args:
            journal_id: Internal journal ID.
            session_factory: Async session factory for DB queries.
        """
        data = await self._fetch_journal_and_maintenance_data(
            journal_id, session_factory
        )
        if not data:
            return

        journal_row, maintenance_data_row, asset_sync_meta_row = data

        # Check if already synced (prevent duplicates on retries)
        async with session_factory() as session:
            maint_meta_result = await session.execute(
                text("""
                    SELECT 1
                    FROM sync_metadata
                    WHERE integration_source = 'snipeit_maintenance'
                      AND internal_uuid = :journal_id
                """),
                {"journal_id": str(journal_id)},
            )
            if maint_meta_result.fetchone():
                logger.debug(
                    "Skipping maintenance create: already synced to Snipe-IT",
                    journal_id=journal_id,
                )
                return

        # Build Snipe-IT payload via reverse transformer
        payload = SnipeItMaintenanceTransformer.reverse_transform(
            title=journal_row.title or "",
            content=journal_row.content or "",
            maintenance_type=maintenance_data_row.maintenance_type
            or "routine maintenance",
            start_date=_format_date_for_snipeit(
                journal_row.event_date_range_start, _journal_zone(journal_row)
            ),
            end_date=_format_date_for_snipeit(
                journal_row.event_date_range_end, _journal_zone(journal_row)
            ),
        )

        try:
            snipeit_asset_id = int(asset_sync_meta_row.external_id)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid asset sync metadata external_id",
                external_id=asset_sync_meta_row.external_id,
                journal_id=journal_id,
            )
            return

        # POST to Snipe-IT
        try:
            created = await self._api_client.create_maintenance(
                asset_id=snipeit_asset_id,
                payload=payload,
            )
        except SnipeItAPIError as exc:
            if exc.status_code in (403, 404):
                logger.warning(
                    "Snipe-IT maintenance create failed (not found/forbidden)",
                    journal_id=journal_id,
                    snipeit_asset_id=snipeit_asset_id,
                    status_code=exc.status_code,
                )
                return
            raise

        # Save sync metadata: journal_id → snipeit_maint:{id}
        external_id = f"snipeit_maint:{created.id}"
        async with session_factory() as session:
            async with session.begin():
                version_hash = hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode()
                ).hexdigest()
                await session.execute(
                    text("""
                        INSERT INTO sync_metadata
                            (internal_uuid, integration_source, external_id,
                             last_synced_at, version_hash, sync_status,
                             error_message, retry_count, created_at, updated_at)
                        VALUES
                            (:internal_uuid, 'snipeit_maintenance', :external_id,
                             now(), :version_hash, 'success', NULL, 0, now(), now())
                        ON CONFLICT (integration_source, external_id)
                        DO UPDATE SET
                            internal_uuid = EXCLUDED.internal_uuid,
                            last_synced_at = EXCLUDED.last_synced_at,
                            version_hash = EXCLUDED.version_hash,
                            sync_status = EXCLUDED.sync_status,
                            updated_at = EXCLUDED.updated_at
                    """),
                    {
                        "internal_uuid": str(journal_id),
                        "external_id": external_id,
                        "version_hash": version_hash,
                    },
                )

        logger.info(
            "Successfully pushed new maintenance to Snipe-IT",
            journal_id=journal_id,
            snipeit_maintenance_id=created.id,
        )

    async def push_maintenance_update(
        self,
        journal_id: int,
        session_factory: Any,
    ) -> None:
        """Push an updated GEAR_MAINTENANCE journal to Snipe-IT.

        Args:
            journal_id: Internal journal ID.
            session_factory: Async session factory for DB queries.
        """
        data = await self._fetch_journal_and_maintenance_data(
            journal_id, session_factory
        )
        if not data:
            return

        journal_row, maintenance_data_row, asset_sync_meta_row = data

        # Look up existing maintenance sync metadata
        async with session_factory() as session:
            maint_meta_result = await session.execute(
                text("""
                    SELECT external_id
                    FROM sync_metadata
                    WHERE integration_source = 'snipeit_maintenance'
                      AND internal_uuid = :journal_id
                """),
                {"journal_id": str(journal_id)},
            )
            maint_sync_row = maint_meta_result.fetchone()

        if not maint_sync_row:
            logger.debug(
                "Skipping outbound maintenance update: no sync metadata",
                journal_id=journal_id,
            )
            return

        # Extract Snipe-IT maintenance ID from external_id format "snipeit_maint:{id}"
        external_id = maint_sync_row.external_id
        try:
            snipeit_maintenance_id = int(external_id.split(":")[1])
        except (IndexError, ValueError):
            logger.warning(
                "Invalid maintenance sync metadata external_id",
                external_id=external_id,
                journal_id=journal_id,
            )
            return

        # Build Snipe-IT payload
        payload = SnipeItMaintenanceTransformer.reverse_transform(
            title=journal_row.title or "",
            content=journal_row.content or "",
            maintenance_type=maintenance_data_row.maintenance_type
            or "routine maintenance",
            start_date=_format_date_for_snipeit(
                journal_row.event_date_range_start, _journal_zone(journal_row)
            ),
            end_date=_format_date_for_snipeit(
                journal_row.event_date_range_end, _journal_zone(journal_row)
            ),
        )

        # PATCH the Snipe-IT maintenance record
        try:
            await self._api_client.update_maintenance(snipeit_maintenance_id, payload)
        except SnipeItAPIError as exc:
            if exc.status_code in (403, 404):
                logger.warning(
                    "Snipe-IT maintenance update failed (not found/forbidden)",
                    journal_id=journal_id,
                    snipeit_maintenance_id=snipeit_maintenance_id,
                    status_code=exc.status_code,
                )
                return
            raise

        # Update sync metadata with new version hash and sync timestamp
        version_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        UPDATE sync_metadata
                        SET version_hash = :version_hash,
                            last_synced_at = now(),
                            updated_at = now()
                        WHERE integration_source = 'snipeit_maintenance'
                          AND internal_uuid = :journal_id
                    """),
                    {
                        "version_hash": version_hash,
                        "journal_id": str(journal_id),
                    },
                )

        logger.info(
            "Successfully pushed maintenance update to Snipe-IT",
            journal_id=journal_id,
            snipeit_maintenance_id=snipeit_maintenance_id,
        )

    # -- Outbound Checkout Sync Methods -------------------------------------

    async def _fetch_journal_and_gear_usage_data(
        self,
        journal_id: int,
        session_factory: Any,
    ) -> tuple[Any, Any, Any] | None:
        """Fetch journal, gear-usage, and asset-sync data for outbound checkout.

        Returns a ``(journal_row, usage_data_row, asset_sync_meta_row)``
        tuple, or ``None`` if any prerequisite is missing (logged and skipped).
        """
        async with session_factory() as session:
            # 1. Get journal data
            journal_row = await _fetch_journal_row(session, journal_id)
            if not journal_row:
                logger.debug(
                    "Skipping outbound checkout push: journal not found",
                    journal_id=journal_id,
                )
                return None

            # 2. Get gear usage data
            usage_result = await session.execute(
                text("""
                    SELECT gear_item_id, checkout_date, checkin_date
                    FROM journal_gear_usage_data
                    WHERE journal_id = :journal_id
                """),
                {"journal_id": journal_id},
            )
            usage_data_row = usage_result.fetchone()
            if not usage_data_row:
                logger.debug(
                    "Skipping outbound checkout push: no gear usage data",
                    journal_id=journal_id,
                )
                return None

            # 3. Get asset sync metadata (gear_item → Snipe-IT asset ID)
            gear_item_id = str(usage_data_row.gear_item_id)
            asset_meta_result = await session.execute(
                text("""
                    SELECT external_id
                    FROM sync_metadata
                    WHERE integration_source = 'snipeit'
                      AND internal_uuid = :gear_item_id
                """),
                {"gear_item_id": gear_item_id},
            )
            asset_sync_meta_row = asset_meta_result.fetchone()
            if not asset_sync_meta_row:
                logger.debug(
                    "Skipping outbound checkout push: gear item not synced to Snipe-IT",
                    journal_id=journal_id,
                    gear_item_id=gear_item_id,
                )
                return None

        return journal_row, usage_data_row, asset_sync_meta_row

    async def push_checkout_create(
        self,
        journal_id: int,
        session_factory: Any,
    ) -> None:
        """Push a new GEAR_USAGE journal to Snipe-IT as an asset checkout.

        Args:
            journal_id: Internal journal ID.
            session_factory: Async session factory for DB queries.

        Raises:
            SnipeItSyncInProgress: Another worker holds this journal's checkout;
                the event must be retried once that checkout finishes.
        """
        data = await self._fetch_journal_and_gear_usage_data(
            journal_id, session_factory
        )
        if not data:
            return

        journal_row, usage_data_row, asset_sync_meta_row = data

        if not self._snipeit_user_id:
            logger.warning(
                "Skipping checkout create: snipeit_user_id is not configured",
                journal_id=journal_id,
            )
            return

        try:
            snipeit_asset_id = int(asset_sync_meta_row.external_id)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid asset sync metadata external_id",
                external_id=asset_sync_meta_row.external_id,
                journal_id=journal_id,
            )
            return

        external_id = f"snipeit_checkout:{snipeit_asset_id}:{journal_id}"

        previous_asset_id: int | None = None

        # Check if already synced and acquire a distributed lock by marking as pending
        async with session_factory() as session:
            async with session.begin():
                checkout_meta_result = await session.execute(
                    text("""
                        SELECT sync_status, external_id,
                               extract(epoch from (now() - updated_at)) as age_seconds
                        FROM sync_metadata
                        WHERE integration_source = 'snipeit_checkout'
                          AND internal_uuid = :journal_id
                        FOR UPDATE SKIP LOCKED
                    """),
                    {"journal_id": str(journal_id)},
                )
                row = checkout_meta_result.fetchone()
                if row:
                    if row.sync_status == "success":
                        logger.debug(
                            "Skipping checkout create: already synced to Snipe-IT",
                            journal_id=journal_id,
                        )
                        return
                    if (
                        row.sync_status == "pending"
                        and row.age_seconds is not None
                        and row.age_seconds < 300
                    ):
                        raise SnipeItSyncInProgress(
                            f"Checkout of journal {journal_id} is in flight"
                        )

                    previous_asset_id = _checkout_asset_id(row.external_id)
                    await session.execute(
                        text("""
                            UPDATE sync_metadata
                            SET sync_status = 'pending', updated_at = now()
                            WHERE integration_source = 'snipeit_checkout' AND internal_uuid = :journal_id
                        """),
                        # The row keeps the previous attempt's asset until that
                        # asset has been dealt with (see below).
                        {"journal_id": str(journal_id)},
                    )
                else:
                    insert_result = await session.execute(
                        text("""
                            INSERT INTO sync_metadata
                                (internal_uuid, integration_source, external_id,
                                 last_synced_at, version_hash, sync_status,
                                 error_message, retry_count, created_at, updated_at)
                            VALUES
                                (:internal_uuid, 'snipeit_checkout', :external_id,
                                 now(), 'PENDING', 'pending', NULL, 0, now(), now())
                            ON CONFLICT (integration_source, external_id) DO NOTHING
                            RETURNING id
                        """),
                        {
                            "internal_uuid": str(journal_id),
                            "external_id": external_id,
                        },
                    )
                    if not insert_result.fetchone():
                        raise SnipeItSyncInProgress(
                            f"Checkout of journal {journal_id} is locked by another worker"
                        )

        # Resolve dates: buffer dates take precedence, fall back to journal range
        checkout_date = (
            usage_data_row.checkout_date or journal_row.event_date_range_start
        )
        checkin_date = usage_data_row.checkin_date or journal_row.event_date_range_end

        if not checkout_date or not checkin_date:
            logger.warning(
                "Missing required dates for gear usage checkout",
                journal_id=journal_id,
                has_checkout=bool(checkout_date),
                has_checkin=bool(checkin_date),
            )
            # Unlock the pending status so it can be retried when data is fixed
            await self._unlock_pending_checkout(
                journal_id, session_factory, "Missing required dates"
            )
            return

        if checkin_date < checkout_date:
            logger.warning(
                "Invalid date range for gear usage checkout: checkin before checkout",
                journal_id=journal_id,
                checkout_date=str(checkout_date),
                checkin_date=str(checkin_date),
            )
            await self._unlock_pending_checkout(
                journal_id, session_factory, "Invalid date range"
            )
            return

        zone = _journal_zone(journal_row)
        checkout_at = _format_date_for_snipeit(checkout_date, zone)
        expected_checkin = _format_date_for_snipeit(checkin_date, zone)

        # Build checkout payload
        payload: dict[str, Any] = {
            "assigned_user": self._snipeit_user_id,
            "checkout_to_type": "user",
            "checkout_at": checkout_at,
            "expected_checkin": expected_checkin,
        }
        if journal_row.title:
            payload["note"] = journal_row.title

        # POST to Snipe-IT
        try:
            if previous_asset_id not in (None, snipeit_asset_id):
                await self._return_previous_asset(
                    previous_asset_id,
                    journal_id=journal_id,
                    session_factory=session_factory,
                )
                # Only now may the row forget the previous asset: had the return
                # failed, the retry must still derive it from the row.
                await self._rekey_checkout(journal_id, external_id, session_factory)
            await self._api_client.checkout_asset(
                asset_id=snipeit_asset_id,
                payload=payload,
            )
        except SnipeItAPIError as exc:
            # Handle 403/404 specific errors gracefully
            if exc.status_code in (403, 404):
                logger.warning(
                    "Snipe-IT checkout create failed (not found/forbidden)",
                    journal_id=journal_id,
                    snipeit_asset_id=snipeit_asset_id,
                    status_code=exc.status_code,
                )
                await self._unlock_pending_checkout(
                    journal_id,
                    session_factory,
                    f"API Error {exc.status_code}",
                )
                return

            # For 500s or other errors, unlock and raise so it retries
            await self._unlock_pending_checkout(
                journal_id, session_factory, str(exc)[:255]
            )
            raise
        except Exception as exc:
            await self._unlock_pending_checkout(
                journal_id, session_factory, str(exc)[:255]
            )
            raise

        # Save sync metadata: journal_id → snipeit_checkout
        # Note: Snipe-IT does not support an idempotency key on checkouts.
        # By using a pending lock beforehand, we mitigate concurrent processing double-POSTs.
        version_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        UPDATE sync_metadata
                        SET version_hash = :version_hash,
                            last_synced_at = now(),
                            sync_status = 'success',
                            error_message = NULL,
                            reference_data = :reference_data,
                            updated_at = now()
                        WHERE integration_source = 'snipeit_checkout'
                          AND internal_uuid = :internal_uuid
                          AND external_id = :external_id
                    """),
                    {
                        "internal_uuid": str(journal_id),
                        "external_id": external_id,
                        "version_hash": version_hash,
                        "reference_data": json.dumps(
                            {
                                "checkout_at": checkout_at,
                                "expected_checkin": expected_checkin,
                            }
                        ),
                    },
                )

        logger.info(
            "Successfully pushed checkout to Snipe-IT",
            journal_id=journal_id,
            snipeit_asset_id=snipeit_asset_id,
        )

        # If the usage period is already over (e.g. logging a past trip), the
        # asset must not stay checked out — immediately record the check-in.
        if _usage_period_has_ended(checkin_date):
            await self.push_checkin_create(
                journal_id=journal_id,
                session_factory=session_factory,
                note=f"Usage period {checkout_at} to {expected_checkin}",
                checkin_at=_snipeit_checkin_at(_local_date(checkin_date, zone)),
            )

    async def _return_previous_asset(
        self, asset_id: int | None, *, journal_id: int, session_factory: Any
    ) -> None:
        """Check in an asset an earlier, failed checkout attempt may have checked out.

        A checkout whose response was lost is recorded as failed even though
        Snipe-IT may have checked the asset out. Once the journal moves to another
        gear item that asset would stay out with no sync row left to return it,
        so it is returned first — but only while Snipe-IT shows it checked out to
        the mapped user and no other journal may hold it. A pending or failed
        attempt by another journal counts as holding it, since that attempt may
        have checked the asset out too; leaving it out is recoverable, returning
        an asset still in use is not.
        """
        if asset_id is None:
            return
        try:
            asset = await self._api_client.get_asset(asset_id)
        except SnipeItAPIError as exc:
            if exc.status_code in (403, 404):
                return
            raise
        assignee = asset.assigned_to
        if (
            assignee is None
            or assignee.type != "user"
            or str(assignee.id) != str(self._snipeit_user_id)
        ):
            return

        async with session_factory() as session:
            held_elsewhere = await session.execute(
                text("""
                    SELECT 1
                    FROM sync_metadata co
                    LEFT JOIN sync_metadata ci
                        ON ci.integration_source = 'snipeit_checkin'
                        AND ci.internal_uuid = co.internal_uuid
                        AND ci.sync_status = 'success'
                    WHERE co.integration_source = 'snipeit_checkout'
                      AND co.external_id LIKE :asset_prefix
                      AND co.internal_uuid <> :journal_id
                      AND (co.sync_status <> 'success' OR ci.id IS NULL)
                    LIMIT 1
                """),
                {
                    "asset_prefix": f"snipeit_checkout:{asset_id}:%",
                    "journal_id": str(journal_id),
                },
            )
            if held_elsewhere.fetchone():
                return

        await self._api_client.checkin_asset(
            asset_id=asset_id,
            payload={"note": "Gear usage journal moved to another gear item"},
        )
        logger.info(
            "Returned the asset of a superseded checkout attempt",
            journal_id=journal_id,
            snipeit_asset_id=asset_id,
        )

    async def _rekey_checkout(
        self, journal_id: int, external_id: str, session_factory: Any
    ) -> None:
        """Point a journal's checkout row at the asset now being checked out."""
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        UPDATE sync_metadata
                        SET external_id = :external_id, updated_at = now()
                        WHERE integration_source = 'snipeit_checkout'
                          AND internal_uuid = :internal_uuid
                    """),
                    {"internal_uuid": str(journal_id), "external_id": external_id},
                )

    async def _unlock_pending_checkout(
        self,
        journal_id: int,
        session_factory: Any,
        error_message: str,
    ) -> None:
        """Mark a pending checkout sync as failed to release the lock for future retries.

        The row is found by journal, not external id: it may still be keyed to a
        previous attempt's asset.
        """
        try:
            async with session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text("""
                            UPDATE sync_metadata
                            SET sync_status = 'failed',
                                updated_at = now(),
                                error_message = :error_message
                            WHERE integration_source = 'snipeit_checkout'
                              AND internal_uuid = :internal_uuid
                        """),
                        {
                            "internal_uuid": str(journal_id),
                            "error_message": error_message,
                        },
                    )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to unlock pending checkout",
                journal_id=journal_id,
                error=str(exc),
            )

    # -- Outbound Checkin Sync Methods --------------------------------------

    async def push_checkin_create(
        self,
        journal_id: int,
        session_factory: Any,
        note: str | None = None,
        checkin_at: date | None = None,
    ) -> bool:
        """Return (check in) the asset previously checked out for a GEAR_USAGE journal.

        The asset is resolved from the existing ``snipeit_checkout`` sync metadata
        row for ``journal_id`` rather than the journal/gear-usage tables, so this
        still works after the journal (and its cascade-deleted usage data) is gone
        — e.g. when triggered by ``JournalDeleted``. A no-op when no successful
        checkout was recorded. Idempotency is enforced via a ``snipeit_checkin``
        sync metadata row, mirroring :meth:`push_checkout_create`.

        Args:
            journal_id: Internal journal ID whose checkout should be reversed.
            session_factory: Async session factory for DB queries.
            note: Optional note recorded on the Snipe-IT check-in (the usage
                window, when known).
            checkin_at: The local date the asset was returned. Sent as Snipe-IT's
                ``checkin_at`` so the check-in is backdated; ``None`` lets
                Snipe-IT stamp the check-in now (e.g. on journal deletion).

        Returns:
            ``True`` only when a check-in was actively performed against Snipe-IT;
            ``False`` for any no-op (no checkout, already checked in, lock
            contention) or terminal non-retryable outcome (403/404).
        """
        # 1. Resolve the asset and confirm a successful checkout exists.
        async with session_factory() as session:
            checkout_result = await session.execute(
                text("""
                    SELECT external_id, sync_status
                    FROM sync_metadata
                    WHERE integration_source = 'snipeit_checkout'
                      AND internal_uuid = :journal_id
                """),
                {"journal_id": str(journal_id)},
            )
            checkout_row = checkout_result.fetchone()

        if not checkout_row or checkout_row.sync_status != "success":
            logger.debug(
                "Skipping checkin: no successful checkout recorded for journal",
                journal_id=journal_id,
            )
            return False

        snipeit_asset_id = _checkout_asset_id(checkout_row.external_id)
        if snipeit_asset_id is None:
            logger.warning(
                "Invalid checkout sync metadata external_id; cannot derive asset",
                external_id=checkout_row.external_id,
                journal_id=journal_id,
            )
            return False

        external_id = f"snipeit_checkin:{snipeit_asset_id}:{journal_id}"

        # 2. Acquire a distributed lock by marking the checkin as pending.
        async with session_factory() as session:
            async with session.begin():
                # Key on (integration_source, external_id) — the table's unique
                # key — so the lock and finalize always target exactly this row.
                checkin_meta_result = await session.execute(
                    text("""
                        SELECT sync_status, extract(epoch from (now() - updated_at)) as age_seconds
                        FROM sync_metadata
                        WHERE integration_source = 'snipeit_checkin'
                          AND external_id = :external_id
                        FOR UPDATE SKIP LOCKED
                    """),
                    {"external_id": external_id},
                )
                row = checkin_meta_result.fetchone()
                if row:
                    if row.sync_status == "success":
                        logger.debug(
                            "Skipping checkin: already checked in",
                            journal_id=journal_id,
                        )
                        return False
                    if (
                        row.sync_status == "pending"
                        and row.age_seconds is not None
                        and row.age_seconds < 300
                    ):
                        logger.debug(
                            "Skipping checkin: currently processing in another worker",
                            journal_id=journal_id,
                        )
                        return False

                    await session.execute(
                        text("""
                            UPDATE sync_metadata
                            SET sync_status = 'pending', updated_at = now()
                            WHERE integration_source = 'snipeit_checkin' AND external_id = :external_id
                        """),
                        {"external_id": external_id},
                    )
                else:
                    insert_result = await session.execute(
                        text("""
                            INSERT INTO sync_metadata
                                (internal_uuid, integration_source, external_id,
                                 last_synced_at, version_hash, sync_status,
                                 error_message, retry_count, created_at, updated_at)
                            VALUES
                                (:internal_uuid, 'snipeit_checkin', :external_id,
                                 now(), 'PENDING', 'pending', NULL, 0, now(), now())
                            ON CONFLICT (integration_source, external_id) DO NOTHING
                            RETURNING id
                        """),
                        {
                            "internal_uuid": str(journal_id),
                            "external_id": external_id,
                        },
                    )
                    if not insert_result.fetchone():
                        logger.debug(
                            "Skipping checkin: locked by another process",
                            journal_id=journal_id,
                        )
                        return False

        # 3. Build the checkin payload and POST to Snipe-IT.
        payload: dict[str, Any] = {}
        if note:
            payload["note"] = note
        if checkin_at:
            payload["checkin_at"] = checkin_at.isoformat()

        try:
            await self._api_client.checkin_asset(
                asset_id=snipeit_asset_id,
                payload=payload,
            )
        except SnipeItAPIError as exc:
            # 403/404 is non-retryable: the asset is already returned / gone (404)
            # or we are not permitted to return it (403). Record a terminal
            # outcome so the periodic sweep and update reconcile stop re-attempting
            # it (a 'failed' row would be re-selected every sweep).
            if exc.status_code in (403, 404):
                logger.warning(
                    "Snipe-IT checkin failed (not found/forbidden); marking terminal",
                    journal_id=journal_id,
                    snipeit_asset_id=snipeit_asset_id,
                    status_code=exc.status_code,
                )
                await self._finalize_checkin(
                    journal_id,
                    external_id,
                    session_factory,
                    error_message=f"Terminal: API {exc.status_code}",
                    checkin_at=checkin_at,
                )
                return False

            await self._unlock_pending_checkin(
                journal_id, external_id, session_factory, str(exc)[:255]
            )
            raise
        except Exception as exc:
            await self._unlock_pending_checkin(
                journal_id, external_id, session_factory, str(exc)[:255]
            )
            raise

        # 4. Record the checkin as successful.
        await self._finalize_checkin(
            journal_id, external_id, session_factory, checkin_at=checkin_at
        )

        logger.info(
            "Successfully checked in asset to Snipe-IT",
            journal_id=journal_id,
            snipeit_asset_id=snipeit_asset_id,
        )
        return True

    async def _finalize_checkin(
        self,
        journal_id: int,
        external_id: str,
        session_factory: Any,
        error_message: str | None = None,
        checkin_at: date | None = None,
    ) -> None:
        """Mark a checkin sync row terminal (``success``) so it is not retried.

        Used both for a confirmed return and for non-retryable 403/404 outcomes
        (which carry an ``error_message`` for diagnostics). A terminal ``success``
        row removes the journal from the periodic sweep's selection.
        """
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        UPDATE sync_metadata
                        SET version_hash = 'CHECKED_IN',
                            last_synced_at = now(),
                            sync_status = 'success',
                            error_message = :error_message,
                            reference_data = :reference_data,
                            updated_at = now()
                        WHERE integration_source = 'snipeit_checkin'
                          AND internal_uuid = :internal_uuid
                          AND external_id = :external_id
                    """),
                    {
                        "internal_uuid": str(journal_id),
                        "external_id": external_id,
                        "error_message": error_message,
                        "reference_data": json.dumps(
                            {
                                "checkin_at": checkin_at.isoformat()
                                if checkin_at
                                else None
                            }
                        ),
                    },
                )

    async def _unlock_pending_checkin(
        self,
        journal_id: int,
        external_id: str,
        session_factory: Any,
        error_message: str,
    ) -> None:
        """Mark a pending checkin sync as failed to release the lock for future retries."""
        try:
            async with session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text("""
                            UPDATE sync_metadata
                            SET sync_status = 'failed',
                                updated_at = now(),
                                error_message = :error_message
                            WHERE integration_source = 'snipeit_checkin'
                              AND internal_uuid = :internal_uuid
                              AND external_id = :external_id
                        """),
                        {
                            "internal_uuid": str(journal_id),
                            "external_id": external_id,
                            "error_message": error_message,
                        },
                    )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to unlock pending checkin",
                journal_id=journal_id,
                error=str(exc),
            )

    async def reconcile_gear_usage(
        self,
        journal_id: int,
        session_factory: Any,
    ) -> None:
        """Reconcile a GEAR_USAGE journal's Snipe-IT state after an update.

        Desired state: the asset is checked out on the journal's local checkout
        date and, once the usage period has ended, checked in on its local
        check-in date. Snipe-IT's activity log cannot be edited, so history is
        only added where it is missing:

        - No successful checkout: create it (which checks the asset straight
          back in when the period is already past).
        - The checkout date changed after the asset was checked in: supersede
          the recorded pair and record a new checkout and check-in.
        - Otherwise: check the asset in once the period has ended. This is a
          no-op when already checked in, so a changed check-in date alone is not
          re-recorded.

        A checkout recorded before its dates were stored, or one whose check-in
        ended in a terminal 403/404 (the asset may still be out), is never
        superseded.
        """
        async with session_factory() as session:
            checkout_result = await session.execute(
                text("""
                    SELECT co.sync_status, co.reference_data,
                           ci.sync_status AS checkin_status,
                           ci.error_message AS checkin_error
                    FROM sync_metadata co
                    LEFT JOIN sync_metadata ci
                        ON ci.integration_source = 'snipeit_checkin'
                        AND ci.internal_uuid = co.internal_uuid
                    WHERE co.integration_source = 'snipeit_checkout'
                      AND co.internal_uuid = :journal_id
                """),
                {"journal_id": str(journal_id)},
            )
            checkout_row = checkout_result.fetchone()

        if not checkout_row or checkout_row.sync_status != "success":
            # No successful checkout yet — create it (handles immediate checkin).
            await self.push_checkout_create(
                journal_id=journal_id,
                session_factory=session_factory,
            )
            return

        data = await self._fetch_journal_and_gear_usage_data(
            journal_id, session_factory
        )
        if not data:
            return

        journal_row, usage_data_row, _ = data
        zone = _journal_zone(journal_row)
        checkout_date = (
            usage_data_row.checkout_date or journal_row.event_date_range_start
        )
        checkin_date = usage_data_row.checkin_date or journal_row.event_date_range_end

        recorded_checkout_at = self._recorded_checkout_at(checkout_row.reference_data)
        checkout_at = _format_date_for_snipeit(checkout_date, zone)
        checkout_date_changed = (
            recorded_checkout_at is not None
            and checkout_at is not None
            and recorded_checkout_at != checkout_at
        )
        if (
            checkout_date_changed
            and checkout_row.checkin_status == "success"
            and checkout_row.checkin_error is None
        ):
            if await self._supersede_checkout(
                journal_id=journal_id,
                recorded_reference=checkout_row.reference_data,
                session_factory=session_factory,
            ):
                await self.push_checkout_create(
                    journal_id=journal_id,
                    session_factory=session_factory,
                )
            return

        if _usage_period_has_ended(checkin_date):
            note = (
                f"Usage period {checkout_at} "
                f"to {_format_date_for_snipeit(checkin_date, zone)}"
            )
            await self.push_checkin_create(
                journal_id=journal_id,
                session_factory=session_factory,
                note=note,
                checkin_at=_snipeit_checkin_at(_local_date(checkin_date, zone)),
            )

    async def _supersede_checkout(
        self,
        *,
        journal_id: int,
        recorded_reference: str,
        session_factory: Any,
    ) -> bool:
        """Release a journal's recorded checkout and check-in so a new pair is made.

        The checkout row is reset to ``failed``, which :meth:`push_checkout_create`
        retries, and the check-in row is removed. The reset only matches while
        the row still holds ``recorded_reference``, so a concurrent update that
        read the same dates matches nothing and returns ``False`` instead of
        recording a second pair.
        """
        async with session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text("""
                        UPDATE sync_metadata
                        SET sync_status = 'failed',
                            error_message = 'Superseded: checkout date changed',
                            updated_at = now()
                        WHERE integration_source = 'snipeit_checkout'
                          AND internal_uuid = :journal_id
                          AND sync_status = 'success'
                          AND reference_data = :recorded_reference
                        RETURNING id
                    """),
                    {
                        "journal_id": str(journal_id),
                        "recorded_reference": recorded_reference,
                    },
                )
                if result.fetchone() is None:
                    logger.debug(
                        "Skipping checkout supersede: already superseded",
                        journal_id=journal_id,
                    )
                    return False
                await session.execute(
                    text("""
                        DELETE FROM sync_metadata
                        WHERE integration_source = 'snipeit_checkin'
                          AND internal_uuid = :journal_id
                    """),
                    {"journal_id": str(journal_id)},
                )

        logger.info(
            "Superseded Snipe-IT checkout after its checkout date changed",
            journal_id=journal_id,
        )
        return True

    @staticmethod
    def _recorded_checkout_at(reference_data: object) -> str | None:
        """Return the ``checkout_at`` a checkout sync row recorded, if any."""
        if not isinstance(reference_data, str):
            return None
        try:
            recorded = json.loads(reference_data)
        except ValueError:
            return None
        value = recorded.get("checkout_at") if isinstance(recorded, dict) else None
        return value if isinstance(value, str) else None


@dataclass(frozen=True)
class OverdueGearUsage:
    """A checked-out GEAR_USAGE journal whose usage period has ended.

    Dates are the local calendar dates the usage ran over, read in the journal's
    event timezone, else the user's.
    """

    journal_id: int
    checkout_at: date | None
    checkin_at: date

    @property
    def note(self) -> str:
        """The usage window recorded on the Snipe-IT check-in."""
        start = self.checkout_at.isoformat() if self.checkout_at else "unknown"
        return f"Usage period {start} to {self.checkin_at.isoformat()}"

    def snipeit_checkin_at(self, *, now: datetime | None = None) -> date | None:
        """The ``checkin_at`` to send Snipe-IT (``None`` while it may be today there)."""
        return _snipeit_checkin_at(self.checkin_at, now=now)


async def fetch_overdue_gear_usage(
    session_factory: Any, user_id: str
) -> list[OverdueGearUsage]:
    """Return a user's successful checkouts with no check-in whose period has ended.

    Drives the periodic check-in sweep. The resolved check-in instant is compared
    against ``now()``, matching :func:`_usage_period_has_ended`; the returned
    dates are local to the journal's event zone, else the user's zone.
    """
    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT j.id AS journal_id,
                       COALESCE(u.checkin_date, j.event_date_range_end) AS checkin_date,
                       COALESCE(u.checkout_date, j.event_date_range_start) AS checkout_date,
                       jci.timezone AS event_timezone,
                       us.timezone AS user_timezone
                FROM sync_metadata co
                JOIN journals j ON j.id = co.internal_uuid::integer
                JOIN journal_gear_usage_data u ON u.journal_id = j.id
                LEFT JOIN journal_calendar_info jci ON jci.journal_id = j.id
                LEFT JOIN user_settings us ON us.user_id = j.user_id
                LEFT JOIN sync_metadata ci
                    ON ci.integration_source = 'snipeit_checkin'
                    AND ci.internal_uuid = co.internal_uuid
                    AND ci.sync_status = 'success'
                WHERE co.integration_source = 'snipeit_checkout'
                  AND co.sync_status = 'success'
                  AND j.user_id = :user_id
                  AND ci.id IS NULL
                  AND COALESCE(u.checkin_date, j.event_date_range_end) < now()
                ORDER BY j.id
            """),
            {"user_id": user_id},
        )
        rows = result.fetchall()

    overdue: list[OverdueGearUsage] = []
    for row in rows:
        zone = _journal_zone(row)
        checkin_at = _local_date(row.checkin_date, zone)
        if checkin_at is None:
            continue
        overdue.append(
            OverdueGearUsage(
                journal_id=row.journal_id,
                checkout_at=_local_date(row.checkout_date, zone),
                checkin_at=checkin_at,
            )
        )
    return overdue
