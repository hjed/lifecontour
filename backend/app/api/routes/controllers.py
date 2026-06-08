"""
Route API controllers.

Handles route-related HTTP endpoints following JSON API specification.
Controllers act as adapters between HTTP and domain services.
"""

from typing import Annotated
from uuid import UUID

from core_shared.models.history import Provenance
from core_shared.models.journals import JournalNotFoundError, RouteNotFoundError
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
from app.core.journal.services.journal_service import JournalService
from app.core.journal.services.route_service import RouteService
from app.infrastructure.auth.models import SessionUser

router = APIRouter(
    prefix="/journals/{journal_id}/routes",
    tags=["routes"],
)


@router.get("")
@inject
async def list_routes(
    journal_id: int,
    request: Request,
    route_service: FromDishka[RouteService],
    journal_service: FromDishka[JournalService],
    user: FromDishka[SessionUser],  # Require authentication
    page: Annotated[int, Query(description="Page number", ge=1)] = 1,
    limit: Annotated[int, Query(description="Items per page", ge=1, le=100)] = 20,
    name: Annotated[
        str | None,
        Query(description="Optional case-insensitive partial route name filter"),
    ] = None,
) -> RouteListResponse:
    """
    List routes with pagination.

    Returns a paginated list of routes for the authenticated user
    following JSON API specification.
    """
    pagination = PaginationParams(page=page, limit=limit)
    base_url = get_request_base_url(request)

    # Verify journal ownership first
    journal = await journal_service.get_journal(journal_id)
    if not journal or journal.user_id != user.id:
        raise JournalNotFoundError(journal_id)

    # Get routes for the authenticated user, pushing filter and pagination to the database
    routes, total_count = await route_service.get_routes_by_journal_paginated(
        journal_id=journal_id,
        name_filter=name,
        limit=pagination.limit,
        offset=pagination.offset,
    )

    # Convert to resources
    route_resources = [RouteConverter.to_resource(route, base_url) for route in routes]

    # Create pagination metadata and links
    meta = create_pagination_meta(total_count, page, limit)
    base_link_url = f"{base_url}/api/journals/{journal_id}/routes"

    additional_params: dict[str, str | list[str]] = {}
    if name:
        additional_params["name"] = name

    links = create_pagination_links(
        base_link_url,
        page,
        limit,
        total_count,
        additional_params=additional_params if additional_params else None,
    )

    return RouteListResponse(
        data=route_resources,
        meta=meta,
        links=links,
    )


@router.get("/{route_id}")
@inject
async def get_route(
    journal_id: int,
    route_id: str,
    request: Request,
    route_service: FromDishka[RouteService],
    journal_service: FromDishka[JournalService],
    user: FromDishka[SessionUser],  # Require authentication
) -> RouteResponse:
    """
    Get a single route by ID.

    Returns a single route resource following JSON API specification.
    """
    base_url = get_request_base_url(request)

    # Verify journal ownership first
    journal = await journal_service.get_journal(journal_id)
    if not journal or journal.user_id != user.id:
        raise JournalNotFoundError(journal_id)

    # Parse UUID
    try:
        route_uuid = UUID(route_id)
    except ValueError as e:
        raise RouteNotFoundError(route_id) from e

    # Get the route
    route = await route_service.get_route(route_uuid)

    # Verify route belongs to user
    if route.journal_id != journal_id:
        raise RouteNotFoundError(route_id)

    # Convert to resource
    route_resource = RouteConverter.to_resource(route, base_url)

    return RouteResponse(data=route_resource)


@router.post("", status_code=status.HTTP_201_CREATED)
@inject
async def create_route(
    journal_id: int,
    request: Request,
    route_request: RouteCreateRequest,
    route_service: FromDishka[RouteService],
    journal_service: FromDishka[JournalService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> RouteResponse:
    """
    Create a new route.

    Creates a new route for the authenticated user and returns the created resource.
    """
    base_url = get_request_base_url(request)

    # Verify journal ownership first
    journal = await journal_service.get_journal(journal_id)
    if not journal or journal.user_id != user.id:
        raise JournalNotFoundError(journal_id)

    # Convert request to domain entity
    route = RouteRequestConverter.from_create_request(
        route_request.data, journal_id=journal_id
    )

    # Create the route
    created_route = await route_service.create_route(
        route, connection, changed_by="ui", source=Provenance.UI
    )

    # Convert to resource
    route_resource = RouteConverter.to_resource(created_route, base_url)

    return RouteResponse(data=route_resource)


@router.put("/{route_id}")
@inject
async def update_route(
    journal_id: int,
    route_id: str,
    request: Request,
    route_request: RouteUpdateRequest,
    route_service: FromDishka[RouteService],
    journal_service: FromDishka[JournalService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> RouteResponse:
    """
    Update an existing route.

    Updates the route with the provided data and returns the updated resource.
    """
    base_url = get_request_base_url(request)

    # Verify journal ownership first
    journal = await journal_service.get_journal(journal_id)
    if not journal or journal.user_id != user.id:
        raise JournalNotFoundError(journal_id)

    # Parse UUID
    try:
        route_uuid = UUID(route_id)
    except ValueError as e:
        raise RouteNotFoundError(route_id) from e

    # Verify route exists and belongs to user
    existing_route = await route_service.get_route(route_uuid)
    if existing_route.journal_id != journal_id:
        raise RouteNotFoundError(route_id)

    # Convert request to domain entity with changed fields
    updated_route, changed_fields = RouteRequestConverter.from_update_request(
        route_request.data, existing_route
    )

    # Update the route
    saved_route = await route_service.update_route(
        updated_route,
        changed_fields,
        connection,
        changed_by="ui",
        source=Provenance.UI,
    )

    # Convert to resource
    route_resource = RouteConverter.to_resource(saved_route, base_url)

    return RouteResponse(data=route_resource)


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_route(
    journal_id: int,
    route_id: str,
    route_service: FromDishka[RouteService],
    journal_service: FromDishka[JournalService],
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
    # Verify journal ownership first
    journal = await journal_service.get_journal(journal_id)
    if not journal or journal.user_id != user.id:
        raise JournalNotFoundError(journal_id)
    # Parse UUID
    try:
        route_uuid = UUID(route_id)
    except ValueError as e:
        raise RouteNotFoundError(route_id) from e

    # Verify route exists and belongs to user
    existing_route = await route_service.get_route(route_uuid)
    if existing_route.journal_id != journal_id:
        raise RouteNotFoundError(route_id)

    # Delete the route (will check for usage)
    await route_service.delete_route(
        route_uuid, connection, changed_by="ui", source=Provenance.UI
    )
