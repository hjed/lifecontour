"""FastMCP-compatible dependency helpers for mounted MCP tools."""

from collections.abc import Callable
from typing import Any, TypeVar, cast

from dishka import AsyncContainer
from fastmcp.dependencies import Depends
from fastmcp.server.dependencies import get_http_request
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.repositories import TagRepository
from app.core.contacts.services import ContactService
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.search.search_service import SearchService

T = TypeVar("T")


def _get_request_container() -> AsyncContainer:
    """Resolve the Dishka container for the current MCP HTTP request."""
    request = get_http_request()

    container = getattr(request.state, "dishka_container", None)
    if container is None:
        container = getattr(request.app.state, "dishka_container", None)
    if container is None:
        state = request.scope.get("state")
        if isinstance(state, dict):
            container = state.get("dishka_container")

    if container is None:
        raise RuntimeError("Dishka container not found in MCP request context")

    return cast(AsyncContainer, container)


async def _resolve_dependency(dependency_type: object) -> Any:
    """Resolve a dependency from the current request-scoped Dishka container."""
    container = _get_request_container()
    return await container.get(dependency_type)


def mcp_depends(
    dependency: Any,
) -> Any:
    """Wrap FastMCP Depends behind a single project-local typing boundary.

    FastMCP supports async dependency functions at runtime, but the current
    third-party typing does not model our strict mypy usage reliably when these
    defaults are applied to tool parameters. Keeping the cast here avoids
    scattering type-ignores/casts across every MCP tool signature.
    """
    return Depends(cast(Callable[..., object], dependency))


def get_session_user() -> SessionUser:
    """Get the authenticated session user for the current MCP request."""
    request = get_http_request()
    if not hasattr(request.state, "user"):
        raise RuntimeError("No authenticated user found in MCP request context")

    return cast(SessionUser, request.state.user)


def get_current_user_id() -> str:
    """Get the current authenticated user id for the MCP request."""
    return get_session_user().id


async def get_async_connection() -> AsyncConnection:
    """Resolve the active request-scoped database connection."""
    return cast(AsyncConnection, await _resolve_dependency(AsyncConnection))


async def get_contact_service() -> ContactService:
    """Resolve the contact service for the current MCP request."""
    return cast(ContactService, await _resolve_dependency(ContactService))


async def get_search_service() -> SearchService:
    """Resolve the search service for the current MCP request."""
    return cast(SearchService, await _resolve_dependency(SearchService))


async def get_tag_repository() -> TagRepository:
    """Resolve the contact tag repository for the current MCP request."""
    return cast(TagRepository, await _resolve_dependency(TagRepository))


async def get_outbox_event_publisher() -> OutboxEventPublisher:
    """Resolve the outbox event publisher for the current MCP request."""
    return cast(OutboxEventPublisher, await _resolve_dependency(OutboxEventPublisher))
