"""
Route API controllers.

Handles route-related HTTP endpoints following JSON API specification.
Controllers act as adapters between HTTP and domain services.
"""

from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.schemas import (
    PaginationParams,
    create_pagination_links,
    create_pagination_meta,
    get_request_base_url,
)
from app.api.routes.converters import RouteConverter, RouteRequestConverter
from app.api.routes.schemas import (
    RouteCreateRequest,
    RouteListResponse,
    RouteResponse,
    RouteUpdateRequest,
)
from app.core.journal.models.exceptions import RouteNotFoundError
from app.core.journal.services.route_service import RouteService
from app.infrastructure.auth.models import SessionUser

router = APIRouter(
    prefix="/routes",
    tags=["routes"],
)


@router.get("")
@inject
async def list_routes(
    request: Request,
    route_service: FromDishka[RouteService],
    user: FromDishka[SessionUser],  # Require authentication
    page: int = Query(default=1, description="Page number", ge=1),
    limit: int = Query(default=20, description="Items per page", ge=1, le=100),
) -> RouteListResponse:
    """
    List routes with pagination.

    Returns a paginated list of routes for the authenticated user
    following JSON API specification.
    """
    pagination = PaginationParams(page=page, limit=limit)
    base_url = get_request_base_url(request)

    # Get routes for the authenticated user
    routes = await route_service.get_routes_for_user(
        user_id=user.id,
        limit=pagination.limit,
        offset=pagination.offset,
    )

    # Get total count for pagination
    total_count = await route_service.get_route_count(user_id=user.id)

    # Convert to resources
    route_resources = [RouteConverter.to_resource(route, base_url) for route in routes]

    # Create pagination metadata and links
    meta = create_pagination_meta(total_count, page, limit)
    links = create_pagination_links(f"{base_url}/api/routes", page, limit, total_count)

    return RouteListResponse(
        data=route_resources,
        meta=meta,
        links=links,
    )


@router.get("/{route_id}")
@inject
async def get_route(
    route_id: str,
    request: Request,
    route_service: FromDishka[RouteService],
    user: FromDishka[SessionUser],  # Require authentication
) -> RouteResponse:
    """
    Get a single route by ID.

    Returns a single route resource following JSON API specification.
    """
    base_url = get_request_base_url(request)

    # Parse UUID
    try:
        route_uuid = UUID(route_id)
    except ValueError as e:
        raise RouteNotFoundError(route_id) from e

    # Get the route
    route = await route_service.get_route(route_uuid)

    # Verify route belongs to user
    if route.user_id != user.id:
        raise RouteNotFoundError(route_id)

    # Convert to resource
    route_resource = RouteConverter.to_resource(route, base_url)

    return RouteResponse(data=route_resource)


@router.post("", status_code=status.HTTP_201_CREATED)
@inject
async def create_route(
    request: Request,
    route_request: RouteCreateRequest,
    route_service: FromDishka[RouteService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> RouteResponse:
    """
    Create a new route.

    Creates a new route for the authenticated user and returns the created resource.
    """
    base_url = get_request_base_url(request)

    # Convert request to domain entity
    route = RouteRequestConverter.from_create_request(
        route_request.data, user_id=user.id
    )

    # Create the route
    created_route = await route_service.create_route(route, connection)

    # Convert to resource
    route_resource = RouteConverter.to_resource(created_route, base_url)

    return RouteResponse(data=route_resource)


@router.put("/{route_id}")
@inject
async def update_route(
    route_id: str,
    request: Request,
    route_request: RouteUpdateRequest,
    route_service: FromDishka[RouteService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> RouteResponse:
    """
    Update an existing route.

    Updates the route with the provided data and returns the updated resource.
    """
    base_url = get_request_base_url(request)

    # Parse UUID
    try:
        route_uuid = UUID(route_id)
    except ValueError as e:
        raise RouteNotFoundError(route_id) from e

    # Verify route exists and belongs to user
    existing_route = await route_service.get_route(route_uuid)
    if existing_route.user_id != user.id:
        raise RouteNotFoundError(route_id)

    # Convert request to domain entity with changed fields
    updated_route, changed_fields = RouteRequestConverter.from_update_request(
        route_request.data, existing_route
    )

    # Update the route
    saved_route = await route_service.update_route(
        updated_route, changed_fields, connection
    )

    # Convert to resource
    route_resource = RouteConverter.to_resource(saved_route, base_url)

    return RouteResponse(data=route_resource)


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_route(
    route_id: str,
    route_service: FromDishka[RouteService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """
    Delete a route.

    Deletes the route if it's not in use by any journals.
    Returns 204 No Content on success.

    Raises:
        RouteNotFoundError: If route doesn't exist
        RouteInUseError: If route is referenced by journals
    """
    # Parse UUID
    try:
        route_uuid = UUID(route_id)
    except ValueError as e:
        raise RouteNotFoundError(route_id) from e

    # Verify route exists and belongs to user
    existing_route = await route_service.get_route(route_uuid)
    if existing_route.user_id != user.id:
        raise RouteNotFoundError(route_id)

    # Delete the route (will check for usage)
    await route_service.delete_route(route_uuid, connection)
