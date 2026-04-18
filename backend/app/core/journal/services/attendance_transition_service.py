"""Attendance transition service for post-event status updates.

Automatically transitions contacts with ATTENDING status to ATTENDED
for events that have passed.
"""

from dataclasses import dataclass
from datetime import datetime

import structlog
from core_shared.models.journals.attendee_status import AttendeeStatus

from app.core.journal.models.repositories import JournalContactRelationshipRepository

logger = structlog.get_logger()


@dataclass
class TransitionResult:
    """Result of an attendance transition run.

    Attributes:
        transitioned_count: Number of relationships transitioned from ATTENDING to ATTENDED.
    """

    transitioned_count: int


class AttendanceTransitionService:
    """Service for transitioning ATTENDING → ATTENDED on past events.

    Idempotent: re-running after all eligible rows have been transitioned
    produces zero changes.
    """

    def __init__(self, repo: JournalContactRelationshipRepository) -> None:
        """Initialize with a journal-contact relationship repository.

        Args:
            repo: Repository for querying and updating journal-contact relationships.
        """
        self.repo = repo

    async def transition_past_event_attendees(
        self,
        cutoff_time: datetime,
        batch_size: int = 100,
    ) -> TransitionResult:
        """Transition ATTENDING contacts to ATTENDED for past events.

        Finds journal-contact relationships where status is ATTENDING and the
        journal's event_date_range.end is before cutoff_time, then updates
        each to ATTENDED.

        Args:
            cutoff_time: Events ending before this time are considered past.
            batch_size: Maximum number of relationships to process per call.

        Returns:
            TransitionResult with the count of transitioned relationships.
        """
        eligible = await self.repo.find_attending_for_past_events(
            cutoff_time=cutoff_time,
            batch_size=batch_size,
        )

        if not eligible:
            logger.debug(
                "No eligible attendance transitions found",
                cutoff_time=cutoff_time.isoformat(),
            )
            return TransitionResult(transitioned_count=0)

        transitioned = 0
        for rel in eligible:
            await self.repo.update_status(
                journal_id=rel.journal_id,
                contact_id=rel.contact_id,
                relationship_type=rel.relationship_type,
                status=AttendeeStatus.ATTENDED,
            )
            transitioned += 1

        logger.info(
            "Attendance transitions completed",
            transitioned_count=transitioned,
            batch_size=batch_size,
            cutoff_time=cutoff_time.isoformat(),
        )

        return TransitionResult(transitioned_count=transitioned)
