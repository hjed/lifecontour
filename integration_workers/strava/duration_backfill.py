"""
One-off backfill of Strava fitness durations from moving time to elapsed time.

Strava journals were once synced with ``moving_time`` as their duration; it is
now ``elapsed_time``. Re-syncing would overwrite whatever the user has edited,
so instead this compares each journal's stored duration with what the sync
would have written and corrects only an exact match. The comparison happens in
the backend, atomically, as a compare-and-set: the worker sends the values the
sync could have written (``expected_durations``) and the duration to store.

A journal may hold several Strava activities: an ADDITIVE merge sums their
durations and keeps every Strava link on the survivor, so the totals here are
sums over all of a journal's linked activities.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from typing import Any

import structlog
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from strava_api_client import StravaAPIClient

logger = structlog.get_logger(__name__)

# A journal links to at most this many activities before only the all-moving
# total is expected: 2**n - 1 mixed totals grow quickly, and merges of more
# than a handful of activities are implausible.
MAX_MIXED_LINKS = 6


@dataclass(frozen=True)
class ActivityTimes:
    """The two durations Strava reports for an activity, in seconds."""

    moving_time: int
    elapsed_time: int


@dataclass(frozen=True)
class DurationCorrection:
    """A journal's duration to correct, and the values that prove it unedited."""

    journal_id: int
    expected_durations: tuple[int, ...]
    corrected_duration: int
    strava_activity_ids: tuple[str, ...]


def _expected_durations(times: Sequence[ActivityTimes]) -> tuple[int, ...]:
    """Every total the sync could have stored, except the already correct one.

    Each activity contributed its moving time (synced before the fix) or its
    elapsed time (re-synced after it, then merged). The all-elapsed total is
    excluded: a journal holding it needs no correction.
    """
    corrected = sum(t.elapsed_time for t in times)
    if len(times) > MAX_MIXED_LINKS:
        totals = {sum(t.moving_time for t in times)}
    else:
        totals = {
            sum(choice)
            for choice in product(*((t.moving_time, t.elapsed_time) for t in times))
        }
    totals.discard(corrected)
    return tuple(sorted(totals))


def plan_corrections(
    links: Mapping[int, Sequence[str]],
    activities: Mapping[str, ActivityTimes],
) -> list[DurationCorrection]:
    """Plan the duration correction for each Strava-linked journal.

    Args:
        links: Journal id → the Strava activity ids linked to it.
        activities: Strava activity id → its moving and elapsed times.

    Returns:
        One correction per journal whose duration would change, in journal
        order. A journal with any linked activity missing from
        ``activities`` (e.g. deleted on Strava) is skipped: without that
        activity's moving time the synced value is unknown.
    """
    corrections: list[DurationCorrection] = []
    for journal_id in sorted(links):
        activity_ids = tuple(links[journal_id])
        if not activity_ids or any(a not in activities for a in activity_ids):
            continue
        times = [activities[a] for a in activity_ids]
        expected = _expected_durations(times)
        if not expected:
            continue
        corrections.append(
            DurationCorrection(
                journal_id=journal_id,
                expected_durations=expected,
                corrected_duration=sum(t.elapsed_time for t in times),
                strava_activity_ids=activity_ids,
            )
        )
    return corrections


class StravaDurationBackfillService:
    """Emits the duration corrections for one user's Strava journals.

    Every page of the athlete's activities is listed before anything is
    written, so a failure part-way (e.g. a rate limit) leaves no events
    behind and the job can simply run again.

    Args:
        api_client: Authenticated ``StravaAPIClient`` for the user.
        user_id: Internal user ID that owns the Strava connection.
    """

    # Strava's maximum page size for the activity list.
    PAGE_SIZE = 200

    def __init__(self, api_client: StravaAPIClient, user_id: str) -> None:
        self._api_client = api_client
        self._user_id = user_id

    async def run(self, session_factory: Any) -> dict[str, int]:
        """List the activities, plan the corrections and write their events.

        Args:
            session_factory: Async session factory; the events are written
                and committed in one transaction.

        Returns:
            Dict with the number of Strava-linked ``journals`` and of
            ``corrections`` emitted.
        """
        activities = await self._fetch_activity_times()

        async with session_factory() as session:
            links = await self._load_links(session)
            corrections = plan_corrections(links, activities)
            for correction in corrections:
                session.add(
                    OutboxEvent.create_fitness_duration_correction_event(
                        journal_id=correction.journal_id,
                        user_id=self._user_id,
                        expected_durations=list(correction.expected_durations),
                        corrected_duration=correction.corrected_duration,
                        strava_activity_ids=list(correction.strava_activity_ids),
                    )
                )
            await session.commit()

        logger.info(
            "Strava duration backfill planned",
            user_id=self._user_id,
            activities=len(activities),
            journals=len(links),
            corrections=len(corrections),
        )
        return {"journals": len(links), "corrections": len(corrections)}

    async def _fetch_activity_times(self) -> dict[str, ActivityTimes]:
        """Page through all of the athlete's activities."""
        times: dict[str, ActivityTimes] = {}
        page = 1
        while True:
            activities = await self._api_client.list_activities(
                page=page, per_page=self.PAGE_SIZE
            )
            if not activities:
                return times
            for activity in activities:
                times[str(activity.id)] = ActivityTimes(
                    moving_time=activity.moving_time,
                    elapsed_time=activity.elapsed_time,
                )
            page += 1

    async def _load_links(self, session: AsyncSession) -> dict[int, list[str]]:
        """Journal id → Strava activity ids, for the user's journals.

        ``sync_metadata`` holds the links (several per journal after an
        ADDITIVE merge); ``journal_fitness_data.strava_activity_id`` is read
        too, as the sync's own dedup does, for journals linked only by it.
        """
        result = await session.execute(
            text("""
                SELECT internal_id AS journal_id, external_id AS activity_id
                FROM sync_metadata
                WHERE integration_source = 'strava'
                  AND internal_entity_type = 'journal'
                  AND internal_id IS NOT NULL
                  AND user_id = :user_id
                UNION
                SELECT f.journal_id, f.strava_activity_id
                FROM journal_fitness_data f
                JOIN journals j ON j.id = f.journal_id
                WHERE f.strava_activity_id IS NOT NULL
                  AND j.user_id = :user_id
            """),
            {"user_id": self._user_id},
        )
        links: dict[int, list[str]] = defaultdict(list)
        for row in result:
            links[row.journal_id].append(row.activity_id)
        return {journal_id: sorted(ids) for journal_id, ids in links.items()}
