"""Repository interfaces for the journal domain."""

from abc import ABC, abstractmethod
from uuid import UUID

from core_shared.models.route import Route

from .calendar import Calendar
from .calendar_info import CalendarInfo
from .entities import Journal
from .journal_contact_relationship import JournalContactRelationship
from .journal_relationship_types import JournalContactRelationshipType
from .journal_tag import JournalTag
from .mood_data import MoodData
from .photo_album_data import PhotoAlbumData
from .plan_data import PlanData, PlanDocument
from .travel_data import (
    TravelAccommodation,
    TravelData,
    TravelFlight,
    TravelTransportation,
)


class JournalRepository(ABC):
    """
    Repository interface for journal operations.

    Provides basic CRUD operations and hierarchy queries for journals.
    Implementations handle database-specific logic.
    """

    @abstractmethod
    async def find_by_id(self, journal_id: int) -> Journal | None:
        """
        Find a journal by ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The Journal if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, journal: Journal) -> Journal:
        """
        Save a journal (insert or update).

        Args:
            journal: The journal to save

        Returns:
            The saved journal with updated fields (id, timestamps)
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete a journal by ID.

        Args:
            journal_id: The journal ID to delete
        """
        pass

    @abstractmethod
    async def get_children(self, parent_id: int) -> list[Journal]:
        """
        Get child journals of a parent.

        Children are ordered by event_date_range.start, then by order field.

        Args:
            parent_id: The parent journal ID

        Returns:
            List of child journals in order
        """
        pass

    @abstractmethod
    async def get_ancestors(self, journal_id: int) -> list[Journal]:
        """
        Get all ancestor journals of a given journal (from parent to root).

        Used to calculate hierarchy depth and detect cycles.

        Args:
            journal_id: The journal ID to find ancestors for

        Returns:
            List of ancestor journals ordered from immediate parent to root
        """
        pass

    @abstractmethod
    async def get_depth(self, journal_id: int) -> int:
        """
        Get the depth of a journal in the hierarchy.

        Root journals have depth 1.

        Args:
            journal_id: The journal ID

        Returns:
            The depth of the journal (1 for root, 2 for first-level child, etc.)
        """
        pass

    @abstractmethod
    async def get_all(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
        journal_type: str | None = None,
    ) -> list[Journal]:
        """
        Get all journals for a user with pagination.

        Args:
            user_id: The user ID to filter by
            limit: Maximum number of journals to return
            offset: Number of journals to skip
            journal_type: Optional journal type to filter by (e.g., "MOOD_RATING", "EVENT")

        Returns:
            List of journals
        """
        pass

    @abstractmethod
    async def get_root_journals(
        self, user_id: str, limit: int = 100, offset: int = 0
    ) -> list[Journal]:
        """
        Get root journals (no parent) for a user.

        Args:
            user_id: The user ID to filter by
            limit: Maximum number of journals to return
            offset: Number of journals to skip

        Returns:
            List of root journals
        """
        pass

    @abstractmethod
    async def count_by_user(self, user_id: str) -> int:
        """
        Count total journals for a user.

        Args:
            user_id: The user ID to count journals for

        Returns:
            Total count of journals
        """
        pass


class CalendarRepository(ABC):
    """
    Repository interface for calendar operations.

    Calendars are used to organize journals and optionally sync with Google Calendar.
    """

    @abstractmethod
    async def find_by_id(self, calendar_id: UUID) -> Calendar | None:
        """
        Find a calendar by ID.

        Args:
            calendar_id: The calendar UUID to look up

        Returns:
            The Calendar if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, calendar: Calendar) -> Calendar:
        """
        Save a calendar (insert or update).

        Args:
            calendar: The calendar to save

        Returns:
            The saved calendar with updated fields (id, timestamps)
        """
        pass

    @abstractmethod
    async def delete(self, calendar_id: UUID) -> None:
        """
        Delete a calendar by ID.

        Args:
            calendar_id: The calendar UUID to delete
        """
        pass

    @abstractmethod
    async def get_all(self, user_id: str) -> list[Calendar]:
        """
        Get all calendars for a user.

        Args:
            user_id: The user ID to filter by

        Returns:
            List of calendars
        """
        pass

    @abstractmethod
    async def get_synced_calendars(self, user_id: str) -> list[Calendar]:
        """
        Get all calendars synced to Google Calendar for a user.

        Args:
            user_id: The user ID to filter by

        Returns:
            List of synced calendars
        """
        pass


class CalendarInfoRepository(ABC):
    """
    Repository interface for calendar info (EVENT type) operations.

    A journal has the EVENT type if a CalendarInfo row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> CalendarInfo | None:
        """
        Find calendar info by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The CalendarInfo if found (journal has EVENT type), None otherwise
        """
        pass

    @abstractmethod
    async def save(self, calendar_info: CalendarInfo) -> CalendarInfo:
        """
        Save calendar info (insert or update).

        This effectively adds or updates the EVENT type for a journal.

        Args:
            calendar_info: The calendar info to save

        Returns:
            The saved calendar info with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete calendar info by journal ID.

        This effectively removes the EVENT type from a journal.

        Args:
            journal_id: The journal ID to delete calendar info for
        """
        pass

    @abstractmethod
    async def get_by_calendar_id(self, calendar_id: UUID) -> list[CalendarInfo]:
        """
        Get all calendar info entries for a calendar.

        Args:
            calendar_id: The calendar UUID to filter by

        Returns:
            List of calendar info entries
        """
        pass


class MoodDataRepository(ABC):
    """
    Repository interface for mood data (MOOD_RATING type) operations.

    A journal has the MOOD_RATING type if a MoodData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> MoodData | None:
        """
        Find mood data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The MoodData if found (journal has MOOD_RATING type), None otherwise
        """
        pass

    @abstractmethod
    async def save(self, mood_data: MoodData) -> MoodData:
        """
        Save mood data (insert or update).

        This effectively adds or updates the MOOD_RATING type for a journal.

        Args:
            mood_data: The mood data to save

        Returns:
            The saved mood data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete mood data by journal ID.

        This effectively removes the MOOD_RATING type from a journal.

        Args:
            journal_id: The journal ID to delete mood data for
        """
        pass


class PhotoAlbumDataRepository(ABC):
    """
    Repository interface for photo album data (PHOTO_ALBUM type) operations.

    A journal has the PHOTO_ALBUM type if a PhotoAlbumData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> PhotoAlbumData | None:
        """
        Find photo album data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The PhotoAlbumData if found (journal has PHOTO_ALBUM type), None otherwise
        """
        pass

    @abstractmethod
    async def save(self, photo_album_data: PhotoAlbumData) -> PhotoAlbumData:
        """
        Save photo album data (insert or update).

        This effectively adds or updates the PHOTO_ALBUM type for a journal.

        Args:
            photo_album_data: The photo album data to save

        Returns:
            The saved photo album data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete photo album data by journal ID.

        This effectively removes the PHOTO_ALBUM type from a journal.

        Args:
            journal_id: The journal ID to delete photo album data for
        """
        pass


class PlanDataRepository(ABC):
    """
    Repository interface for plan data (PLAN type) operations.

    A journal has the PLAN type if a PlanData row exists for its journal_id.
    Plan documents are managed separately but loaded with plan data.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> PlanData | None:
        """
        Find plan data by journal ID, including associated documents.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The PlanData with documents if found (journal has PLAN type), None otherwise
        """
        pass

    @abstractmethod
    async def save(self, plan_data: PlanData) -> PlanData:
        """
        Save plan data (insert or update).

        This effectively adds or updates the PLAN type for a journal.
        Documents are saved separately.

        Args:
            plan_data: The plan data to save

        Returns:
            The saved plan data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete plan data by journal ID.

        This effectively removes the PLAN type from a journal.
        Associated documents are cascade deleted.

        Args:
            journal_id: The journal ID to delete plan data for
        """
        pass

    @abstractmethod
    async def save_document(self, document: PlanDocument) -> PlanDocument:
        """
        Save a plan document (insert or update).

        Args:
            document: The plan document to save

        Returns:
            The saved plan document with updated timestamps
        """
        pass

    @abstractmethod
    async def delete_document(self, document_id: UUID) -> None:
        """
        Delete a plan document by ID.

        Args:
            document_id: The document UUID to delete
        """
        pass

    @abstractmethod
    async def get_documents(self, journal_id: int) -> list[PlanDocument]:
        """
        Get all documents for a plan, ordered by order field.

        Args:
            journal_id: The journal ID to get documents for

        Returns:
            List of plan documents in order
        """
        pass


class TravelDataRepository(ABC):
    """
    Repository interface for travel data (TRAVEL type) operations.

    A journal has the TRAVEL type if a TravelData row exists for its journal_id.
    Travel components (flights, accommodations, transportation) are managed separately
    but loaded with travel data.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> TravelData | None:
        """
        Find travel data by journal ID, including all associated components.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The TravelData with all components if found (journal has TRAVEL type), None otherwise
        """
        pass

    @abstractmethod
    async def save(self, travel_data: TravelData) -> TravelData:
        """
        Save travel data (insert or update).

        This effectively adds or updates the TRAVEL type for a journal.
        Components are saved separately.

        Args:
            travel_data: The travel data to save

        Returns:
            The saved travel data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete travel data by journal ID.

        This effectively removes the TRAVEL type from a journal.
        Associated components are cascade deleted.

        Args:
            journal_id: The journal ID to delete travel data for
        """
        pass

    @abstractmethod
    async def save_flight(self, flight: TravelFlight) -> TravelFlight:
        """
        Save a travel flight (insert or update).

        Args:
            flight: The travel flight to save

        Returns:
            The saved travel flight with updated timestamps
        """
        pass

    @abstractmethod
    async def delete_flight(self, flight_id: UUID) -> None:
        """
        Delete a travel flight by ID.

        Args:
            flight_id: The flight UUID to delete
        """
        pass

    @abstractmethod
    async def save_accommodation(
        self, accommodation: TravelAccommodation
    ) -> TravelAccommodation:
        """
        Save a travel accommodation (insert or update).

        Args:
            accommodation: The travel accommodation to save

        Returns:
            The saved travel accommodation with updated timestamps
        """
        pass

    @abstractmethod
    async def delete_accommodation(self, accommodation_id: UUID) -> None:
        """
        Delete a travel accommodation by ID.

        Args:
            accommodation_id: The accommodation UUID to delete
        """
        pass

    @abstractmethod
    async def save_transportation(
        self, transportation: TravelTransportation
    ) -> TravelTransportation:
        """
        Save a travel transportation (insert or update).

        Args:
            transportation: The travel transportation to save

        Returns:
            The saved travel transportation with updated timestamps
        """
        pass

    @abstractmethod
    async def delete_transportation(self, transportation_id: UUID) -> None:
        """
        Delete a travel transportation by ID.

        Args:
            transportation_id: The transportation UUID to delete
        """
        pass


class JournalTagRepository(ABC):
    """
    Repository interface for journal tag operations.

    Tags are hierarchical (parent-child relationships) and can be assigned to journals.
    """

    @abstractmethod
    async def find_by_id(self, tag_id: UUID) -> JournalTag | None:
        """
        Find a tag by ID.

        Args:
            tag_id: The tag UUID to look up

        Returns:
            The JournalTag if found, None otherwise
        """
        pass

    @abstractmethod
    async def find_by_name(self, name: str) -> JournalTag | None:
        """
        Find a tag by name.

        Args:
            name: The tag name to look up

        Returns:
            The JournalTag if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, tag: JournalTag) -> JournalTag:
        """
        Save a tag (insert or update).

        Args:
            tag: The tag to save

        Returns:
            The saved tag with updated fields (id, timestamps)
        """
        pass

    @abstractmethod
    async def delete(self, tag_id: UUID) -> None:
        """
        Delete a tag by ID.

        Args:
            tag_id: The tag UUID to delete
        """
        pass

    @abstractmethod
    async def get_all(self) -> list[JournalTag]:
        """
        Get all tags.

        Returns:
            List of all tags
        """
        pass

    @abstractmethod
    async def get_children(self, parent_id: UUID) -> list[JournalTag]:
        """
        Get child tags of a parent tag.

        Args:
            parent_id: The parent tag UUID

        Returns:
            List of child tags
        """
        pass

    @abstractmethod
    async def get_root_tags(self) -> list[JournalTag]:
        """
        Get all root tags (no parent).

        Returns:
            List of root tags
        """
        pass

    @abstractmethod
    async def get_tags_for_journal(self, journal_id: int) -> list[JournalTag]:
        """
        Get all tags assigned to a journal.

        Args:
            journal_id: The journal ID to get tags for

        Returns:
            List of tags assigned to the journal
        """
        pass

    @abstractmethod
    async def assign_tag(self, journal_id: int, tag_id: UUID) -> None:
        """
        Assign a tag to a journal.

        Args:
            journal_id: The journal ID
            tag_id: The tag UUID to assign
        """
        pass

    @abstractmethod
    async def remove_tag(self, journal_id: int, tag_id: UUID) -> None:
        """
        Remove a tag from a journal.

        Args:
            journal_id: The journal ID
            tag_id: The tag UUID to remove
        """
        pass


class JournalContactRelationshipRepository(ABC):
    """
    Repository interface for journal-contact relationship operations.

    Manages relationships between journals and contacts with different relationship types.
    """

    @abstractmethod
    async def create(
        self, relationship: JournalContactRelationship
    ) -> JournalContactRelationship:
        """
        Create a new journal-contact relationship.

        Args:
            relationship: The relationship to create

        Returns:
            The created relationship with created_at timestamp
        """
        pass

    @abstractmethod
    async def delete(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
    ) -> None:
        """
        Delete a specific journal-contact relationship.

        Args:
            journal_id: The journal ID
            contact_id: The contact ID
            relationship_type: The relationship type to delete
        """
        pass

    @abstractmethod
    async def get_by_journal(self, journal_id: int) -> list[JournalContactRelationship]:
        """
        Get all relationships for a journal.

        Args:
            journal_id: The journal ID to filter by

        Returns:
            List of relationships for the journal
        """
        pass

    @abstractmethod
    async def get_by_contact(self, contact_id: int) -> list[JournalContactRelationship]:
        """
        Get all relationships for a contact.

        Args:
            contact_id: The contact ID to filter by

        Returns:
            List of relationships for the contact
        """
        pass

    @abstractmethod
    async def get_by_journal_and_type(
        self, journal_id: int, relationship_type: JournalContactRelationshipType
    ) -> list[JournalContactRelationship]:
        """
        Get all relationships of a specific type for a journal.

        Args:
            journal_id: The journal ID to filter by
            relationship_type: The relationship type to filter by

        Returns:
            List of relationships matching the criteria
        """
        pass


class RouteRepository(ABC):
    """
    Repository interface for route operations.

    Routes are shared across multiple activity types (BUSHWALKING, CANYONING,
    CLIMBING, KAYAKING, CROSS_COUNTRY_SKIING, JOGGING) and are user-specific.
    """

    @abstractmethod
    async def find_by_id(self, route_id: UUID) -> Route | None:
        """
        Find a route by ID.

        Args:
            route_id: The route UUID to look up

        Returns:
            The Route if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, route: Route) -> Route:
        """
        Save a route (insert or update).

        Args:
            route: The route to save

        Returns:
            The saved route with updated fields (id, timestamps)
        """
        pass

    @abstractmethod
    async def delete(self, route_id: UUID) -> None:
        """
        Delete a route by ID.

        Args:
            route_id: The route UUID to delete
        """
        pass

    @abstractmethod
    async def get_all(
        self, user_id: str, limit: int = 100, offset: int = 0
    ) -> list[Route]:
        """
        Get all routes for a user with pagination.

        Args:
            user_id: The user ID to filter by
            limit: Maximum number of routes to return
            offset: Number of routes to skip

        Returns:
            List of routes
        """
        pass

    @abstractmethod
    async def get_count(self, user_id: str) -> int:
        """
        Get total count of routes for a user.

        Args:
            user_id: The user ID to filter by

        Returns:
            Total number of routes for the user
        """
        pass

    @abstractmethod
    async def check_usage_in_journals(self, route_id: UUID) -> bool:
        """
        Check if a route is referenced by any journal entries.

        Routes are referenced by activity-specific data tables (journal_bushwalking_data,
        journal_kayaking_data, journal_climbing_data, journal_skiing_data, journal_jogging_data,
        journal_canyoning_data), NOT by the journals table itself.

        This is used to prevent deletion of routes that are in use.

        Args:
            route_id: The route UUID to check

        Returns:
            True if the route is used in any activity-specific journal data, False otherwise
        """
        pass
