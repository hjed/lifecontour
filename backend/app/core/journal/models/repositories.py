"""Repository interfaces for the journal domain."""

from abc import ABC, abstractmethod

from .entities import Journal


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
