"""
Snipe-IT Sync Service — orchestrates gear item import.

Fetches assets from the Snipe-IT API, transforms them using
``SnipeItDataTransformer``, and directly upserts them into the
``gear_items`` table. Sync state is tracked via ``SyncMetadata``.
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
from snipeit_rate_limiter import SnipeItRateLimitError

logger = structlog.get_logger(__name__)

# Maximum assets per Snipe-IT API page
_PAGE_SIZE = 50


# Internal signalling exceptions
class _AssetSkipped(Exception):
    """Raised when an asset was already imported (dedup)."""


class _AssetFailed(Exception):
    """Raised when an asset failed after all retries."""


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
                                SELECT version_hash
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
                        gear_id = transformed.gear_item.id

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
                    except Exception:
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
