"""
Strava Sync Service — orchestrates activity import.

Fetches activities from the Strava API, transforms them using
``StravaDataTransformer``, and creates transactional outbox events
for the backend inbound processor to consume. Handles full-sync
pagination, single-activity webhook sync, and delete events.

No journal creation happens here — the outbox → inbound processor
pipeline handles that.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import structlog
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from strava_api_client import StravaAPIClient, StravaAPIError
from strava_data_transformer import StravaDataTransformer, TransformedActivity
from strava_models import StravaStreamSet
from strava_rate_limiter import StravaRateLimitError

logger = structlog.get_logger(__name__)

# Synthetic calendar_id for Strava (Strava doesn't use calendars, but the
# outbox event schema requires one for compatibility with the inbound
# processor).  This UUID is deterministic so lookups work.
_STRAVA_SYNTHETIC_CALENDAR_ID = "00000000-0000-0000-0000-000000000001"

# Maximum activities per Strava API page
_PAGE_SIZE = 100

# ── Internal signalling exceptions ──────────────────────────────────


class _ActivitySkipped(Exception):
    """Raised when an activity was already imported (dedup)."""


class _ActivityFailed(Exception):
    """Raised when an activity failed after all retries."""


# ── Transient error classification ──────────────────────────────────

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
    """Return True if *exc* is a transient/retryable error."""
    if isinstance(exc, _TRANSIENT_EXCEPTIONS):
        return True
    # 5xx server errors from Strava are transient
    if isinstance(exc, StravaAPIError) and exc.status_code >= 500:
        return True
    return False


# Per-activity retry settings for transient errors
_MAX_ACTIVITY_RETRIES = 3
_RETRY_BACKOFF_BASE = 2.0  # seconds — exponential: 2s, 4s, 8s


class StravaSyncService:
    """Orchestrates Strava activity import into journal outbox events.

    Responsibilities:
    - **Full sync**: paginate through all activities and create outbox events.
    - **Single-activity sync**: fetch one activity (webhook trigger), create event.
    - **Delete handling**: create cancellation event for deleted activity.

    Args:
        api_client: Authenticated ``StravaAPIClient`` for Strava API calls.
        user_id: Internal user ID that owns the Strava connection.
    """

    def __init__(
        self,
        api_client: StravaAPIClient,
        user_id: str,
    ) -> None:
        self._api_client = api_client
        self._user_id = user_id
        self._transformer = StravaDataTransformer()

    # ── Public API ──────────────────────────────────────────────────────

    async def sync_single_activity(
        self,
        activity_id: int,
        session: AsyncSession,
    ) -> list[OutboxEvent]:
        """Sync a single activity (e.g. from a webhook create/update).

        For new activities, creates a ``journal_event.created`` outbox event.
        For already-imported activities (webhook update), creates a
        ``journal_event.updated`` event with the ``existing_journal_id`` so
        the inbound processor updates rather than duplicates.

        Args:
            activity_id: Strava numeric activity ID.
            session: Database session for outbox event persistence and dedup.

        Returns:
            List containing the created outbox event, or empty if skipped.
        """
        activity = await self._api_client.get_activity(activity_id)

        # Check if already imported — if so, emit an update instead of create
        existing_journal_id = await self._find_existing_journal_id(
            str(activity.id), session
        )

        # Fetch streams for GPS-equipped activities
        streams: StravaStreamSet | None = None
        if activity.start_latlng is not None:
            streams = await self._api_client.get_activity_streams(activity.id)

        transformed = self._transformer.transform(activity, streams=streams)

        if existing_journal_id is not None:
            event = self._build_outbox_event(
                transformed,
                sync_action="updated",
                existing_journal_id=existing_journal_id,
            )
            logger.info(
                "Created update outbox event for existing Strava activity",
                strava_activity_id=activity.id,
                journal_id=existing_journal_id,
            )
        else:
            event = self._build_outbox_event(transformed)
            logger.info(
                "Created outbox event for new Strava activity",
                strava_activity_id=activity.id,
            )

        session.add(event)
        return [event]

    async def list_activity_batches(
        self,
        after_timestamp: int | None = None,
    ) -> AsyncIterator[list[int]]:
        """Yield pages of Strava activity IDs for batch processing.

        Each yielded list represents one API page of activity IDs. The
        caller (typically the ARQ orchestrator) should enqueue each batch
        as a separate job so that:

        - Each batch commits independently (progress is preserved).
        - ARQ retries handle transient failures per-batch.
        - The sync can make incremental progress even under timeouts.

        Args:
            after_timestamp: Optional epoch timestamp — only list activities
                after this time (for incremental sync).

        Yields:
            Lists of Strava activity IDs, one list per API page.
        """
        page = 1

        while True:
            activities = await self._api_client.list_activities(
                page=page,
                per_page=_PAGE_SIZE,
                after=after_timestamp,
            )

            if not activities:
                break

            activity_ids = [activity.id for activity in activities]
            logger.info(
                "Listed activity batch",
                page=page,
                batch_size=len(activity_ids),
            )
            yield activity_ids

            page += 1

        logger.info(
            "Finished listing activity batches",
            pages_fetched=page - 1,
        )

    async def sync_activity_batch(
        self,
        activity_ids: list[int],
        session_factory: Any,
    ) -> dict[str, int]:
        """Process a batch of activity IDs, creating outbox events.

        Each activity is processed independently — a failure in one
        activity does not affect others in the batch. This method is
        designed to be called from an ARQ job so that ARQ's built-in
        ``max_tries`` provides automatic retries on job-level failures
        (e.g. full-batch timeouts).

        Args:
            activity_ids: Strava activity IDs to sync.
            session_factory: Async session factory for per-activity
                database transactions.

        Returns:
            Dict with ``synced``, ``skipped``, and ``failed`` counts.
        """
        synced = 0
        skipped = 0
        failed = 0

        for activity_id in activity_ids:
            try:
                await self._sync_single_activity_with_retry(
                    activity_id, session_factory
                )
                synced += 1
            except _ActivitySkipped:
                skipped += 1
            except _ActivityFailed:
                failed += 1

        logger.info(
            "Activity batch completed",
            batch_size=len(activity_ids),
            synced=synced,
            skipped=skipped,
            failed=failed,
        )
        return {"synced": synced, "skipped": skipped, "failed": failed}

    async def _sync_single_activity_with_retry(
        self,
        activity_id: int,
        session_factory: Any,
    ) -> None:
        """Fetch, transform, and persist one activity with retry.

        Performs deduplication and API calls *outside* a DB transaction
        to avoid holding connections during network I/O.  Only opens a
        short transaction for the final outbox event write.

        Retries transient errors (network timeouts, 5xx) up to
        ``_MAX_ACTIVITY_RETRIES`` times with exponential backoff.
        Non-transient errors (e.g. transformation bugs) fail
        immediately.  DB/SQLAlchemy errors are *not* caught so they
        bubble up to ARQ for job-level retry.

        Raises:
            _ActivitySkipped: Activity already imported (dedup).
            _ActivityFailed: All retries exhausted.
        """
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_ACTIVITY_RETRIES + 1):
            try:
                # Deduplication — check outside a long-lived transaction
                async with session_factory() as dedup_session:
                    existing_jid = await self._find_existing_journal_id(
                        str(activity_id), dedup_session
                    )
                    stored_hash = await self._find_stored_version_hash(
                        str(activity_id), dedup_session
                    )

                if existing_jid is not None and stored_hash is not None:
                    # Activity is imported AND has a valid version hash —
                    # skip unless the hash has changed on re-fetch
                    logger.debug(
                        "Skipping already-imported activity",
                        strava_activity_id=activity_id,
                    )
                    raise _ActivitySkipped

                # API calls happen outside any DB transaction
                activity = await self._api_client.get_activity(activity_id)

                # Fetch streams for GPS-equipped activities
                streams: StravaStreamSet | None = None
                if activity.start_latlng is not None:
                    streams = await self._api_client.get_activity_streams(activity.id)

                transformed = self._transformer.transform(activity, streams=streams)

                if existing_jid is not None:
                    # Activity exists but version hash was invalidated
                    # (e.g. by a data migration) — emit an update to
                    # re-process types and fitness data
                    event = self._build_outbox_event(
                        transformed,
                        sync_action="updated",
                        existing_journal_id=existing_jid,
                    )
                    logger.info(
                        "Re-syncing stale activity (version hash invalidated)",
                        strava_activity_id=activity_id,
                        journal_id=existing_jid,
                    )
                else:
                    event = self._build_outbox_event(transformed)

                # Short transaction just for the write
                async with session_factory() as session:
                    async with session.begin():
                        session.add(event)
                return  # success

            except _ActivitySkipped:
                raise  # propagate immediately
            except (StravaRateLimitError, SQLAlchemyError):
                # Rate limiting and DB errors affect the whole batch —
                # let them bubble up to ARQ for job-level retry.
                raise
            except Exception as exc:
                if not _is_transient_error(exc):
                    # Non-transient (e.g. transform bug) — fail immediately
                    logger.warning(
                        "Non-transient error syncing activity, skipping",
                        strava_activity_id=activity_id,
                        attempt=attempt,
                        exc_info=True,
                    )
                    raise _ActivityFailed from exc

                last_exc = exc
                if attempt < _MAX_ACTIVITY_RETRIES:
                    backoff = _RETRY_BACKOFF_BASE**attempt
                    logger.warning(
                        "Transient error syncing activity, retrying",
                        strava_activity_id=activity_id,
                        attempt=attempt,
                        max_attempts=_MAX_ACTIVITY_RETRIES,
                        backoff_seconds=backoff,
                        error=str(exc),
                    )
                    await asyncio.sleep(backoff)

        # All retries exhausted
        logger.error(
            "Failed to sync activity after all retries",
            strava_activity_id=activity_id,
            max_attempts=_MAX_ACTIVITY_RETRIES,
            error=str(last_exc),
        )
        raise _ActivityFailed from last_exc

    async def handle_delete(
        self,
        activity_id: int,
        session: AsyncSession,
    ) -> OutboxEvent | None:
        """Handle a Strava activity deletion.

        Looks up the journal linked to the Strava activity ID and creates
        a ``journal_event.cancelled`` outbox event.

        Args:
            activity_id: Strava numeric activity ID that was deleted.
            session: Database session.

        Returns:
            The cancellation outbox event, or None if the activity
            was not previously imported.
        """
        strava_id = str(activity_id)

        # Find the journal linked to this Strava activity
        result = await session.execute(
            text("""
                SELECT journal_id
                FROM journal_fitness_data
                WHERE strava_activity_id = :strava_id
                LIMIT 1
            """),
            {"strava_id": strava_id},
        )
        row = result.fetchone()

        if row is None:
            logger.info(
                "Deleted Strava activity not found in database, skipping",
                strava_activity_id=activity_id,
            )
            return None

        journal_id = row.journal_id

        event = OutboxEvent.create_journal_sync_event(
            journal_data={"user_id": self._user_id},
            calendar_info_data={"calendar_id": _STRAVA_SYNTHETIC_CALENDAR_ID},
            integration_source="strava",
            external_event_id=f"strava:{strava_id}",
            calendar_id=_STRAVA_SYNTHETIC_CALENDAR_ID,
            sync_action="cancelled",
            existing_journal_id=journal_id,
        )
        session.add(event)

        logger.info(
            "Created cancellation event for deleted Strava activity",
            strava_activity_id=activity_id,
            journal_id=journal_id,
        )
        return event

    # ── Internal helpers ────────────────────────────────────────────────

    async def _find_existing_journal_id(
        self, strava_activity_id: str, session: AsyncSession
    ) -> int | None:
        """Find journal ID for an already-imported Strava activity.

        Uses the ``strava_activity_id`` column in ``journal_fitness_data``
        for deduplication.

        Args:
            strava_activity_id: Strava activity ID string.
            session: Database session.

        Returns:
            Journal ID if the activity exists, None otherwise.
        """
        result = await session.execute(
            text("""
                SELECT journal_id
                FROM journal_fitness_data
                WHERE strava_activity_id = :strava_id
                LIMIT 1
            """),
            {"strava_id": strava_activity_id},
        )
        row = result.fetchone()
        return row.journal_id if row is not None else None

    async def _find_stored_version_hash(
        self, strava_activity_id: str, session: AsyncSession
    ) -> str | None:
        """Look up the stored version hash for a Strava activity.

        Queries ``sync_metadata`` for an entry matching the Strava
        activity ID.  Returns ``None`` if no row exists or if the
        ``version_hash`` column has been set to ``'invalidated_for_type_backfill'``
        (e.g. by a data migration that invalidates stale entries).

        Args:
            strava_activity_id: Strava activity ID string.
            session: Database session.

        Returns:
            The stored version hash, or None if absent/invalidated.
        """
        result = await session.execute(
            text("""
                SELECT version_hash
                FROM sync_metadata
                WHERE integration_source = 'strava'
                  AND external_id = :strava_id
                LIMIT 1
            """),
            {"strava_id": strava_activity_id},
        )
        row = result.fetchone()
        if row is None:
            return None
        hash_val: str | None = row.version_hash
        # If the hash was invalidated by the migration, treat it as absent
        if hash_val == "invalidated_for_type_backfill":
            return None
        return hash_val

    def _build_outbox_event(
        self,
        transformed: TransformedActivity,
        sync_action: str = "created",
        existing_journal_id: int | None = None,
    ) -> OutboxEvent:
        """Build an outbox event from a transformed Strava activity.

        Constructs the ``journal_data`` and ``calendar_info_data`` payloads
        expected by ``JournalOutboxEventProcessor``, including fitness-specific
        fields (``fitness_data``, ``journal_types``, ``gpx_xml``).

        Args:
            transformed: Output from ``StravaDataTransformer.transform()``.
            sync_action: ``'created'`` for new activities, ``'updated'`` for
                re-imports of already-imported activities.
            existing_journal_id: Journal ID if updating an existing import.

        Returns:
            ``OutboxEvent`` ready to be persisted.
        """
        journal_data: dict[str, Any] = {
            "user_id": self._user_id,
            "title": transformed.title,
            "content": transformed.content or "",
            "event_date_range_start": transformed.event_date_range.start.isoformat(),
            "event_date_range_end": transformed.event_date_range.end.isoformat(),
            "journal_types": [jt.value for jt in transformed.journal_types],
            "fitness_data": {
                "distance": transformed.fitness_data_distance,
                "elevation_gain": transformed.fitness_data_elevation_gain,
                "elevation_loss": transformed.elevation_loss,
                "duration": transformed.fitness_data_duration,
                "calories": transformed.fitness_data_calories,
                "heart_rate_avg": transformed.fitness_data_heart_rate_avg,
                "heart_rate_max": transformed.fitness_data_heart_rate_max,
                "strava_activity_id": transformed.fitness_data_strava_activity_id,
            },
            "strava_athletes": transformed.strava_athletes,
            "gpx_xml": transformed.gpx_xml,
            "version_hash": transformed.version_hash,
        }

        # Strava doesn't use calendars, but the outbox event schema requires
        # calendar_info_data for compatibility with the inbound processor.
        calendar_info_data: dict[str, Any] = {
            "calendar_id": _STRAVA_SYNTHETIC_CALENDAR_ID,
            "is_all_day": False,
            "location": None,
            "start_time": None,
            "end_time": None,
            "event_state": "confirmed",
        }

        return OutboxEvent.create_journal_sync_event(
            journal_data=journal_data,
            calendar_info_data=calendar_info_data,
            integration_source="strava",
            external_event_id=f"strava:{transformed.fitness_data_strava_activity_id}",
            calendar_id=_STRAVA_SYNTHETIC_CALENDAR_ID,
            sync_action=sync_action,
            existing_journal_id=existing_journal_id,
        )
