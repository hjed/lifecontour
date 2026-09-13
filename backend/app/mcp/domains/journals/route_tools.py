"""MCP tools for journal routes — the GPX tracks attached to a journal entry.

The ``/journals/{journal_id}/routes`` REST endpoints, for AI clients. Every tool
checks the journal belongs to the caller first, so a journal owned by someone
else reads as not found. Writes go through ``RouteService``, which owns the
transaction and records the change in the journal's history as made by MCP.
"""

import json
from typing import Annotated
from uuid import UUID

from core_shared.models import Route
from core_shared.models.history import Provenance
from core_shared.models.journals import RouteNotFoundError
from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.route_service import RouteService
from app.core.journal.utils.route_edits import UNCHANGED, RouteEdit, build_new_route
from app.mcp.domains.journals.converters import RouteMCPConverter
from app.mcp.shared.annotations import (
    ADDITIVE_WRITE,
    DESTRUCTIVE_WRITE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_route_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder

_GPX_DATA_DESCRIPTION = (
    "The complete GPX XML document as a single string. It must parse as XML "
    "with a <gpx> root element. The server accepts documents of several "
    "megabytes (e.g. a 3.6 MB track); a deployment's reverse proxy may impose "
    "its own request-size limit."
)

_ROUTE_ID_DESCRIPTION = (
    "Route UUID, as returned by create_journal_route or list_journal_routes"
)


async def _owns_journal(
    db_connection: AsyncConnection, journal_id: int, user_id: str
) -> bool:
    journal = await SqlJournalRepository(db_connection).find_by_id_for_user(
        journal_id, user_id
    )
    return journal is not None


async def _load_owned_route(
    db_connection: AsyncConnection,
    route_service: RouteService,
    user_id: str,
    journal_id: int,
    route_id: str,
) -> Route | str:
    """The route, or the error response to return in its place.

    A journal the caller does not own, and a route that is not on that journal,
    both read as not found rather than confirming that they exist.
    """
    if not await _owns_journal(db_connection, journal_id, user_id):
        return MCPResponseBuilder.not_found_error_response("Journal", journal_id)
    try:
        route_uuid = UUID(route_id)
    except ValueError:
        return MCPResponseBuilder.validation_error_response(
            "route_id", "Must be a valid UUID"
        )
    try:
        route = await route_service.get_route(route_uuid)
    except RouteNotFoundError:
        return MCPResponseBuilder.not_found_error_response("Route", route_id)
    if route.journal_id != journal_id:
        return MCPResponseBuilder.not_found_error_response("Route", route_id)
    return route


@tool(annotations=ADDITIVE_WRITE)
@mcp_unified_error_handler("create_journal_route", "journal")
async def create_journal_route(
    journal_id: Annotated[
        int, Field(description="ID of the journal entry to attach the route to")
    ],
    name: Annotated[str, Field(description="Route name (max 200 characters)")],
    gpx_data: Annotated[
        str | None, Field(default=None, description=_GPX_DATA_DESCRIPTION)
    ] = None,
    description: Annotated[
        str | None, Field(default=None, description="Optional route description")
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    route_service: RouteService = mcp_depends(get_route_service),
) -> str:
    """
    Attach a route (GPX track) to a journal entry the user owns.

    The route is validated before anything is written: GPX that is not XML, or
    has no <gpx> root, is refused with a validation error on ``gpx_data``, as is
    a blank or over-long ``name``. The response summarises the saved route (id,
    name, whether GPX is stored and its size) without echoing the GPX back; use
    ``list_journal_routes`` to find a journal's routes later.
    """
    if not await _owns_journal(db_connection, journal_id, user_id):
        return MCPResponseBuilder.not_found_error_response("Journal", journal_id)

    route = build_new_route(
        journal_id=journal_id, name=name, description=description, gpx_data=gpx_data
    )
    saved_route = await route_service.create_route(
        route, db_connection, changed_by="mcp", source=Provenance.MCP
    )
    return MCPResponseBuilder.success_response(
        RouteMCPConverter.to_mcp_response(saved_route)
    )


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("list_journal_routes", "journal")
async def list_journal_routes(
    journal_id: Annotated[
        int, Field(description="ID of the journal entry whose routes to list")
    ],
    name: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional case-insensitive partial route name filter",
        ),
    ] = None,
    limit: Annotated[
        int, Field(default=20, ge=1, le=100, description="Routes per page (1-100)")
    ] = 20,
    offset: Annotated[
        int, Field(default=0, ge=0, description="Routes to skip before this page")
    ] = 0,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    route_service: RouteService = mcp_depends(get_route_service),
) -> str:
    """
    List the routes (GPX tracks) attached to a journal entry, oldest first.

    Returns each route's id, name, description, and whether GPX is stored and
    its size — never the GPX itself — so a caller can find the route to update
    or delete. ``total_count`` counts every route matching ``name``.
    """
    if not await _owns_journal(db_connection, journal_id, user_id):
        return MCPResponseBuilder.not_found_error_response("Journal", journal_id)

    routes, total_count = await route_service.get_routes_by_journal_paginated(
        journal_id=journal_id, name_filter=name, limit=limit, offset=offset
    )
    return MCPResponseBuilder.success_response(
        RouteMCPConverter.to_mcp_list_response(
            routes, total_count=total_count, limit=limit, offset=offset
        )
    )


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("update_journal_route", "journal")
async def update_journal_route(
    journal_id: Annotated[
        int, Field(description="ID of the journal entry the route is attached to")
    ],
    route_id: Annotated[str, Field(description=_ROUTE_ID_DESCRIPTION)],
    name: Annotated[
        str | None,
        Field(default=None, description="New route name (max 200 characters)"),
    ] = None,
    description: Annotated[
        str | None,
        Field(
            default=None,
            description="New description (pass an empty string to clear it)",
        ),
    ] = None,
    gpx_data: Annotated[
        str | None,
        Field(
            default=None,
            description=_GPX_DATA_DESCRIPTION
            + " Pass an empty string to remove the stored track.",
        ),
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    route_service: RouteService = mcp_depends(get_route_service),
) -> str:
    """
    Change a route's name, description or GPX track on a journal entry the user owns.

    Only the arguments you pass change; omitted ones keep their current value,
    even if another update to the same route lands at the same time. The update
    is validated before anything is written, with the same ``gpx_data`` and
    ``name`` refusals as ``create_journal_route``. A route that is not on
    ``journal_id`` is reported as not found. The change is recorded in the
    journal's history (a GPX change as present/absent, not its content).
    """
    route = await _load_owned_route(
        db_connection, route_service, user_id, journal_id, route_id
    )
    if isinstance(route, str):
        return route
    assert route.id is not None, "A route loaded from the database has an id"

    edit = RouteEdit(
        name=UNCHANGED if name is None else name,
        description=UNCHANGED if description is None else description or None,
        gpx_data=UNCHANGED if gpx_data is None else gpx_data,
    )
    saved_route = await route_service.update_route(
        route.id, edit, db_connection, changed_by="mcp", source=Provenance.MCP
    )
    return MCPResponseBuilder.success_response(
        RouteMCPConverter.to_mcp_response(saved_route)
    )


@tool(annotations=DESTRUCTIVE_WRITE)
@mcp_unified_error_handler("delete_journal_route", "journal")
async def delete_journal_route(
    journal_id: Annotated[
        int, Field(description="ID of the journal entry the route is attached to")
    ],
    route_id: Annotated[str, Field(description=_ROUTE_ID_DESCRIPTION)],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    route_service: RouteService = mcp_depends(get_route_service),
) -> str:
    """
    Permanently delete a route (and its GPX track) from a journal entry the user owns.

    The journal entry itself is not changed. A route that is not on
    ``journal_id`` is reported as not found. The deletion is recorded in the
    journal's history.
    """
    route = await _load_owned_route(
        db_connection, route_service, user_id, journal_id, route_id
    )
    if isinstance(route, str):
        return route
    assert route.id is not None, "A route loaded from the database has an id"

    await route_service.delete_route(
        route.id, db_connection, changed_by="mcp", source=Provenance.MCP
    )
    return json.dumps(
        {"deleted": True, "route_id": str(route.id), "journal_id": journal_id},
        indent=2,
    )


def register_journal_route_tools(mcp: FastMCP[None]) -> None:
    """Register journal route MCP tools with the FastMCP server."""
    mcp.add_tool(create_journal_route)
    mcp.add_tool(list_journal_routes)
    mcp.add_tool(update_journal_route)
    mcp.add_tool(delete_journal_route)
