"""
Snipe-IT Sync Service — orchestrates gear item and maintenance import.

Fetches assets and maintenance records from the Snipe-IT API, transforms
them using ``SnipeItDataTransformer`` / ``SnipeItMaintenanceTransformer``,
and upserts them into the database. Sync state is tracked via ``SyncMetadata``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import structlog
from sqlalchemy import text

from snipeit_api_client import SnipeItAPIClient, SnipeItAPIError
from snipeit_data_transformer import SnipeItDataTransformer
from snipeit_maintenance_transformer import SnipeItMaintenanceTransformer
from snipeit_rate_limiter import SnipeItRateLimitError

logger = structlog.get_logger(__name__)

# Maximum assets per Snipe-IT API page
_PAGE_SIZE = 50


# Internal signalling exceptions
class _AssetSkipped(Exception):
    """Raised when an asset was already imported (dedup)."""


class _AssetFailed(Exception):
    """Raised when an asset failed after all retries."""


class _MaintenanceSkipped(Exception):
    """Raised when a maintenance record was already imported (dedup)."""


class _MaintenanceFailed(Exception):
    """Raised when a maintenance record failed after all retries."""


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
