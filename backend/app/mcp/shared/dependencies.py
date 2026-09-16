"""FastMCP-compatible dependency helpers for mounted MCP tools."""

import contextvars
from collections.abc import Callable
from typing import Any, TypeVar, cast

import structlog
from dishka import AsyncContainer
from fastmcp.dependencies import Depends
from fastmcp.server.dependencies import get_http_request
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.repositories import TagRepository
from app.core.contacts.services import (
    ContactRelationshipService,
    ContactService,
    TagService,
)
from app.core.contacts.services.contact_merge_service import ContactMergeService
from app.core.contacts.services.upcoming_important_dates_service import (
    UpcomingImportantDatesService,
)
from app.core.history.services.task_history_service import TaskHistoryService
from app.core.journal.models.repositories import ActivityStatsRepository
from app.core.journal.services.activity_template_service import (
    ActivityTemplateService,
)
from app.core.journal.services.calendar_service import CalendarService
from app.core.journal.services.daily_summary_service import DailySummaryService
from app.core.journal.services.gear_item_service import GearItemService
from app.core.journal.services.incomplete_outdoor_activity_service import (
    IncompleteOutdoorActivityService,
)
from app.core.journal.services.journal_contact_service import JournalContactService
from app.core.journal.services.journal_series_service import JournalSeriesService
from app.core.journal.services.journal_tag_service import JournalTagService
from app.core.journal.services.journal_write_service import JournalWriteService
from app.core.journal.services.outdoor_activity_dismissal_service import (
    OutdoorActivityDismissalService,
)
from app.core.journal.services.outdoor_dashboard_service import (
    OutdoorDashboardService,
)
from app.core.journal.services.review_item_service import ReviewItemService
from app.core.journal.services.route_service import RouteService
from app.core.tasks.services.task_read_service import TaskReadService
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.auth.immich_token_service import ImmichTokenService
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.auth.token_user import session_user_from_claims
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.search.search_service import SearchService

T = TypeVar("T")

logger = structlog.get_logger()

# ContextVar for background workers to supply the DI container
mcp_background_container: contextvars.ContextVar[AsyncContainer | None] = (
    contextvars.ContextVar("mcp_background_container", default=None)
)


def _get_request_container() -> AsyncContainer:
    """Resolve the Dishka container for the current MCP HTTP request."""
    bg_container = mcp_background_container.get()
    if bg_container is not None:
        return bg_container

    try:
        request = get_http_request()
    except RuntimeError:
        raise RuntimeError(
            "Dishka container not found in MCP context (neither HTTP nor background)"
        ) from None

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


async def get_session_user() -> SessionUser:
    """Get the authenticated session user for the current MCP request.

    When OAuth auth is enabled, the user identity is extracted from the
    FastMCP access token claims (populated by the OAuth provider).
    When auth is disabled (dev mode), resolves the SessionUser from the
    Dishka container to stay consistent with API endpoint user identity.

    Every provider exposes the identity as flat claims on the verified token:
    the named providers (GitHub, Azure, Discord) verify upstream themselves,
    and the generic-OAuth proxy verifies the upstream ``id_token`` against the
    IdP's JWKS, so its payload — ``sub``, ``email``, ``name`` — arrives the
    same way.
    """
    from fastmcp.server.dependencies import get_access_token

    try:
        token = get_access_token()
    except RuntimeError:
        token = None

    if token is not None:
        # Authenticated via OAuth — extract user identity from token claims
        return session_user_from_claims(
            token.claims, token.client_id, provider="mcp-oauth"
        )

    # No access token — auth is disabled (dev mode).
    # Resolve SessionUser from Dishka container so MCP tools use
    # the same user identity as API endpoints.
    logger.debug("MCP: No access token, resolving user from DI container")
    return cast(SessionUser, await _resolve_dependency(SessionUser))


async def get_current_user_id() -> str:
    """Get the current authenticated user id for the MCP request."""
    user = await get_session_user()
    return user.id


async def get_async_connection() -> AsyncConnection:
    """Resolve the active request-scoped database connection."""
    return cast(AsyncConnection, await _resolve_dependency(AsyncConnection))


async def get_immich_token_service() -> ImmichTokenService:
    """Resolve the Immich token service for the current MCP request."""
    return cast(ImmichTokenService, await _resolve_dependency(ImmichTokenService))


async def get_immich_album_creation_service() -> Any:
    """Resolve the Immich album creation service for the current MCP request."""
    from app.core.integrations.immich.album_creation_service import (
        ImmichAlbumCreationService,
    )

    return cast(
        ImmichAlbumCreationService,
        await _resolve_dependency(ImmichAlbumCreationService),
    )


async def get_contact_service() -> ContactService:
    """Resolve the contact service for the current MCP request."""
    return cast(ContactService, await _resolve_dependency(ContactService))


async def get_upcoming_important_dates_service() -> UpcomingImportantDatesService:
    """Resolve the upcoming-dates read for the current MCP request."""
    return cast(
        UpcomingImportantDatesService,
        await _resolve_dependency(UpcomingImportantDatesService),
    )


async def get_contact_merge_service() -> ContactMergeService:
    """Resolve the contact merge service for the current MCP request."""
    return cast(ContactMergeService, await _resolve_dependency(ContactMergeService))


async def get_activity_stats_repository() -> ActivityStatsRepository:
    """Resolve the activity stats repository for the current MCP request."""
    return cast(
        ActivityStatsRepository, await _resolve_dependency(ActivityStatsRepository)
    )


async def get_search_service() -> SearchService:
    """Resolve the search service for the current MCP request."""
    return cast(SearchService, await _resolve_dependency(SearchService))


async def get_tag_repository() -> TagRepository:
    """Resolve the contact tag repository for the current MCP request."""
    return cast(TagRepository, await _resolve_dependency(TagRepository))


async def get_tag_service() -> TagService:
    """Resolve the contact tag service for the current MCP request."""
    return cast(TagService, await _resolve_dependency(TagService))


async def get_outbox_event_publisher() -> OutboxEventPublisher:
    """Resolve the outbox event publisher for the current MCP request."""
    return cast(OutboxEventPublisher, await _resolve_dependency(OutboxEventPublisher))


async def get_contact_relationship_service() -> ContactRelationshipService:
    """Resolve the contact relationship service for the current MCP request."""
    return cast(
        ContactRelationshipService,
        await _resolve_dependency(ContactRelationshipService),
    )


async def get_daily_summary_service() -> DailySummaryService:
    """Resolve the daily summary service for the current MCP request."""
    return cast(DailySummaryService, await _resolve_dependency(DailySummaryService))


async def get_calendar_service() -> CalendarService:
    """Resolve the calendar service for the current MCP request."""
    return cast(CalendarService, await _resolve_dependency(CalendarService))


async def get_review_item_service() -> ReviewItemService:
    """Resolve the review item service for the current MCP request."""
    return cast(ReviewItemService, await _resolve_dependency(ReviewItemService))


async def get_incomplete_outdoor_activity_service() -> IncompleteOutdoorActivityService:
    """Resolve the incomplete outdoor activity service for the current MCP request."""
    return cast(
        IncompleteOutdoorActivityService,
        await _resolve_dependency(IncompleteOutdoorActivityService),
    )


async def get_outdoor_activity_dismissal_service() -> OutdoorActivityDismissalService:
    """Resolve the outdoor activity dismissal service for the current MCP request."""
    return cast(
        OutdoorActivityDismissalService,
        await _resolve_dependency(OutdoorActivityDismissalService),
    )


async def get_outdoor_dashboard_service() -> OutdoorDashboardService:
    """Resolve the outdoor dashboard service for the current MCP request."""
    return cast(
        OutdoorDashboardService,
        await _resolve_dependency(OutdoorDashboardService),
    )


async def get_journal_contact_service() -> JournalContactService:
    """Resolve the journal contact service for the current MCP request."""
    return cast(JournalContactService, await _resolve_dependency(JournalContactService))


async def get_journal_write_service() -> JournalWriteService:
    """Resolve the composite journal write service for the current MCP request."""
    return cast(JournalWriteService, await _resolve_dependency(JournalWriteService))


async def get_journal_series_service() -> JournalSeriesService:
    """Resolve the journal series service for the current MCP request."""
    return cast(JournalSeriesService, await _resolve_dependency(JournalSeriesService))


async def get_activity_template_service() -> ActivityTemplateService:
    """Resolve the activity template service for the current MCP request."""
    return cast(
        ActivityTemplateService, await _resolve_dependency(ActivityTemplateService)
    )


async def get_journal_tag_service() -> JournalTagService:
    """Resolve the journal tag service for the current MCP request."""
    return cast(JournalTagService, await _resolve_dependency(JournalTagService))


async def get_gear_item_service() -> GearItemService:
    """Resolve the gear item service for the current MCP request."""
    return cast(GearItemService, await _resolve_dependency(GearItemService))


async def get_route_service() -> RouteService:
    """Resolve the journal route service for the current MCP request."""
    return cast(RouteService, await _resolve_dependency(RouteService))


async def get_task_service() -> TaskService:
    """Resolve the task service for the current MCP request."""
    return cast(TaskService, await _resolve_dependency(TaskService))


async def get_task_history_service() -> TaskHistoryService:
    """Resolve the task history read service for the current MCP request.

    Reads only, like ``get_task_read_service`` — and it carries the ownership
    check itself, so the tool cannot answer "is this yours?" differently from
    the endpoint.
    """
    return cast(TaskHistoryService, await _resolve_dependency(TaskHistoryService))


async def get_task_read_service() -> TaskReadService:
    """Resolve the task read service for the current MCP request.

    Separate from the write service so a read tool is never handed the ability
    to change a task, which is the same split ``TaskProvider`` makes.
    """
    return cast(TaskReadService, await _resolve_dependency(TaskReadService))


async def get_integration_registry_service() -> Any:
    """Resolve the integration registry service for the current MCP request."""
    from app.core.integrations.registry.service import IntegrationRegistryService

    return cast(
        IntegrationRegistryService,
        await _resolve_dependency(IntegrationRegistryService),
    )


async def get_task_queue_service() -> Any:
    """Resolve the task queue service for the current MCP request."""
    from app.core.integrations.task_queue_service import TaskQueueService

    return cast(TaskQueueService, await _resolve_dependency(TaskQueueService))


async def get_strava_athlete_mapping_service() -> Any:
    """Resolve the strava athlete mapping service for the current MCP request."""
    from app.core.integrations.strava.athlete_mapping_service import (
        StravaAthleteMappingService,
    )

    return cast(
        StravaAthleteMappingService,
        await _resolve_dependency(StravaAthleteMappingService),
    )
