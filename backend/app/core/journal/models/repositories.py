"""Repository interfaces for the journal domain."""

from abc import ABC, abstractmethod
from uuid import UUID

from .calendar import Calendar
from .calendar_info import CalendarInfo
from .entities import Journal
from .mood_data import MoodData


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
        self, user_id: str, limit: int = 100, offset: int = 0
    ) -> list[Journal]:
        """
        Get all journals for a user with pagination.

        Args:
            user_id: The user ID to filter by
            limit: Maximum number of journals to return
            offset: Number of journals to skip

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
