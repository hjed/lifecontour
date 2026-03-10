"""Service for managing routes."""

from typing import Any
from uuid import UUID

import structlog
from core_shared.models import Route
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.events import RouteCreated, RouteDeleted, RouteUpdated
from app.core.journal.models.exceptions import (
    RouteInUseError,
    RouteNotFoundError,
    RouteValidationError,
)
from app.core.journal.models.repositories import RouteRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher

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

    async def create_route(self, route: Route, transaction: AsyncConnection) -> Route:
        """
        Create a new route with validation.

        Publishes RouteCreated event via outbox pattern.

        Args:
            route: The route to create
            transaction: Database transaction

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
            saved_route.user_id,
            saved_route.name,
            transaction=transaction,
        )
        await self.event_publisher.publish(event)

        logger.info(
            "Route created",
            route_id=str(saved_route.id),
            user_id=saved_route.user_id,
            name=saved_route.name,
        )

        return saved_route

    async def update_route(
        self,
        route: Route,
        changed_fields: dict[str, Any],
        transaction: AsyncConnection,
    ) -> Route:
        """
        Update an existing route.

        Publishes RouteUpdated event via outbox pattern.

        Args:
            route: The route to update (must have id set)
            changed_fields: Dictionary of changed fields for event tracking
            transaction: Database transaction

        Returns:
            The updated route

        Raises:
            RouteValidationError: If validation fails or route has no ID
            RouteNotFoundError: If route doesn't exist
        """
        if route.id is None:
            raise RouteValidationError("id", "Route ID is required for update")

        # Validate route exists
        existing_route = await self.route_repo.find_by_id(route.id)
        if existing_route is None:
            raise RouteNotFoundError(str(route.id))

        # Save the updated route
        try:
            saved_route = await self.route_repo.save(route)
        except IntegrityError as e:
            raise RouteValidationError(
                "database", f"Database constraint violation: {e}"
            ) from e

        # Ensure route ID is set (should always be true for updates)
        assert saved_route.id is not None, "Route ID must be set after update"

        # Publish update event
        event = RouteUpdated(
            str(saved_route.id),
            changed_fields,
            transaction=transaction,
        )
        await self.event_publisher.publish(event)

        logger.info(
            "Route updated",
            route_id=str(saved_route.id),
            changed_fields=list(changed_fields.keys()),
        )

        return saved_route

    async def delete_route(self, route_id: UUID, transaction: AsyncConnection) -> None:
        """
        Delete a route after checking it's not in use.

        Publishes RouteDeleted event via outbox pattern.

        Args:
            route_id: The ID of the route to delete
            transaction: Database transaction

        Raises:
            RouteNotFoundError: If route doesn't exist
            RouteInUseError: If route is in use by journals
        """
        # Validate route exists
        route = await self.route_repo.find_by_id(route_id)
        if route is None:
            raise RouteNotFoundError(str(route_id))

        # Check if route is in use
        is_in_use = await self.route_repo.check_usage_in_journals(route_id)
        if is_in_use:
            raise RouteInUseError(str(route_id))

        # Delete the route
        await self.route_repo.delete(route_id)

        # Publish deletion event
        event = RouteDeleted(str(route_id), transaction=transaction)
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

    async def get_routes_for_user(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        name: str | None = None,
    ) -> list[Route]:
        """
        Get all routes for a user with pagination.

        Args:
            user_id: The user ID to filter by
            limit: Maximum number of routes to return
            offset: Number of routes to skip
            name: Optional case-insensitive partial route name filter

        Returns:
            List of routes
        """
        if name is None:
            return await self.route_repo.get_all(user_id, limit, offset)

        return await self.route_repo.get_all(user_id, limit, offset, name)

    async def get_route_count(self, user_id: str, name: str | None = None) -> int:
        """
        Get count of routes for a user.

        Args:
            user_id: The user ID to count routes for
            name: Optional case-insensitive partial route name filter

        Returns:
            Total count of routes
        """
        if name is None:
            return await self.route_repo.get_count(user_id)

        return await self.route_repo.get_count(user_id, name)
