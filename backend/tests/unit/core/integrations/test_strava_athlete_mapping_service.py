"""A Strava athlete can only be mapped to the mapping user's own contact.

The contact is resolved for the user before the unit of work opens, so a
missing or foreign contact is refused before any mapping, journal link or
unmatched-athlete row is touched. The rows themselves are proven in
``tests/integration/api/integrations/test_strava_athlete_mappings_api.py``.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.contacts.models.repositories import ContactRepository
from app.core.integrations.adapters.sql.journal_unmatched_strava_athlete_repository import (
    SqlJournalUnmatchedStravaAthleteRepository,
)
from app.core.integrations.adapters.sql.strava_athlete_mapping_repository import (
    SqlStravaAthleteMappingRepository,
)
from app.core.integrations.strava.athlete_mapping_service import (
    StravaAthleteMappingService,
)
from app.core.journal.models.repositories import JournalContactRelationshipRepository

USER_ID = "user-1"
CONTACT_ID = 42
ATHLETE_ID = "athlete-1"


@pytest.mark.asyncio
async def test_a_contact_the_user_does_not_own_is_refused_before_any_write() -> None:
    mapping_repo = AsyncMock(spec=SqlStravaAthleteMappingRepository)
    unmatched_repo = AsyncMock(spec=SqlJournalUnmatchedStravaAthleteRepository)
    contact_repo = AsyncMock(spec=ContactRepository)
    # Missing and foreign alike: the owner-scoped read finds nothing.
    contact_repo.find_by_id.return_value = None
    relationship_repo = AsyncMock(spec=JournalContactRelationshipRepository)
    service = StravaAthleteMappingService(
        connection=MagicMock(spec=AsyncConnection),
        mapping_repo=mapping_repo,
        unmatched_repo=unmatched_repo,
        contact_repo=contact_repo,
        contact_relationship_repo=relationship_repo,
    )

    with pytest.raises(ContactNotFoundError):
        await service.create_mapping(USER_ID, ATHLETE_ID, "Jane Doe", CONTACT_ID)

    contact_repo.find_by_id.assert_awaited_once_with(CONTACT_ID, user_id=USER_ID)
    mapping_repo.save.assert_not_called()
    unmatched_repo.get_journal_ids_by_strava_id.assert_not_called()
    unmatched_repo.delete_by_strava_id.assert_not_called()
    relationship_repo.create.assert_not_called()
