"""Main journal service with transaction management and type dependency resolution."""

from typing import Any

import structlog
from core_shared.models.journals import (
    MAX_HIERARCHY_DEPTH,
    Journal,
    JournalCycleError,
    JournalMaxDepthExceededError,
    JournalNotFoundError,
    JournalType,
    JournalValidationError,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.events import ContactSummaryRefreshRequested
from app.core.journal.models.events import (
    JournalCreated,
    JournalDeleted,
    JournalTypeAdded,
    JournalTypeRemoved,
    JournalUpdated,
)
from app.core.journal.models.repositories import (
    JournalContactRelationshipRepository,
    JournalRepository,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher

logger = structlog.get_logger()


class JournalService:
    """
    Service for managing journals with type dependency resolution.

    Handles:
    - Journal CRUD operations with validation
    - Type dependency resolution (automatic type addition)
    - Hierarchy validation (max depth 5, cycle prevention)
    - Domain event publishing via outbox pattern
    """

    def __init__(
        self,
        journal_repo: JournalRepository,
        event_publisher: OutboxEventPublisher,
        contact_relationship_repo: JournalContactRelationshipRepository | None = None,
    ):
        """
        Initialize the journal service.

        Args:
            journal_repo: Repository for journal persistence
            event_publisher: Publisher for domain events (outbox pattern)
            contact_relationship_repo: Repository for contact relationships
        """
        self.journal_repo = journal_repo
        self.event_publisher = event_publisher
        self.contact_relationship_repo = contact_relationship_repo

    async def create_journal(
        self, journal: Journal, transaction: AsyncConnection
    ) -> Journal:
        """
        Create a new journal with validation.

        Validates hierarchy depth and cycles before creating the journal.
        Publishes JournalCreated event via outbox pattern.

        Args:
            journal: The journal to create
            transaction: Database transaction

        Returns:
            The created journal with ID and timestamps

        Raises:
            JournalValidationError: If validation fails
            JournalMaxDepthExceededError: If hierarchy depth exceeds maximum
            JournalCycleError: If parent relationship would create a cycle
        """
        # Validate hierarchy if journal has a parent
        if journal.parent_id is not None:
            await self._validate_hierarchy(journal.parent_id, transaction)

        # Save the journal
        try:
            saved_journal = await self.journal_repo.save(journal)
        except IntegrityError as e:
            raise JournalValidationError(
                "database", f"Database constraint violation: {e}"
            ) from e

        # Ensure journal has ID after save
        if saved_journal.id is None:
            raise JournalValidationError(
                "id", "Journal ID is required after save operation"
            )

        # Publish creation event
        event = JournalCreated(
            saved_journal.id,
            saved_journal.user_id,
            saved_journal.title,
            transaction=transaction,
        )
        await self.event_publisher.publish(event)

        logger.info(
            "Journal created",
            journal_id=saved_journal.id,
            user_id=saved_journal.user_id,
            title=saved_journal.title,
        )

        return saved_journal

    async def update_journal(
        self,
        journal: Journal,
        changed_fields: dict[str, Any],
        transaction: AsyncConnection,
    ) -> Journal:
        """
        Update an existing journal.

        Validates hierarchy if parent_id is being changed.
        Publishes JournalUpdated event via outbox pattern.

        Args:
            journal: The journal to update (must have id set)
            changed_fields: Dictionary of changed fields for event tracking
            transaction: Database transaction

        Returns:
            The updated journal

        Raises:
            JournalValidationError: If validation fails or journal has no ID
            JournalNotFoundError: If journal doesn't exist
            JournalMaxDepthExceededError: If hierarchy depth exceeds maximum
            JournalCycleError: If parent relationship would create a cycle
        """
        if journal.id is None:
            raise JournalValidationError("id", "Journal ID is required for update")

        # Validate hierarchy if parent_id is being changed
        if "parent_id" in changed_fields and journal.parent_id is not None:
            await self._validate_hierarchy(journal.parent_id, transaction, journal.id)

        # Save the updated journal
        try:
            saved_journal = await self.journal_repo.save(journal)
        except IntegrityError as e:
            raise JournalValidationError(
                "database", f"Database constraint violation: {e}"
            ) from e

        # Ensure journal ID is set (should always be true for updates)
        assert saved_journal.id is not None, "Journal ID must be set after update"

        # Publish update event
        event = JournalUpdated(
            saved_journal.id,
            changed_fields,
            transaction=transaction,
        )
        await self.event_publisher.publish(event)

        # Trigger summary refresh for any associated contacts
        if self.contact_relationship_repo is not None:
            relationships = await self.contact_relationship_repo.get_by_journal(
                saved_journal.id
            )
            for rel in relationships:
                await self.event_publisher.publish(
                    ContactSummaryRefreshRequested(
                        rel.contact_id, transaction=transaction
                    )
                )

        logger.info(
            "Journal updated",
            journal_id=saved_journal.id,
            changed_fields=list(changed_fields.keys()),
        )

        return saved_journal

    async def delete_journal(
        self, journal_id: int, transaction: AsyncConnection
    ) -> None:
        """
        Delete a journal.

        Publishes JournalDeleted event via outbox pattern.
        Note: Type data and relationships are cascade deleted by database constraints.

        Args:
            journal_id: The ID of the journal to delete
            transaction: Database transaction

        Raises:
            JournalNotFoundError: If journal doesn't exist
        """
        # Validate journal exists
        journal = await self.journal_repo.find_by_id(journal_id)
        if journal is None:
            raise JournalNotFoundError(journal_id)

        # Fetch external event IDs before deletion so workers know what to delete
        stmt = text("""
            SELECT jeel.external_event_id, c.google_calendar_id
            FROM journal_external_event_links jeel
            JOIN calendars c ON jeel.calendar_id = c.id
            WHERE jeel.journal_id = :journal_id AND jeel.external_event_id IS NOT NULL
        """)
        result = await transaction.execute(stmt, {"journal_id": journal_id})
        external_identifiers: dict[str, list[dict[str, Any]]] = {}
        # We currently only support Google calendar syncing, so we hardcode the key.
        for row in result.fetchall():
            if "google" not in external_identifiers:
                external_identifiers["google"] = []
            external_identifiers["google"].append(
                {
                    "external_event_id": row.external_event_id,
                    "google_calendar_id": row.google_calendar_id,
                }
            )

        # Delete the journal
        await self.journal_repo.delete(journal_id)

        # Publish deletion event
        event = JournalDeleted(
            journal_id,
            user_id=journal.user_id,
            external_identifiers=external_identifiers,
            transaction=transaction,
        )
        await self.event_publisher.publish(event)

        logger.info("Journal deleted", journal_id=journal_id)

    async def get_journal(self, journal_id: int) -> Journal | None:
        """
        Get a journal by ID.

        Args:
            journal_id: The ID of the journal to retrieve

        Returns:
            The journal if found, None otherwise
        """
        return await self.journal_repo.find_by_id(journal_id)

    async def find_journals_by_ids_for_user(
        self, user_id: str, journal_ids: list[int]
    ) -> list[Journal]:
        """Batch-load journals by ID, scoped to a user."""
        return await self.journal_repo.find_by_ids_for_user(user_id, journal_ids)

    async def get_journals_by_ids_for_user(
        self,
        user_id: str,
        journal_ids: list[int],
        offset: int = 0,
        limit: int = 20,
    ) -> list[Journal]:
        """Get journals by IDs for a user with ordering and pagination."""
        return await self.journal_repo.get_by_ids_for_user(
            user_id=user_id,
            journal_ids=journal_ids,
            limit=limit,
            offset=offset,
        )

    async def count_journals_by_ids_for_user(
        self, user_id: str, journal_ids: list[int]
    ) -> int:
        """Count journals by IDs for a user."""
        return await self.journal_repo.count_by_ids_for_user(user_id, journal_ids)

    async def count_children_for_parents(
        self, user_id: str, parent_ids: list[int]
    ) -> dict[int, int]:
        """Count direct children for each parent journal ID for a user."""
        return await self.journal_repo.count_children_for_parents(
            user_id=user_id, parent_ids=parent_ids
        )

    async def find_descendants_for_user(
        self,
        user_id: str,
        ancestor_ids: list[int],
        max_depth: int = 5,
    ) -> list[Journal]:
        """Find all descendant journals for the given ancestor journals, scoped to a user."""
        return await self.journal_repo.find_descendants_for_user(
            user_id=user_id,
            ancestor_ids=ancestor_ids,
            max_depth=max_depth,
        )

    async def get_journals_paginated(
        self,
        user_id: str,
        offset: int = 0,
        limit: int = 20,
        journal_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        contact_id: str | None = None,
        tag_id: str | None = None,
        calendar_id: str | None = None,
        parent_id: int | None = None,
        search: str | None = None,
    ) -> list[Journal]:
        """
        Get journals for a user with pagination and filtering.

        Args:
            user_id: The user ID to filter by
            offset: Number of journals to skip
            limit: Maximum number of journals to return
            journal_type: Optional journal type to filter by (e.g., "MOOD_RATING", "EVENT")
            start_date: Optional start date filter (ISO format)
            end_date: Optional end date filter (ISO format)
            contact_id: Optional contact ID to filter journals by
            tag_id: Optional tag ID to filter journals by
            calendar_id: Optional calendar ID to filter journals by
            parent_id: Optional parent journal ID to filter by (None for root journals)
            search: Optional search query for full-text search

        Returns:
            List of journals matching the filter criteria
        """
        return await self.journal_repo.get_all(
            user_id,
            limit,
            offset,
            journal_type,
            start_date,
            end_date,
            contact_id,
            tag_id,
            calendar_id,
            parent_id,
            search,
        )

    async def get_journals_count(
        self,
        user_id: str,
        journal_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        contact_id: str | None = None,
        tag_id: str | None = None,
        calendar_id: str | None = None,
        parent_id: int | None = None,
        search: str | None = None,
    ) -> int:
        """
        Get total count of journals for a user with filtering.

        Args:
            user_id: The user ID to count journals for
            journal_type: Optional journal type to filter by
            start_date: Optional start date filter (ISO format)
            end_date: Optional end date filter (ISO format)
            contact_id: Optional contact ID to filter journals by
            tag_id: Optional tag ID to filter journals by
            calendar_id: Optional calendar ID to filter journals by
            parent_id: Optional parent journal ID to filter by
            search: Optional search query for full-text search

        Returns:
            Total count of journals matching the filter criteria
        """
        # If any filters are applied, use the count_all method for efficiency
        if any(
            [
                journal_type,
                start_date,
                end_date,
                contact_id,
                tag_id,
                calendar_id,
                parent_id,
                search,
            ]
        ):
            return await self.journal_repo.count_all(
                user_id,
                journal_type=journal_type,
                start_date=start_date,
                end_date=end_date,
                contact_id=contact_id,
                tag_id=tag_id,
                calendar_id=calendar_id,
                parent_id=parent_id,
                search=search,
            )
        return await self.journal_repo.count_by_user(user_id)

    async def _validate_hierarchy(
        self,
        parent_id: int,
        transaction: AsyncConnection,
        journal_id: int | None = None,
    ) -> None:
        """
        Validate hierarchy constraints.

        Checks:
        1. Parent exists
        2. Maximum depth not exceeded (5 levels)
        3. No cycles (parent cannot be a descendant of the journal)

        Args:
            parent_id: The parent journal ID
            transaction: Database transaction
            journal_id: The journal ID (for cycle detection, None for new journals)

        Raises:
            JournalNotFoundError: If parent doesn't exist
            JournalMaxDepthExceededError: If depth exceeds maximum
            JournalCycleError: If parent relationship would create a cycle
        """
        # Validate parent exists
        parent = await self.journal_repo.find_by_id(parent_id)
        if parent is None:
            raise JournalNotFoundError(parent_id)

        # Check maximum depth
        parent_depth = await self.journal_repo.get_depth(parent_id)
        if parent_depth >= MAX_HIERARCHY_DEPTH:
            raise JournalMaxDepthExceededError(
                max_depth=MAX_HIERARCHY_DEPTH,
                attempted_depth=parent_depth + 1,
            )

        # Check for cycles (parent cannot be a descendant of the journal, or the journal itself)
        if journal_id is not None:
            if parent_id == journal_id:
                raise JournalCycleError(
                    journal_id=journal_id,
                    parent_id=parent_id,
                )

            ancestors = await self.journal_repo.get_ancestors(parent_id)
            ancestor_ids = [a.id for a in ancestors if a.id is not None]
            if journal_id in ancestor_ids:
                raise JournalCycleError(
                    journal_id=journal_id,
                    parent_id=parent_id,
                )

    async def add_type_to_journal(
        self,
        journal_id: int,
        journal_type: JournalType,
        transaction: AsyncConnection,
    ) -> list[JournalType]:
        """
        Add a type to a journal with automatic dependency resolution.

        When a type is added, all its dependent types are automatically added as well.
        For example, adding CANYONING automatically adds BUSHWALKING, ABSEILING_TRIP,
        OUTDOOR_ACTIVITY, and FITNESS (in Iteration 4.5).

        Type-specific data rows are created with NULL values for optional fields.
        The caller is responsible for populating the type-specific data.

        Args:
            journal_id: The journal ID
            journal_type: The type to add
            transaction: Database transaction

        Returns:
            List of all types that were added (including dependencies)

        Raises:
            JournalNotFoundError: If journal doesn't exist
            JournalValidationError: If type addition fails

        Example:
            # In Iteration 4 (base types only):
            types_added = await service.add_type_to_journal(
                journal_id=1,
                journal_type=JournalType.EVENT,
                transaction=conn
            )
            # Returns: [JournalType.EVENT]

            # In Iteration 4.5 (with fitness types):
            types_added = await service.add_type_to_journal(
                journal_id=1,
                journal_type=JournalType.CANYONING,
                transaction=conn
            )
            # Returns: [JournalType.CANYONING, JournalType.BUSHWALKING,
            #           JournalType.ABSEILING_TRIP, JournalType.OUTDOOR_ACTIVITY,
            #           JournalType.FITNESS]
        """
        # Validate journal exists
        journal = await self.journal_repo.find_by_id(journal_id)
        if journal is None:
            raise JournalNotFoundError(journal_id)

        # Get all types to add (including dependencies)
        types_to_add = self._resolve_type_dependencies(journal_type)

        # Add each type and publish events
        # Note: Type-specific data creation is handled by the caller
        # This service only tracks which types are added
        for jtype in types_to_add:
            event = JournalTypeAdded(journal_id, jtype.value, transaction=transaction)
            await self.event_publisher.publish(event)

            logger.info(
                "Journal type added",
                journal_id=journal_id,
                journal_type=jtype.value,
            )

        return types_to_add

    async def remove_type_from_journal(
        self,
        journal_id: int,
        journal_type: JournalType,
        transaction: AsyncConnection,
    ) -> None:
        """
        Remove a type from a journal.

        Note: This method does NOT validate that dependent types are removed first.
        The caller is responsible for ensuring type dependencies are respected.
        Type-specific data deletion is handled by database CASCADE constraints.

        Args:
            journal_id: The journal ID
            journal_type: The type to remove
            transaction: Database transaction

        Raises:
            JournalNotFoundError: If journal doesn't exist
        """
        # Validate journal exists
        journal = await self.journal_repo.find_by_id(journal_id)
        if journal is None:
            raise JournalNotFoundError(journal_id)

        # Publish type removed event
        # Note: Type-specific data deletion is handled by database CASCADE
        event = JournalTypeRemoved(
            journal_id, journal_type.value, transaction=transaction
        )
        await self.event_publisher.publish(event)

        logger.info(
            "Journal type removed",
            journal_id=journal_id,
            journal_type=journal_type.value,
        )

    def _resolve_type_dependencies(
        self, journal_type: JournalType
    ) -> list[JournalType]:
        """
        Resolve type dependencies to get all types that need to be added.

        Uses the JournalType.get_dependencies() method to get direct dependencies,
        then recursively resolves transitive dependencies.

        Args:
            journal_type: The type to resolve dependencies for

        Returns:
            List of all types to add, in order (dependencies first, then the type itself)

        Example:
            # In Iteration 4 (base types):
            _resolve_type_dependencies(JournalType.EVENT)
            # Returns: [JournalType.EVENT]

            # In Iteration 4.5 (with fitness types):
            _resolve_type_dependencies(JournalType.CANYONING)
            # Returns: [JournalType.FITNESS, JournalType.OUTDOOR_ACTIVITY,
            #           JournalType.ABSEILING_TRIP, JournalType.BUSHWALKING,
            #           JournalType.CANYONING]
        """
        resolved: list[JournalType] = []
        seen: set[JournalType] = set()

        def _resolve(jtype: JournalType) -> None:
            """Recursively resolve dependencies."""
            if jtype in seen:
                return
            seen.add(jtype)

            # Resolve dependencies first
            dependencies = JournalType.get_dependencies(jtype)
            for dep in dependencies:
                _resolve(dep)

            # Add the type itself
            if jtype not in resolved:
                resolved.append(jtype)

        _resolve(journal_type)
        return resolved
