import structlog
from core_shared.models.journals.attendee_status import AttendeeStatus
from core_shared.models.journals.journal_contact_relationship import (
    JournalContactRelationship,
)
from core_shared.models.journals.journal_relationship_types import (
    JournalContactRelationshipType,
)
from core_shared.models.strava_athlete_mapping import StravaAthleteMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.contacts.models.repositories import ContactRepository
from app.core.integrations.adapters.sql.journal_unmatched_strava_athlete_repository import (
    SqlJournalUnmatchedStravaAthleteRepository,
)
from app.core.integrations.adapters.sql.strava_athlete_mapping_repository import (
    SqlStravaAthleteMappingRepository,
)
from app.core.journal.models.repositories import JournalContactRelationshipRepository
from app.infrastructure.unit_of_work import savepoint, unit_of_work

logger = structlog.get_logger()


class StravaAthleteMappingService:
    """Service for managing Strava athlete mappings and retroactive journaling."""

    def __init__(
        self,
        connection: AsyncConnection,
        mapping_repo: SqlStravaAthleteMappingRepository,
        unmatched_repo: SqlJournalUnmatchedStravaAthleteRepository,
        contact_repo: ContactRepository,
        contact_relationship_repo: JournalContactRelationshipRepository,
    ) -> None:
        self.connection = connection
        self.mapping_repo = mapping_repo
        self.unmatched_repo = unmatched_repo
        self.contact_repo = contact_repo
        self.contact_relationship_repo = contact_relationship_repo

    async def get_all_mappings(self, user_id: str) -> list[StravaAthleteMapping]:
        """Get all mappings for a user."""
        return await self.mapping_repo.get_all_by_user_id(user_id)

    async def delete_mapping(self, user_id: str, strava_athlete_id: str) -> bool:
        """Delete a mapping as a committed unit of work."""
        async with unit_of_work(self.connection):
            return await self.mapping_repo.delete_by_strava_id(
                user_id, strava_athlete_id
            )

    async def create_mapping(
        self,
        user_id: str,
        strava_athlete_id: str,
        strava_athlete_name: str,
        contact_id: int,
    ) -> StravaAthleteMapping:
        """
        Create a mapping and retroactively add the contact to existing journals
        that contain the unmatched athlete.
        """
        # The contact must be the user's own; another's is not found.
        contact = await self.contact_repo.find_by_id(contact_id, user_id=user_id)
        if not contact:
            raise ContactNotFoundError(contact_id)

        mapping = StravaAthleteMapping(
            user_id=user_id,
            strava_athlete_id=strava_athlete_id,
            strava_athlete_name=strava_athlete_name,
            contact_id=contact_id,
        )

        async with unit_of_work(self.connection):
            # 1. Save mapping
            saved_mapping = await self.mapping_repo.save(mapping)

            # 2. Find unmatched journals for this athlete
            journal_ids = await self.unmatched_repo.get_journal_ids_by_strava_id(
                user_id, strava_athlete_id
            )

            # 3. Add contact as participant to each journal
            for journal_id in journal_ids:
                try:
                    # Isolate insert so PK violations don't invalidate the unit of work
                    async with savepoint(self.connection):
                        relationship = JournalContactRelationship(
                            journal_id=journal_id,
                            contact_id=contact_id,
                            relationship_type=JournalContactRelationshipType.PARTICIPANT,
                            status=AttendeeStatus.ATTENDED,
                        )
                        await self.contact_relationship_repo.create(relationship)
                except IntegrityError as e:
                    logger.info(
                        "Contact is already a participant on journal",
                        journal_id=journal_id,
                        contact_id=contact_id,
                        error=str(e),
                    )
                    # Ignore unique constraint violations (already a participant)

            # 4. Remove from unmatched athletes
            await self.unmatched_repo.delete_by_strava_id(user_id, strava_athlete_id)

        return saved_mapping
