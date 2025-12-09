"""Base repository for journal type-specific data."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, TypeVar

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

# Type variable for the data entity
T = TypeVar("T")


class BaseJournalDataRepository(ABC):
    """
    Base repository for journal type-specific data.

    Provides common functionality for repositories that manage
    journal type data with one-to-one relationships to journals.
    """

    def __init__(self, connection: AsyncConnection):
        """
        Initialize the repository with a database connection.

        Args:
            connection: SQLAlchemy async connection
        """
        self.connection = connection

    @property
    @abstractmethod
    def table_name(self) -> str:
        """Return the table name for this repository."""

    @property
    @abstractmethod
    def validation_error_class(self) -> type[Exception]:
        """Return the validation error class for this repository."""

    @abstractmethod
    def _row_to_entity(self, row: Any) -> T:
        """Convert a database row to an entity."""

    @abstractmethod
    def _entity_to_insert_params(self, entity: T, created_at: datetime) -> dict[str, Any]:
        """Convert an entity to insert parameters."""

    @abstractmethod
    def _entity_to_update_params(self, entity: T, updated_at: datetime) -> dict[str, Any]:
        """Convert an entity to update parameters."""

    async def find_by_journal_id(self, journal_id: int) -> T | None:
        """
        Find data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The entity if found, None otherwise
        """
        query = text(f"""
            SELECT *
            FROM {self.table_name}
            WHERE journal_id = :journal_id
        """)

        result = await self.connection.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if row is None:
            return None

        return self._row_to_entity(row)

    async def save(self, entity: T) -> T:
        """
        Save data (insert or update).

        Args:
            entity: The entity to save

        Returns:
            The saved entity with updated timestamps

        Raises:
            ValidationError: If database constraints are violated
        """
        now = datetime.now(timezone.utc)

        # Check if record exists
        journal_id = getattr(entity, "journal_id")
        existing = await self.find_by_journal_id(journal_id)

        try:
            if existing is None:
                # Insert new record
                params = self._entity_to_insert_params(entity, now)
                columns = ", ".join(params.keys())
                placeholders = ", ".join(f":{key}" for key in params.keys())

                query = text(f"""
                    INSERT INTO {self.table_name} ({columns})
                    VALUES ({placeholders})
                """)

                await self.connection.execute(query, params)
            else:
                # Update existing record
                params = self._entity_to_update_params(entity, now)
                set_clause = ", ".join(f"{key} = :{key}" for key in params.keys())

                query = text(f"""
                    UPDATE {self.table_name}
                    SET {set_clause}
                    WHERE journal_id = :journal_id
                """)

                params["journal_id"] = journal_id
                await self.connection.execute(query, params)

            # Return updated entity
            return await self.find_by_journal_id(journal_id)

        except IntegrityError as e:
            raise self.validation_error_class(
                "database", f"Database constraint violation: {e}"
            ) from e

    async def delete(self, journal_id: int) -> None:
        """
        Delete data by journal ID.

        Args:
            journal_id: The journal ID to delete data for
        """
        query = text(f"""
            DELETE FROM {self.table_name}
            WHERE journal_id = :journal_id
        """)

        await self.connection.execute(query, {"journal_id": journal_id})

    def _get_now(self) -> datetime:
        """Get current UTC datetime."""
        return datetime.now(timezone.utc)
