"""
Snipe-IT Worker Stream Consumer for Redis Streams.

Reads events from the pms:domain-events stream using the 'snipeit-worker'
consumer group. The declarative route table consumes ``snipeit.webhook_received``
(asset sync), ``GearItemUpdated`` (push local gear changes), and
``JournalCreated`` / ``JournalUpdated`` (gear-maintenance / gear-usage sync).
"""

import asyncio
import math
from typing import Any

import structlog
from core_shared.stream_client import StreamClient, StreamEvent, create_stream_redis
from core_shared.stream_consumer import EventRoute, StreamConsumer

from snipeit_sync_service import IN_FLIGHT_LOCK_SECONDS, INBOUND_SYNC_CHANGED_BY

logger = structlog.get_logger()

# Events that meet a Snipe-IT lock held by another worker raise
# SnipeItSyncInProgress and are redelivered. If that worker died, its lock only
# becomes retakeable after IN_FLIGHT_LOCK_SECONDS, so delivery attempts must
# continue past that point (with an interval to spare) or the event is
# dead-lettered and its update lost.
RETRY_MIN_IDLE_MS = 60_000
MAX_DELIVERY_COUNT = math.ceil(IN_FLIGHT_LOCK_SECONDS * 1000 / RETRY_MIN_IDLE_MS) + 2


def _imported_maintenance_ids(event: StreamEvent) -> list[str]:
    """The Snipe-IT records a deleted journal was imported from.

    ``JournalDeleted`` carries the external ids of the links it is about to
    lose, filed under the integration that owns each. This is the only way an
    imported record can be reached afterwards: its sync row names no journal,
    so nothing left in the database connects the two.

    Never raises. The payload arrives as JSON over Redis, so it is data rather
    than a call — an event published before the identifiers were filed by
    source, or one carrying a shape this worker does not know, must leave the
    rest of the deletion to get on with its work.
    """
    identifiers = event.event_data.get("external_identifiers")
    if not isinstance(identifiers, dict):
        return []
    entries = identifiers.get(INBOUND_SYNC_CHANGED_BY)
    if not isinstance(entries, list):
        return []
    external_ids = []
    for entry in entries:
        external_id = (
            entry.get("external_event_id") if isinstance(entry, dict) else entry
        )
        if isinstance(external_id, str) and external_id:
            external_ids.append(external_id)
    return external_ids


class SnipeItWorkerStreamConsumer(StreamConsumer):
    """Stream consumer for Snipe-IT integration event processing.

    Listens to Snipe-IT webhook, gear item and journal events on the
    ``pms:domain-events`` stream using the ``snipeit-worker`` consumer group.
    The declarative route table maps each consumed event type to a handler;
    the shared ``StreamConsumer`` runs the read/ack/retry loop and dispatches
    matched events. The route table is the single source of truth for the
    consumed-event set.
    """

    def __init__(
        self,
        stream_client: StreamClient,
        session_factory: Any,
        stream_name: str = "pms:domain-events",
        consumer_name: str = "snipeit-worker-1",
        batch_size: int = 10,
        block_ms: int = 5000,
        retry_min_idle_ms: int = RETRY_MIN_IDLE_MS,
        max_delivery_count: int = MAX_DELIVERY_COUNT,
    ) -> None:
        self._session_factory = session_factory
        super().__init__(
            stream_client=stream_client,
            stream_name=stream_name,
            group_name="snipeit-worker",
            consumer_name=consumer_name,
            batch_size=batch_size,
            block_ms=block_ms,
            retry_min_idle_ms=retry_min_idle_ms,
            max_delivery_count=max_delivery_count,
            routes=self._build_routes(),
        )

    def _build_routes(self) -> list[EventRoute]:
        """Declare the event-type → handler routes for this worker."""
        return [
            EventRoute("GearItemUpdated", self._handle_gear_item_updated),
            EventRoute("JournalCreated", self._handle_journal_maintenance_event),
            EventRoute("JournalUpdated", self._handle_journal_maintenance_event),
            EventRoute("JournalDeleted", self._handle_journal_deleted),
            EventRoute("snipeit.webhook_received", self._handle_webhook_received),
        ]

    def _log_processed(self, event: StreamEvent) -> None:
        logger.info(
            "Snipe-IT worker processed event from stream",
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_id=event.aggregate_id,
        )

    async def _handle_webhook_received(self, event: StreamEvent) -> None:
        """Process a ``snipeit.webhook_received`` event.

        Extracts the asset ID and synchronizes it for the user who owns the
        webhook URL (``user_id``), whose token authenticated the notification.
        An event without an owner is skipped rather than synced for everyone,
        so an unauthenticated notification can never fan out across users.
        The item is always an asset: the backend publishes only notifications
        that link an asset, and Snipe-IT sends no maintenance notifications, so
        maintenance records are imported only by the maintenance sync job
        (``sync_snipeit_maintenances``).
        """
        self._log_processed(event)

        item = event.event_data.get("item")
        if not item or not isinstance(item, dict):
            logger.debug("Skipping webhook event: missing or invalid item payload")
            return

        asset_id = item.get("id")
        if not asset_id:
            logger.debug("Skipping webhook event: missing item.id")
            return

        user_id = event.event_data.get("user_id")
        if not user_id or not isinstance(user_id, str):
            logger.warning(
                "Skipping webhook event: missing owning user",
                event_id=event.event_id,
                asset_id=asset_id,
            )
            return

        from sqlalchemy import text

        from snipeit_api_client import SnipeItAPIError
        from snipeit_settings import SnipeItWorkerSettings
        from snipeit_sync_service import _AssetSkipped
        from worker import _create_sync_service, _get_auth_data

        worker_settings = SnipeItWorkerSettings()

        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT user_id, base_url, snipeit_user_id
                    FROM snipeit_settings
                    WHERE user_id = :user_id
                """),
                {"user_id": user_id},
            )
            settings_row = result.fetchone()

        if settings_row is None:
            logger.info(
                "Skipping webhook event: user no longer has Snipe-IT configured",
                asset_id=asset_id,
                user_id=user_id,
            )
            return

        auth_data = await _get_auth_data(self._session_factory, user_id)
        if not auth_data:
            return

        sync_service = _create_sync_service(
            user_id=user_id,
            auth_data=auth_data,
            base_url=settings_row.base_url,
            snipeit_user_id=settings_row.snipeit_user_id,
            worker_settings=worker_settings,
            session_factory=self._session_factory,
        )

        try:
            await sync_service._sync_single_asset_with_retry(
                asset_id=asset_id,
                session_factory=self._session_factory,
            )
            logger.info(
                "Successfully processed webhook sync for asset",
                asset_id=asset_id,
                user_id=user_id,
            )
        except _AssetSkipped:
            # Asset hasn't changed, ignore safely
            pass
        except SnipeItAPIError as exc:
            if exc.status_code in (403, 404):
                # Asset likely doesn't exist in this user's instance
                logger.debug(
                    "Skipped webhook sync for asset (not found/forbidden)",
                    asset_id=asset_id,
                    user_id=user_id,
                    status_code=exc.status_code,
                )
            else:
                logger.warning(
                    "Failed to sync asset from webhook",
                    asset_id=asset_id,
                    user_id=user_id,
                    exc_info=True,
                )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to sync asset from webhook",
                asset_id=asset_id,
                user_id=user_id,
                exc_info=True,
            )
        finally:
            await sync_service._api_client.close()

    async def _handle_gear_item_updated(self, event: StreamEvent) -> None:
        """Process GearItemUpdated outbox events to push changes to Snipe-IT."""
        self._log_processed(event)
        gear_item_id = event.event_data.get("gear_item_id")
        changed_fields = event.event_data.get("changed_fields")

        if not gear_item_id or not isinstance(changed_fields, dict):
            logger.debug("Skipping GearItemUpdated: missing or invalid payload")
            return

        from sqlalchemy import text

        from snipeit_api_client import SnipeItAPIError
        from snipeit_settings import SnipeItWorkerSettings
        from worker import _create_sync_service, _get_auth_data

        worker_settings = SnipeItWorkerSettings()

        async with self._session_factory() as session:
            # Look up the gear item's user and see if they have Snipe-IT configured
            result = await session.execute(
                text("""
                    SELECT g.user_id, s.base_url, s.snipeit_user_id
                    FROM gear_items g
                    JOIN snipeit_settings s ON g.user_id = s.user_id
                    WHERE g.id = :gear_item_id
                """),
                {"gear_item_id": gear_item_id},
            )
            row = result.fetchone()

        if not row:
            logger.debug(
                "Skipping GearItemUpdated: user has no Snipe-IT settings or gear item missing"
            )
            return

        user_id = row.user_id
        base_url = row.base_url
        snipeit_user_id = row.snipeit_user_id

        auth_data = await _get_auth_data(self._session_factory, user_id)
        if not auth_data:
            logger.debug("Skipping GearItemUpdated: missing auth data")
            return

        sync_service = _create_sync_service(
            user_id=user_id,
            auth_data=auth_data,
            base_url=base_url,
            snipeit_user_id=snipeit_user_id,
            worker_settings=worker_settings,
            session_factory=self._session_factory,
        )

        try:
            await sync_service.push_asset_update(
                gear_item_id=gear_item_id,
                changed_fields=changed_fields,
                session_factory=self._session_factory,
            )
        except SnipeItAPIError as exc:
            if exc.status_code in (403, 404):
                logger.debug(
                    "Skipping gear item export (not found/forbidden in Snipe-IT)",
                    gear_item_id=gear_item_id,
                    status_code=exc.status_code,
                )
            else:
                # Let it propagate so the stream consumer retries
                raise
        finally:
            await sync_service._api_client.close()

    async def _handle_journal_maintenance_event(self, event: StreamEvent) -> None:
        """Process JournalCreated/JournalUpdated events for outbound sync.

        Checks if the journal has GEAR_MAINTENANCE or GEAR_USAGE type data,
        then pushes the creation or update to Snipe-IT for users with active
        Snipe-IT settings.
        """
        self._log_processed(event)
        journal_id = event.event_data.get("journal_id")
        if not journal_id:
            logger.debug("Skipping journal event: missing journal_id")
            return

        if event.event_data.get("changed_by") == INBOUND_SYNC_CHANGED_BY:
            # The inbound sync applied this from Snipe-IT; pushing it back
            # would send the record to where it came from.
            logger.debug(
                "Skipping journal event: applied by the inbound Snipe-IT sync",
                journal_id=journal_id,
            )
            return

        from sqlalchemy import text

        from snipeit_api_client import SnipeItAPIError
        from snipeit_settings import SnipeItWorkerSettings
        from worker import _create_sync_service, _get_auth_data

        worker_settings = SnipeItWorkerSettings()

        journal_type: str | None = None

        async with self._session_factory() as session:
            # Look up the journal's user via snipeit_settings
            # The journal_id's user_id comes from event_data for JournalCreated,
            # or we can look it up from the journals table
            user_id = event.event_data.get("user_id")
            if not user_id:
                # For JournalUpdated, user_id may not be in event_data;
                # we'll rely on the journal_id being passed to the sync service
                # which queries the journal table directly.
                # For now, look up which user owns this journal.
                pass

            # Find users with Snipe-IT configured that own this journal
            result = await session.execute(
                text("""
                    SELECT s.user_id, s.base_url, s.snipeit_user_id
                    FROM snipeit_settings s
                    JOIN journals j ON j.user_id = s.user_id
                    WHERE j.id = :journal_id
                """),
                {"journal_id": journal_id},
            )
            settings_row = result.fetchone()

            if not settings_row:
                logger.debug(
                    "Skipping journal event: no Snipe-IT settings for journal owner",
                    journal_id=journal_id,
                )
                return

            # Check if journal has GEAR_MAINTENANCE type data
            maint_result = await session.execute(
                text("""
                    SELECT journal_id
                    FROM journal_gear_maintenance_data
                    WHERE journal_id = :journal_id
                """),
                {"journal_id": journal_id},
            )
            if maint_result.fetchone():
                journal_type = "GEAR_MAINTENANCE"
            else:
                # A GEAR_USAGE journal, or one that was: a journal whose gear
                # items (or whole GEAR_USAGE type) were removed still has pairs
                # recorded in Snipe-IT to release.
                usage_result = await session.execute(
                    text("""
                        SELECT 1
                        FROM journal_gear_usage_data
                        WHERE journal_id = :journal_id
                        UNION ALL
                        SELECT 1
                        FROM sync_metadata
                        WHERE integration_source = 'snipeit_checkout'
                          AND internal_uuid = :journal_uuid
                        LIMIT 1
                    """),
                    {"journal_id": journal_id, "journal_uuid": str(journal_id)},
                )
                if usage_result.fetchone():
                    journal_type = "GEAR_USAGE"

            if not journal_type:
                logger.debug(
                    "Skipping journal event: not a GEAR_MAINTENANCE or GEAR_USAGE journal",
                    journal_id=journal_id,
                )
                return

        auth_data = await _get_auth_data(self._session_factory, settings_row.user_id)
        if not auth_data:
            logger.debug(
                "Skipping journal event: missing auth data",
                journal_id=journal_id,
            )
            return

        sync_service = _create_sync_service(
            user_id=settings_row.user_id,
            auth_data=auth_data,
            base_url=settings_row.base_url,
            snipeit_user_id=settings_row.snipeit_user_id,
            worker_settings=worker_settings,
            session_factory=self._session_factory,
        )

        try:
            if journal_type == "GEAR_USAGE":
                # Created or updated, reconcile the desired checkout/checkin
                # state. A create is not just a checkout: when its check-in
                # failed after the checkout was recorded (e.g. a 429), the
                # redelivered event must still check the asset back in, or it
                # stays out and every later checkout of it fails.
                await sync_service.reconcile_gear_usage(
                    journal_id=journal_id,
                    session_factory=self._session_factory,
                )
                logger.info(
                    "Successfully processed journal gear usage event",
                    journal_id=journal_id,
                    event_type=event.event_type,
                )
            else:
                if event.event_type == "JournalCreated":
                    await sync_service.push_maintenance_create(
                        journal_id=journal_id,
                        session_factory=self._session_factory,
                    )
                else:
                    await sync_service.push_maintenance_update(
                        journal_id=journal_id,
                        session_factory=self._session_factory,
                    )
                logger.info(
                    "Successfully processed journal maintenance event",
                    journal_id=journal_id,
                    event_type=event.event_type,
                )
        except SnipeItAPIError as exc:
            if exc.status_code in (403, 404):
                logger.debug(
                    "Skipping journal export (not found/forbidden)",
                    journal_id=journal_id,
                    status_code=exc.status_code,
                )
            else:
                raise
        finally:
            await sync_service._api_client.close()

    async def _handle_journal_deleted(self, event: StreamEvent) -> None:
        """Process JournalDeleted events: undo what the journal put in Snipe-IT.

        The journal and its cascade-deleted type data are already gone, so there
        is no journal type to dispatch on. What the journal put in Snipe-IT is
        read from the sync rows that name it instead, and each is undone:

        - ``snipeit_checkout``: the asset it held is checked in, resolved from
          the row inside ``push_checkin_create``.
        - ``snipeit_maintenance``: the record it pushed is deleted, so it cannot
          outlive the journal and import again as a new one.
        - ``snipeit_maintenance_claim``: the claim an attempt that failed after
          posting left is removed; it is inert once its journal is gone.

        A journal *imported* from Snipe-IT has no such row — its record's row
        names no journal — so the record it was imported from is read from the
        event's own ``external_identifiers`` instead, and deleted the same way.
        A journal can have both: an import whose edit was echoed into a second
        record holds a link and a push row naming different records, and each
        is undone by its own route.

        A journal is gear usage or maintenance, never both, so in practice one
        path runs. This is a no-op for a journal Snipe-IT never recorded.
        """
        self._log_processed(event)
        journal_id = event.event_data.get("journal_id")
        user_id = event.event_data.get("user_id")
        if not journal_id or not user_id:
            logger.debug("Skipping JournalDeleted: missing journal_id or user_id")
            return

        from sqlalchemy import text

        from snipeit_api_client import SnipeItAPIError
        from snipeit_settings import SnipeItWorkerSettings
        from snipeit_sync_service import _delete_maintenance_claim
        from worker import _create_sync_service, _get_auth_data

        # Fast path: only proceed if this journal put something in the owner's
        # Snipe-IT. A claim is keyed by journal id on ``external_id``, the
        # others on ``internal_uuid``.
        async with self._session_factory() as session:
            rows_result = await session.execute(
                text("""
                    SELECT integration_source
                    FROM sync_metadata
                    WHERE user_id = :user_id
                      AND ((integration_source IN
                                ('snipeit_checkout', 'snipeit_maintenance')
                            AND internal_uuid = :journal_id)
                           OR (integration_source = 'snipeit_maintenance_claim'
                               AND external_id = :journal_id))
                """),
                {"user_id": str(user_id), "journal_id": str(journal_id)},
            )
            sources = {row.integration_source for row in rows_result.fetchall()}

        imported_records = _imported_maintenance_ids(event)

        if not sources and not imported_records:
            logger.debug(
                "Skipping JournalDeleted: nothing recorded in Snipe-IT",
                journal_id=journal_id,
            )
            return

        # A claim with no record beside it is cleared before anything asks for
        # credentials: clearing it is a database write, and a user who has
        # disconnected Snipe-IT would otherwise leave it behind for good. A
        # claim alongside a push row or an imported record goes with that
        # record instead, and deleting a record does need credentials.
        #
        # In its own session: the query above has already opened a transaction
        # on that one, and asking it to begin a second raises.
        if sources == {"snipeit_maintenance_claim"} and not imported_records:
            async with self._session_factory() as session:
                async with session.begin():
                    await _delete_maintenance_claim(
                        session, journal_id, user_id=str(user_id)
                    )
            logger.info(
                "Cleared the maintenance claim of a deleted journal",
                journal_id=journal_id,
            )
            return

        async with self._session_factory() as session:
            settings_result = await session.execute(
                text("""
                    SELECT user_id, base_url, snipeit_user_id
                    FROM snipeit_settings
                    WHERE user_id = :user_id
                """),
                {"user_id": user_id},
            )
            settings_row = settings_result.fetchone()

        if not settings_row:
            logger.debug(
                "Skipping JournalDeleted: no Snipe-IT settings for journal owner",
                journal_id=journal_id,
            )
            return

        worker_settings = SnipeItWorkerSettings()
        auth_data = await _get_auth_data(self._session_factory, settings_row.user_id)
        if not auth_data:
            logger.debug(
                "Skipping JournalDeleted: missing auth data",
                journal_id=journal_id,
            )
            return

        sync_service = _create_sync_service(
            user_id=settings_row.user_id,
            auth_data=auth_data,
            base_url=settings_row.base_url,
            snipeit_user_id=settings_row.snipeit_user_id,
            worker_settings=worker_settings,
            session_factory=self._session_factory,
        )

        try:
            if "snipeit_checkout" in sources:
                await self._checkin_deleted_journal(sync_service, journal_id)
            if sources & {"snipeit_maintenance", "snipeit_maintenance_claim"}:
                await sync_service.delete_pushed_maintenance(
                    journal_id=journal_id,
                    session_factory=self._session_factory,
                )
            for external_id in imported_records:
                await sync_service.delete_maintenance_record(
                    external_id=external_id,
                    session_factory=self._session_factory,
                )
        except SnipeItAPIError as exc:
            if exc.status_code in (403, 404):
                logger.debug(
                    "Skipping journal deletion cleanup (not found/forbidden)",
                    journal_id=journal_id,
                    status_code=exc.status_code,
                )
            else:
                raise
        finally:
            await sync_service._api_client.close()

    async def _checkin_deleted_journal(
        self, sync_service: Any, journal_id: int
    ) -> None:
        """Check in every asset a deleted gear-usage journal held.

        The journal's gear items are gone with it, so its (journal, asset) pairs
        are read from the checkout sync rows.
        """
        from sqlalchemy import text

        from snipeit_sync_service import GearUsagePair, _checkout_asset_id

        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT external_id
                    FROM sync_metadata
                    WHERE integration_source = 'snipeit_checkout'
                      AND internal_uuid = :journal_uuid
                    ORDER BY external_id
                """),
                {"journal_uuid": str(journal_id)},
            )
            asset_ids = [_checkout_asset_id(row.external_id) for row in result]

        for asset_id in asset_ids:
            if asset_id is None:
                continue
            checked_in = await sync_service.push_checkin_create(
                GearUsagePair(journal_id, asset_id),
                session_factory=self._session_factory,
                note="Gear usage journal deleted",
            )
            if checked_in:
                logger.info(
                    "Checked in asset on journal deletion",
                    journal_id=journal_id,
                    snipeit_asset_id=asset_id,
                )
            else:
                logger.debug(
                    "Journal deletion checkin was a no-op",
                    journal_id=journal_id,
                    snipeit_asset_id=asset_id,
                )


async def run_snipeit_stream_consumer(
    session_factory: Any,
    redis_url: str,
    stream_name: str = "pms:domain-events",
) -> None:
    """Run the Snipe-IT worker stream consumer loop."""
    redis_client = create_stream_redis(redis_url)
    stream_client = StreamClient(redis_client)

    consumer = SnipeItWorkerStreamConsumer(
        stream_client=stream_client,
        session_factory=session_factory,
        stream_name=stream_name,
    )

    logger.info(
        "Starting Snipe-IT worker stream consumer",
        stream=stream_name,
        group="snipeit-worker",
    )

    try:
        await consumer.start()
    except asyncio.CancelledError:
        logger.info("Snipe-IT worker stream consumer cancelled")
        raise
    finally:
        await redis_client.aclose()
