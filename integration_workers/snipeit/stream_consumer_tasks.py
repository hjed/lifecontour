"""
Snipe-IT Worker Stream Consumer for Redis Streams.

Reads events from the pms:domain-events stream using the 'snipeit-worker' consumer group.
Currently listens for snipeit.webhook_received events, which will be processed in
subsequent phases.
"""

import asyncio
from typing import Any

import structlog
from core_shared.stream_client import StreamClient, StreamEvent
from core_shared.stream_consumer import StreamConsumer

logger = structlog.get_logger()

_SNIPEIT_EVENT_TYPES = frozenset({"snipeit.webhook_received"})


class SnipeItWorkerStreamConsumer(StreamConsumer):
    """Stream consumer for Snipe-IT integration event processing.

    Listens to Snipe-IT webhook events on the ``pms:domain-events`` stream
    using the ``snipeit-worker`` consumer group.
    """

    def __init__(
        self,
        stream_client: StreamClient,
        session_factory: Any,
        stream_name: str = "pms:domain-events",
        consumer_name: str = "snipeit-worker-1",
        batch_size: int = 10,
        block_ms: int = 5000,
    ) -> None:
        super().__init__(
            stream_client=stream_client,
            stream_name=stream_name,
            group_name="snipeit-worker",
            consumer_name=consumer_name,
            event_type_patterns=list(_SNIPEIT_EVENT_TYPES),
            batch_size=batch_size,
            block_ms=block_ms,
        )
        self._session_factory = session_factory

    async def _handle_event(self, event: StreamEvent) -> None:
        """Process an event from the stream.

        Processes snipeit.webhook_received events by extracting the asset ID
        and synchronizing it for all users that have a Snipe-IT configuration.
        """
        logger.info(
            "Snipe-IT worker processed event from stream",
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_id=event.aggregate_id,
        )

        if event.event_type != "snipeit.webhook_received":
            return

        item = event.event_data.get("item")
        if not item or not isinstance(item, dict):
            logger.debug("Skipping webhook event: missing or invalid item payload")
            return

        asset_id = item.get("id")
        if not asset_id:
            logger.debug("Skipping webhook event: missing item.id")
            return

        from sqlalchemy import text

        from snipeit_api_client import SnipeItAPIError
        from snipeit_settings import SnipeItWorkerSettings
        from snipeit_sync_service import _AssetSkipped
        from worker import _create_sync_service, _get_auth_data

        worker_settings = SnipeItWorkerSettings()  # type: ignore[call-arg]

        # Query all users with Snipe-IT configured
        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT user_id, base_url, snipeit_user_id
                    FROM snipeit_settings
                """)
            )
            settings_rows = result.fetchall()

        for row in settings_rows:
            user_id = row.user_id
            base_url = row.base_url
            snipeit_user_id = row.snipeit_user_id

            auth_data = await _get_auth_data(self._session_factory, user_id)
            if not auth_data:
                continue

            sync_service = _create_sync_service(
                user_id=user_id,
                auth_data=auth_data,
                base_url=base_url,
                snipeit_user_id=snipeit_user_id,
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
            except Exception:
                logger.warning(
                    "Failed to sync asset from webhook",
                    asset_id=asset_id,
                    user_id=user_id,
                    exc_info=True,
                )
            finally:
                await sync_service._api_client.close()


async def run_snipeit_stream_consumer(
    session_factory: Any,
    redis_url: str,
    stream_name: str = "pms:domain-events",
) -> None:
    """Run the Snipe-IT worker stream consumer loop."""
    from redis.asyncio import Redis  # type: ignore[import-untyped]

    redis_client = Redis.from_url(redis_url)
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
        await redis_client.close()
