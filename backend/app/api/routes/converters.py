"""
Converters for transforming route domain entities to API resources.

Handles the conversion between domain models and JSON API resources,
ensuring proper separation between domain and API layers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core_shared.models import Route

from app.api.common.schemas import JsonApiLinks
from app.api.routes.schemas import RouteResource, RouteResponseAttributes
from app.core.journal.models.exceptions import RouteValidationError

if TYPE_CHECKING:
    from app.api.routes.schemas import RouteCreateData, RouteUpdateData


class RouteConverter:
    """Converter for Route domain entities to API resources."""

    @staticmethod
    def to_resource(route: Route, base_url: str) -> RouteResource:
        """
        Convert Route domain entity to API resource.

        Args:
            route: The route domain entity
            base_url: Base URL for generating resource links

        Returns:
            RouteResource following JSON API specification

        Raises:
            ValueError: If route has no ID (must be persisted first)
        """
        if route.id is None:
            raise ValueError(
                "Cannot serialize Route without ID - Route must be persisted first"
            )
        if route.created_at is None or route.updated_at is None:
            raise ValueError(
                "Cannot serialize Route without timestamps - Route must be persisted first"
            )

        route_id = str(route.id)
        links = JsonApiLinks(self=f"{base_url}/api/routes/{route_id}")

        return RouteResource(
            type="routes",
            id=route_id,
            attributes=RouteResponseAttributes(
                name=route.name,
                description=route.description,
                gpx_data=route.gpx_data,
                created_at=route.created_at,
                updated_at=route.updated_at,
            ),
            links=links,
        )


class RouteRequestConverter:
    """Converter for API requests to Route domain entities."""

    @staticmethod
    def from_create_request(data: RouteCreateData, user_id: str) -> Route:
        """
        Convert API create request to Route domain entity.

        Args:
            data: The API request data
            user_id: The user ID from the authenticated session

        Returns:
            Route domain entity ready for creation

        Raises:
            RouteValidationError: If route validation fails
        """
        try:
            return Route(
                user_id=user_id,
                name=data.attributes.name,
                description=data.attributes.description,
                gpx_data=data.attributes.gpx_data,
            )
        except ValueError as e:
            # Convert ValueError from Route entity to RouteValidationError
            # Extract field name from error message if possible
            error_msg = str(e)
            if "GPX" in error_msg or "gpx" in error_msg:
                field = "gpx_data"
            elif "name" in error_msg.lower():
                field = "name"
            elif "user" in error_msg.lower():
                field = "user_id"
            else:
                field = "route"
            raise RouteValidationError(field, error_msg) from e

    @staticmethod
    def from_update_request(
        data: RouteUpdateData, existing_route: Route
    ) -> tuple[Route, dict[str, tuple[str | None, str | None]]]:
        """
        Convert API update request to Route domain entity with changed fields.

        Args:
            data: The API request data
            existing_route: The existing route from the database

        Returns:
            Tuple of (updated Route entity, changed fields dict)
            Changed fields format: {field_name: (old_value, new_value)}

        Raises:
            RouteValidationError: If route validation fails
        """
        # Calculate changed fields for event tracking
        changed_fields: dict[str, tuple[str | None, str | None]] = {}

        if data.attributes.name != existing_route.name:
            changed_fields["name"] = (existing_route.name, data.attributes.name)

        if data.attributes.description != existing_route.description:
            changed_fields["description"] = (
                existing_route.description,
                data.attributes.description,
            )

        if data.attributes.gpx_data != existing_route.gpx_data:
            # For GPX data, we don't include the full content in events (too large)
            # Just track that it changed
            changed_fields["gpx_data"] = (
                "present" if existing_route.gpx_data else None,
                "present" if data.attributes.gpx_data else None,
            )

        # Create updated route entity
        # Note: We use existing_route.id to prevent ID mismatch attacks
        # The path parameter is the authoritative source of the route ID
        try:
            updated_route = Route(
                id=existing_route.id,
                user_id=existing_route.user_id,
                name=data.attributes.name,
                description=data.attributes.description,
                gpx_data=data.attributes.gpx_data,
                created_at=existing_route.created_at,
                updated_at=existing_route.updated_at,
            )
        except ValueError as e:
            # Convert ValueError from Route entity to RouteValidationError
            error_msg = str(e)
            if "GPX" in error_msg or "gpx" in error_msg:
                field = "gpx_data"
            elif "name" in error_msg.lower():
                field = "name"
            elif "user" in error_msg.lower():
                field = "user_id"
            else:
                field = "route"
            raise RouteValidationError(field, error_msg) from e

        return updated_route, changed_fields
