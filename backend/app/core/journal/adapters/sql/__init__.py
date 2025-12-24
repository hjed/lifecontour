"""SQL adapters for journal domain."""

from .calendar_info_repository import SqlCalendarInfoRepository
from .calendar_repository import SqlCalendarRepository
from .journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from .journal_repository import SqlJournalRepository
from .journal_tag_repository import SqlJournalTagRepository
from .mood_data_repository import SqlMoodDataRepository
from .photo_album_data_repository import SqlPhotoAlbumDataRepository
from .plan_data_repository import SqlPlanDataRepository
from .travel_data_repository import SqlTravelDataRepository

__all__ = [
    "SqlJournalRepository",
    "SqlCalendarRepository",
    "SqlCalendarInfoRepository",
    "SqlMoodDataRepository",
    "SqlPhotoAlbumDataRepository",
    "SqlPlanDataRepository",
    "SqlTravelDataRepository",
    "SqlJournalTagRepository",
    "SqlJournalContactRelationshipRepository",
]
