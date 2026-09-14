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
from app.core.journal.utils.route_edits import RouteEdit, build_new_route

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
    def from_create_request(data: RouteCreateData, journal_id: int) -> Route:
        """
        Convert API create request to Route domain entity.

        Args:
            data: The API request data
            journal_id: The journal the route belongs to

        Returns:
            Route domain entity ready for creation

        Raises:
            RouteValidationError: If route validation fails
        """
        return build_new_route(
            journal_id=journal_id,
            name=data.attributes.name,
            description=data.attributes.description,
            gpx_data=data.attributes.gpx_data,
        )

    @staticmethod
    def to_route_edit(data: RouteUpdateData) -> RouteEdit:
        """
        Convert an API update request to a route edit.

        A PUT replaces every editable field, so all three are set. The route's
        id comes from the URL, never the request body, so a mismatched id in
        the body cannot retarget the update.

        Args:
            data: The API request data

        Returns:
            RouteEdit setting the name, description and GPX data
        """
        return RouteEdit(
            name=data.attributes.name,
            description=data.attributes.description,
            gpx_data=data.attributes.gpx_data,
        )
