"""Service for managing routes."""

from uuid import UUID

import structlog
from core_shared.models import Route
from core_shared.models.history import Provenance
from core_shared.models.journals import (
    RouteNotFoundError,
    RouteValidationError,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.events import RouteCreated, RouteDeleted, RouteUpdated
from app.core.journal.models.repositories import RouteRepository
from app.core.journal.utils.route_edits import RouteEdit, apply_route_update
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import transactional

logger = structlog.get_logger()


class RouteService:
    """
    Service for managing routes with validation and event publishing.

    Handles:
    - Route CRUD operations with validation
    - Usage checking before deletion
    - Domain event publishing via outbox pattern
    """

    def __init__(
        self,
        route_repo: RouteRepository,
        event_publisher: OutboxEventPublisher,
    ):
        """
        Initialize the route service.

        Args:
            route_repo: Repository for route persistence
            event_publisher: Publisher for domain events (outbox pattern)
        """
        self.route_repo = route_repo
        self.event_publisher = event_publisher

    async def get_routes_by_journal_paginated(
        self,
        journal_id: int,
        name_filter: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Route], int]:
        """
        Get routes for a journal with filtering and pagination.

        Args:
            journal_id: ID of the journal
            name_filter: Optional string to filter by name
            limit: Maximum number of routes to return
            offset: Offset for pagination

        Returns:
            Tuple of (list of routes, total count matching filters)
        """
        return await self.route_repo.find_by_journal_id_paginated(
            journal_id=journal_id,
            name_filter=name_filter,
            limit=limit,
            offset=offset,
        )

    @transactional
    async def create_route(
        self,
        route: Route,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> Route:
        """
        Create a new route with validation.

        Publishes RouteCreated event via outbox pattern.

        Args:
            route: The route to create
            transaction: Database transaction
            changed_by: Who/what made the change (for history provenance)
            source: Provenance of the change (for history provenance)

        Returns:
            The created route with ID and timestamps

        Raises:
            RouteValidationError: If validation fails
        """
        # Validate that this is a new route (no ID set)
        if route.id is not None:
            raise RouteValidationError(
                "id", "Cannot create route with existing ID. Use update_route instead."
            )

        # Save the route
        try:
            saved_route = await self.route_repo.save(route)
        except IntegrityError as e:
            raise RouteValidationError(
                "database", f"Database constraint violation: {e}"
            ) from e

        # Ensure route has ID after save
        if saved_route.id is None:
            raise RouteValidationError(
                "id", "Route ID is required after save operation"
            )

        # Publish creation event
        event = RouteCreated(
            str(saved_route.id),
            saved_route.journal_id,
            saved_route.name,
            source=source,
            changed_by=changed_by,
            transaction=transaction,
        )
        await self.event_publisher.publish(event)

        logger.info(
            "Route created",
            route_id=str(saved_route.id),
            journal_id=saved_route.journal_id,
            name=saved_route.name,
        )

        return saved_route

    @transactional
    async def update_route(
        self,
        route_id: UUID,
        edit: RouteEdit,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> Route:
        """
        Apply an edit to a route and record what changed.

        The route is read with a row lock held until the unit of work ends, and
        the edit is merged into, and its changed fields computed from, that
        locked row. Concurrent edits to one route therefore run one after the
        other: neither can revert a field the other changed, and each records
        exactly what it changed.

        Publishes RouteUpdated event via outbox pattern.

        Args:
            route_id: The ID of the route to edit
            edit: The fields to change; unset fields keep their current value
            transaction: Database transaction
            changed_by: Who/what made the change (for history provenance)
            source: Provenance of the change (for history provenance)

        Returns:
            The updated route

        Raises:
            RouteValidationError: If the edited route fails validation
            RouteNotFoundError: If route doesn't exist
        """
        existing_route = await self.route_repo.find_by_id_for_update(route_id)
        if existing_route is None:
            raise RouteNotFoundError(str(route_id))

        updated_route, changed_fields = apply_route_update(existing_route, edit)

        # Save the updated route
        try:
            saved_route = await self.route_repo.save(updated_route)
        except IntegrityError as e:
            raise RouteValidationError(
                "database", f"Database constraint violation: {e}"
            ) from e

        # Ensure route ID is set (should always be true for updates)
        assert saved_route.id is not None, "Route ID must be set after update"

        # Publish update event
        event = RouteUpdated(
            str(saved_route.id),
            saved_route.journal_id,
            changed_fields,
            source=source,
            changed_by=changed_by,
            transaction=transaction,
        )
        await self.event_publisher.publish(event)

        logger.info(
            "Route updated",
            route_id=str(saved_route.id),
            changed_fields=list(changed_fields.keys()),
        )

        return saved_route

    @transactional
    async def delete_route(
        self,
        route_id: UUID,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> None:
        """
        Delete a route after checking it's not in use.

        Publishes RouteDeleted event via outbox pattern.

        Args:
            route_id: The ID of the route to delete
            transaction: Database transaction
            changed_by: Who/what made the change (for history provenance)
            source: Provenance of the change (for history provenance)

        Raises:
            RouteNotFoundError: If route doesn't exist
            RouteInUseError: If route is in use by journals
        """
        # Validate route exists (loaded before deletion so journal_id is available)
        route = await self.route_repo.find_by_id(route_id)
        if route is None:
            raise RouteNotFoundError(str(route_id))

        journal_id = route.journal_id

        # Delete the route
        await self.route_repo.delete(route_id)

        # Publish deletion event
        event = RouteDeleted(
            str(route_id),
            journal_id,
            source=source,
            changed_by=changed_by,
            transaction=transaction,
        )
        await self.event_publisher.publish(event)

        logger.info("Route deleted", route_id=str(route_id))

    async def get_route(self, route_id: UUID) -> Route:
        """
        Get a route by ID.

        Args:
            route_id: The ID of the route to retrieve

        Returns:
            The route if found

        Raises:
            RouteNotFoundError: If route doesn't exist
        """
        route = await self.route_repo.find_by_id(route_id)
        if route is None:
            raise RouteNotFoundError(str(route_id))
        return route

    async def get_routes_by_journal(
        self,
        journal_id: int,
    ) -> list[Route]:
        """
        Get all routes for a journal.

        Args:
            journal_id: The journal ID to get routes for

        Returns:
            List of routes
        """
        return await self.route_repo.find_by_journal_id(journal_id)
