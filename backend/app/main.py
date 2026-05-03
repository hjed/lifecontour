"""
Personal CRM & Journal System - FastAPI Backend

Main application entry point with FastAPI configuration,
middleware setup, and route registration.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from core_shared.telemetry import setup_telemetry
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastmcp.utilities.lifespan import combine_lifespans
from starlette.middleware.sessions import SessionMiddleware

from app.infrastructure.config import Settings, get_settings
from app.infrastructure.database import get_database_engine
from app.infrastructure.di.container import create_container
from app.infrastructure.events.outbox_relay import run_outbox_relay_loop
from app.infrastructure.logging import setup_logging
from app.infrastructure.tasks.attendance_transition_task import (
    run_attendance_transition_loop,
)
from app.mcp.server import create_mcp_app


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown events."""
    settings: Settings = app.state.settings
    logger = structlog.get_logger()

    logger.info("Starting Personal Management System Backend", version="0.1.0")

    # Initialize database
    get_database_engine()
    logger.info("Database engine initialized")

    # Setup Dishka container (get from app state)
    container = app.state.dishka_container
    logger.info("Dishka container initialized")

    # Start background tasks
    attendance_task = None
    relay_task = None
    search_consumer_task = None
    summary_consumer_task = None
    inbound_consumer_task = None
    try:
        # Start attendance transition background task (hourly)
        attendance_task = asyncio.create_task(
            run_attendance_transition_loop(container, interval_seconds=3600)
        )
        logger.info("Attendance transition background task started")

        # Start the Redis Streams outbox relay
        from core_shared.stream_client import StreamClient

        stream_client = await container.get(StreamClient)
        relay_task = asyncio.create_task(
            run_outbox_relay_loop(
                stream_client,
                stream_name=settings.stream_name,
                batch_size=settings.stream_relay_batch_size,
                interval_seconds=settings.stream_relay_poll_interval,
            )
        )
        logger.info(
            "Outbox relay background task started",
            stream=settings.stream_name,
        )

        # Start stream consumers for search indexing and summary generation
        from app.infrastructure.events.search_indexer_consumer import (
            SearchIndexerConsumer,
        )
        from app.infrastructure.events.summary_consumer import SummaryConsumer

        search_consumer = SearchIndexerConsumer(
            stream_client=stream_client,
            stream_name=settings.stream_name,
        )
        search_consumer_task = asyncio.create_task(search_consumer.start())
        logger.info(
            "Search indexer consumer started",
            group="search-indexer",
            stream=settings.stream_name,
        )

        summary_consumer = SummaryConsumer(
            stream_client=stream_client,
            container=container,
            stream_name=settings.stream_name,
        )
        summary_consumer_task = asyncio.create_task(summary_consumer.start())
        logger.info(
            "Summary generator consumer started",
            group="summary-generator",
            stream=settings.stream_name,
        )

        # Start stream consumer for inbound sync events
        from app.infrastructure.events.inbound_event_consumer import (
            InboundEventConsumer,
        )

        inbound_consumer = InboundEventConsumer(
            stream_client=stream_client,
            container=container,
            settings=settings,
            stream_name=settings.stream_name,
        )
        inbound_consumer_task = asyncio.create_task(inbound_consumer.start())
        logger.info(
            "Inbound event consumer started",
            group="inbound-processor",
            stream=settings.stream_name,
        )

        yield

    finally:
        # Collect all active background tasks for cleanup
        active_tasks: list[tuple[asyncio.Task[None], str]] = []
        for task, name in [
            (inbound_consumer_task, "Inbound event consumer"),
            (summary_consumer_task, "Summary generator consumer"),
            (search_consumer_task, "Search indexer consumer"),
            (relay_task, "Outbox relay"),
            (attendance_task, "Attendance transition"),
        ]:
            if task:
                task.cancel()
                active_tasks.append((task, name))

        # Await all cancelled tasks concurrently; return_exceptions=True
        # ensures we don't abort mid-cleanup if one raises.
        if active_tasks:
            results = await asyncio.gather(
                *(t for t, _ in active_tasks), return_exceptions=True
            )
            for (_, name), result in zip(active_tasks, results, strict=True):
                if isinstance(result, asyncio.CancelledError):
                    logger.info(f"{name} background task stopped")
                elif isinstance(result, BaseException):
                    logger.error(
                        f"{name} background task raised during shutdown",
                        error=str(result),
                    )
                else:
                    logger.info(f"{name} background task stopped")

        # Close Dishka container
        await container.close()
        logger.info("Dishka container closed")

        logger.info("Shutting down Personal Management System Backend")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = get_settings()

    # Create Dishka container once, shared between main app and MCP
    container = create_container(settings)

    # Create MCP app early so its lifespan can be combined with the parent app's.
    # FastMCP's StreamableHTTPSessionManager requires its lifespan to be passed
    # to the parent ASGI app's constructor — see https://gofastmcp.com/deployment/http
    mcp_app = None
    if settings.mcp_enabled:
        from app.mcp.auth.providers import create_mcp_auth_provider

        auth_provider = create_mcp_auth_provider(settings)
        mcp_app = create_mcp_app(container, auth_provider=auth_provider)
    else:
        auth_provider = None

    # Combine our lifespan with MCP lifespan using FastMCP's utility
    combined_lifespan: Any = lifespan
    if mcp_app is not None:
        mcp_lifespan = getattr(mcp_app, "lifespan", None)
        if mcp_lifespan is not None:
            combined_lifespan = combine_lifespans(lifespan, mcp_lifespan)

    app = FastAPI(
        title="Personal CRM & Journal System",
        description="A personal relationship management and journaling system with AI integration",
        version="0.1.0",
        docs_url="/api/docs" if settings.debug else None,
        redoc_url="/api/redoc" if settings.debug else None,
        openapi_url="/api/openapi.json" if settings.debug else None,
        lifespan=combined_lifespan,
    )

    # Setup logging early so basicConfig runs before OTEL adds handlers
    setup_logging(settings.log_level)

    # Setup OpenTelemetry BEFORE middleware and routes are compiled by Uvicorn/Starlette
    setup_telemetry(settings, app)

    # Setup Dishka dependency injection
    app.state.settings = settings
    app.state.dishka_container = container  # Store for lifespan access
    app.state.mcp_app = mcp_app
    setup_dishka(container, app)

    # Import routers after Dishka setup to avoid type annotation issues
    from app.api.auth.controllers import router as auth_router
    from app.api.calendars.controllers import router as calendars_router
    from app.api.contacts.controllers import router as contacts_router
    from app.api.contacts.custom_date_type_controllers import (
        router as custom_date_types_router,
    )
    from app.api.contacts.enum_controllers import router as enums_router
    from app.api.contacts.relationship_controllers import router as relationships_router
    from app.api.error_handlers import register_error_handlers
    from app.api.health import router as health_router
    from app.api.integrations.controllers import router as integrations_router
    from app.api.integrations.strava_controllers import router as strava_router
    from app.api.journals.activity_template_controller import (
        router as activity_template_router,
    )
    from app.api.journals.controllers import router as journals_router
    from app.api.journals.daily_summary_controller import (
        daily_summary_router,
    )
    from app.api.journals.gear_item_controller import (
        router as gear_item_router,
    )
    from app.api.routes.controllers import router as routes_router
    from app.api.search.controllers import router as search_router
    from app.api.tags.controllers import router as tags_router

    # Session middleware (must be added before other middleware that uses sessions)
    # Using standard Starlette SessionMiddleware
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret_key,
        max_age=86400 * 7,  # 7 days
        same_site="lax",
        https_only=not settings.debug,
    )

    # Security middleware
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_hosts,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    # Include routers
    app.include_router(health_router, prefix="/api", tags=["health"])
    app.include_router(auth_router, prefix="/api/auth", tags=["authentication"])
    app.include_router(search_router, prefix="/api", tags=["search"])
    app.include_router(enums_router, prefix="/api/contacts", tags=["contacts"])
    app.include_router(contacts_router, prefix="/api", tags=["contacts"])
    app.include_router(relationships_router, prefix="/api", tags=["relationships"])
    app.include_router(custom_date_types_router, prefix="/api", tags=["contacts"])
    app.include_router(journals_router, prefix="/api", tags=["journals"])
    app.include_router(activity_template_router, prefix="/api")
    app.include_router(gear_item_router, prefix="/api")
    app.include_router(daily_summary_router, prefix="/api", tags=["journals"])
    app.include_router(routes_router, prefix="/api")
    app.include_router(calendars_router, prefix="/api", tags=["calendars"])
    app.include_router(tags_router, prefix="/api", tags=["tags"])
    app.include_router(integrations_router, prefix="/api", tags=["integrations"])
    app.include_router(strava_router, prefix="/api", tags=["integrations-strava"])

    # Mount MCP server if enabled (mcp_app was already created above for lifespan)
    if settings.mcp_enabled and mcp_app is not None:
        mcp_logger = structlog.get_logger()
        mcp_logger.info("MCP: Mounting MCP server", mount_path=settings.mcp_mount_path)

        app.mount(settings.mcp_mount_path, mcp_app)  # type: ignore[arg-type]

        # Mount .well-known discovery routes at root level (required by MCP spec)
        if auth_provider is not None:
            well_known_routes = auth_provider.get_well_known_routes(mcp_path="/mcp")
            # Insert all .well-known routes at the front while preserving order
            app.routes[0:0] = well_known_routes
            mcp_logger.info(
                "MCP: Mounted .well-known OAuth discovery routes",
                route_count=len(well_known_routes),
            )

        mcp_logger.info(
            "MCP: Server mounted successfully",
            endpoint=f"{settings.mcp_mount_path}/mcp",
            auth_enabled=auth_provider is not None,
        )

    return app


def run_app(settings: Settings | None = None) -> None:
    """Run the application with the configured host and port."""
    import uvicorn

    resolved_settings = settings or get_settings()
    uvicorn.run(
        "app.main:app",
        host=resolved_settings.host,
        port=resolved_settings.port,
        reload=resolved_settings.debug,
        log_level=resolved_settings.log_level.lower(),
    )


# Create the application instance
app = create_app()


if __name__ == "__main__":
    run_app()
