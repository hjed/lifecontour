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

from typing import Any

import structlog
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from strava_api_client import StravaAPIClient
from strava_data_transformer import StravaDataTransformer, TransformedActivity
from strava_models import StravaStreamSet

logger = structlog.get_logger(__name__)

# Synthetic calendar_id for Strava (Strava doesn't use calendars, but the
# outbox event schema requires one for compatibility with the inbound
# processor).  This UUID is deterministic so lookups work.
_STRAVA_SYNTHETIC_CALENDAR_ID = "00000000-0000-0000-0000-000000000001"

# Maximum activities per Strava API page
_PAGE_SIZE = 100


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

    async def sync_full(
        self,
        session: AsyncSession,
        after_timestamp: int | None = None,
    ) -> list[OutboxEvent]:
        """Paginate through all activities and create outbox events.

        Args:
            session: Database session for outbox event persistence.
            after_timestamp: Optional epoch timestamp — only sync activities
                after this time (for incremental sync).

        Returns:
            List of all created outbox events.
        """
        all_events: list[OutboxEvent] = []
        page = 1

        while True:
            activities = await self._api_client.list_activities(
                page=page,
                per_page=_PAGE_SIZE,
                after=after_timestamp,
            )

            if not activities:
                break

            for activity in activities:
                # Deduplication — during full sync, skip already-imported
                existing_jid = await self._find_existing_journal_id(
                    str(activity.id), session
                )
                if existing_jid is not None:
                    logger.debug(
                        "Skipping already-imported activity during full sync",
                        strava_activity_id=activity.id,
                    )
                    continue

                # Fetch streams for GPS-equipped activities
                streams: StravaStreamSet | None = None
                if activity.start_latlng is not None:
                    streams = await self._api_client.get_activity_streams(activity.id)

                transformed = self._transformer.transform(activity, streams=streams)
                event = self._build_outbox_event(transformed)
                session.add(event)
                all_events.append(event)

            page += 1

        logger.info(
            "Full sync completed",
            activities_synced=len(all_events),
            pages_fetched=page - 1,
        )
        return all_events

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
            "gpx_xml": transformed.gpx_xml,
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
